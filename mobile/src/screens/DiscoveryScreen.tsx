import React, { useEffect, useRef, useState } from 'react'
import {
  Alert,
  FlatList,
  Modal,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import { CameraView, useCameraPermissions } from 'expo-camera'
import * as Haptics from 'expo-haptics'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { validateControllerTarget } from '../api/controllerEndpoint'
import { pairWithDevice } from '../discovery/deviceScanner'
import { parsePairingPayload, resolvePairingTarget } from '../discovery/qrScanner'
import { getSavedDevices, type SavedDevice, saveCurrentDevice } from '../storage/tokenStorage'

interface DiscoveryScreenProps {
  onDeviceConnected: (device: SavedDevice) => void
}

export function DiscoveryScreen({ onDeviceConnected }: DiscoveryScreenProps): React.ReactElement {
  const insets = useSafeAreaInsets()
  const [permission, requestPermission] = useCameraPermissions()
  const [isScanningQR, setIsScanningQR] = useState(false)
  const [manualHost, setManualHost] = useState('')
  const [manualPort, setManualPort] = useState('8765')
  const [pairingCode, setPairingCode] = useState('')
  const [selectedBox, setSelectedBox] = useState<{ host: string; port: number } | null>(null)
  const [showPairModal, setShowPairModal] = useState(false)
  const [isPairing, setIsPairing] = useState(false)
  const [savedDevices, setSavedDevices] = useState<SavedDevice[]>([])

  const isPairingRef = useRef(false)
  const isScanningLockRef = useRef(false)

  useEffect(() => {
    void loadSaved()
  }, [])

  const loadSaved = async () => {
    const list = await getSavedDevices()
    setSavedDevices(list)
  }

  const handleCancelPairModal = () => {
    if (isPairingRef.current) {
      return
    }
    setShowPairModal(false)
    setPairingCode('')
    setSelectedBox(null)
  }

  const performPairing = async (host: string, port: number, code: string) => {
    if (isPairingRef.current) {
      return
    }
    const sanitizedCode = code.replace(/[^0-9]/g, '').slice(0, 6)
    if (sanitizedCode.length !== 6) {
      Alert.alert('代碼無效', '配對碼須為 6 位數字。')
      return
    }

    isPairingRef.current = true
    setIsPairing(true)

    try {
      const result = await pairWithDevice(host, port, sanitizedCode)
      if ('token' in result) {
        const device: SavedDevice = {
          id: `${host}:${port}`,
          name: `電腦電視盒 (${host})`,
          host,
          port,
          token: result.token,
          lastConnected: Date.now(),
        }
        await saveCurrentDevice(device)
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)
        setShowPairModal(false)
        setPairingCode('')
        setSelectedBox(null)
        onDeviceConnected(device)
      } else {
        Alert.alert('配對失敗', result.error)
      }
    } catch (error) {
      Alert.alert(
        '配對失敗',
        error instanceof Error ? error.message : '無法安全儲存此次配對。',
      )
    } finally {
      isPairingRef.current = false
      setIsPairing(false)
    }
  }

  const handleBarCodeScanned = async ({ data }: { data: string }) => {
    if (isScanningLockRef.current || isPairingRef.current) {
      return
    }
    isScanningLockRef.current = true

    const parsed = parsePairingPayload(data)
    if (!parsed) {
      isScanningLockRef.current = false
      Alert.alert('QR 碼無效', '掃描的 QR 碼不是有效的電視盒配對碼。')
      return
    }

    const target = resolvePairingTarget(parsed, manualHost, manualPort)
    if (!target) {
      isScanningLockRef.current = false
      Alert.alert('需要控制器位址', '掃描僅含代碼的 QR 碼前，請先輸入電視盒 IP 位址。')
      return
    }

    let validatedTarget: { host: string; port: number }
    try {
      validatedTarget = validateControllerTarget(target.host, target.port)
    } catch (error) {
      isScanningLockRef.current = false
      Alert.alert('位址無效', error instanceof Error ? error.message : '控制器主機或連接埠無效。')
      return
    }

    if (parsed.code) {
      const sanitizedCode = parsed.code.replace(/[^0-9]/g, '').slice(0, 6)
      if (sanitizedCode.length !== 6) {
        isScanningLockRef.current = false
        Alert.alert('QR 碼無效', '掃描的 QR 碼未包含有效的 6 位數字代碼。')
        return
      }
      setIsScanningQR(false)
      await performPairing(validatedTarget.host, validatedTarget.port, sanitizedCode)
      isScanningLockRef.current = false
    } else {
      setIsScanningQR(false)
      setPairingCode('')
      setSelectedBox(validatedTarget)
      setShowPairModal(true)
      isScanningLockRef.current = false
    }
  }

  const handleOpenQRScanner = async () => {
    if (isPairingRef.current) {
      return
    }
    isScanningLockRef.current = false
    if (!permission?.granted) {
      const res = await requestPermission()
      if (!res.granted) {
        Alert.alert('需要相機權限', '請在系統設定中開啟相機權限，才能掃描電視配對 QR 碼。')
        return
      }
    }
    setIsScanningQR(true)
  }

  const handleCloseQRScanner = () => {
    isScanningLockRef.current = false
    setIsScanningQR(false)
  }

  const handleManualPair = () => {
    if (isPairingRef.current) {
      return
    }
    try {
      const target = validateControllerTarget(manualHost, manualPort)
      setPairingCode('')
      setSelectedBox(target)
      setShowPairModal(true)
    } catch (error) {
      Alert.alert(
        '端點無效',
        error instanceof Error ? error.message : '請輸入有效的 IPv4 位址與連接埠。',
      )
    }
  }
  return (
    <View
      style={[
        styles.container,
        { paddingTop: insets.top + 20, paddingBottom: insets.bottom + 20 },
      ]}
    >
      <View style={styles.header}>
        <Text style={styles.eyebrow}>電腦電視盒</Text>
        <Text style={styles.title}>連接你的電視</Text>
        <Text style={styles.subtitle}>掃描電視畫面上的 QR 碼，或在下方輸入區網 IP。</Text>
      </View>

      {/* Primary Action: QR Code Scan */}
      <TouchableOpacity style={styles.qrButton} onPress={handleOpenQRScanner}>
        <Text style={styles.qrIcon}>📷</Text>
        <View style={styles.qrTextCol}>
          <Text style={styles.qrButtonTitle}>掃描電視 QR 碼</Text>
          <Text style={styles.qrButtonDesc}>將相機對準電視畫面的 QR 碼</Text>
        </View>
      </TouchableOpacity>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>已儲存的電視</Text>

        <FlatList
          data={savedDevices}
          keyExtractor={(item, index) => `${item.host}-${index}`}
          renderItem={({ item }) => (
            <TouchableOpacity
              style={styles.deviceCard}
              onPress={() => onDeviceConnected(item)}
            >
              <View style={styles.deviceIcon}>
                <Text style={{ fontSize: 20 }}>📺</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.deviceName}>{item.name}</Text>
                <Text style={styles.deviceHost}>{item.host}:{item.port}</Text>
              </View>
              <Text style={styles.connectArrow}>➔</Text>
            </TouchableOpacity>
          )}
          ListEmptyComponent={
            <Text style={styles.emptyText}>
              尚未儲存電視盒。請掃描 QR 碼或在下方輸入 IP。
            </Text>
          }
        />
      </View>

      {/* Manual Connection Option */}
      <View style={styles.manualCard}>
        <Text style={styles.manualTitle}>手動連線</Text>
        <View style={styles.manualRow}>
          <TextInput
            style={[styles.input, { flex: 2 }]}
            placeholder="IP 位址（例如 172.20.10.8）"
            placeholderTextColor="#64748b"
            value={manualHost}
            onChangeText={setManualHost}
            autoCapitalize="none"
          />
          <TextInput
            style={[styles.input, { flex: 1 }]}
            placeholder="連接埠"
            placeholderTextColor="#64748b"
            value={manualPort}
            onChangeText={setManualPort}
            keyboardType="number-pad"
          />
          <TouchableOpacity
            style={styles.manualBtn}
            onPress={handleManualPair}
          >
            <Text style={styles.manualBtnText}>配對</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* QR Scanner Modal */}
      <Modal visible={isScanningQR} animationType="slide" onRequestClose={handleCloseQRScanner}>
        <View style={styles.scannerModal}>
          <CameraView
            style={StyleSheet.absoluteFill}
            facing="back"
            barcodeScannerSettings={{
              barcodeTypes: ['qr'],
            }}
            onBarcodeScanned={handleBarCodeScanned}
          />
          <View
            style={[
              styles.scannerOverlay,
              { paddingTop: insets.top + 20, paddingBottom: insets.bottom + 20 },
            ]}
          >
            <Text style={styles.scannerTitle}>將 QR 碼對準框內</Text>
            <View style={styles.scanTarget} />
            <TouchableOpacity style={styles.closeScannerBtn} onPress={handleCloseQRScanner}>
              <Text style={styles.closeScannerText}>關閉掃描</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* 6-Digit Pairing Modal */}
      <Modal visible={showPairModal} transparent animationType="fade" onRequestClose={handleCancelPairModal}>
        <View
          style={[
            styles.modalOverlay,
            { paddingTop: insets.top + 20, paddingBottom: insets.bottom + 20 },
          ]}
        >
          <View style={styles.pairCard}>
            <Text style={styles.pairCardTitle}>輸入 6 位數代碼</Text>
            <Text style={styles.pairCardDesc}>
              輸入電視畫面左下角顯示的配對碼。
            </Text>

            <TextInput
              style={styles.codeInput}
              placeholder="000000"
              placeholderTextColor="#475569"
              keyboardType="number-pad"
              maxLength={6}
              value={pairingCode}
              editable={!isPairing}
              onChangeText={(text) => {
                const sanitized = text.replace(/[^0-9]/g, '').slice(0, 6)
                setPairingCode(sanitized)
              }}
              autoFocus
            />

            <View style={styles.pairActions}>
              <TouchableOpacity
                style={[styles.cancelPairBtn, isPairing && { opacity: 0.5 }]}
                disabled={isPairing}
                onPress={handleCancelPairModal}
              >
                <Text style={styles.cancelPairText}>取消</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.confirmPairBtn, (pairingCode.length !== 6 || isPairing) && { opacity: 0.5 }]}
                disabled={pairingCode.length !== 6 || isPairing}
                onPress={() => {
                  if (isPairingRef.current) {
                    return
                  }
                  if (selectedBox && pairingCode.length === 6) {
                    void performPairing(selectedBox.host, selectedBox.port, pairingCode)
                  }
                }}
              >
                <Text style={styles.confirmPairText}>{isPairing ? '配對中…' : '確認'}</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0c111d',
    padding: 20,
  },
  header: {
    marginBottom: 20,
  },
  eyebrow: {
    color: '#f7d488',
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 2,
  },
  title: {
    color: '#f8fafc',
    fontSize: 28,
    fontWeight: '800',
    marginTop: 4,
  },
  subtitle: {
    color: '#94a3b8',
    fontSize: 14,
    marginTop: 6,
  },
  qrButton: {
    backgroundColor: '#27354a',
    borderColor: '#4d6994',
    borderWidth: 1.5,
    borderRadius: 16,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 24,
  },
  qrIcon: {
    fontSize: 32,
    marginRight: 14,
  },
  qrTextCol: {
    flex: 1,
  },
  qrButtonTitle: {
    color: '#f7d488',
    fontSize: 16,
    fontWeight: '800',
  },
  qrButtonDesc: {
    color: '#cbd5e1',
    fontSize: 12,
    marginTop: 2,
  },
  section: {
    flex: 1,
    marginBottom: 16,
  },
  sectionTitle: {
    color: '#8da0b8',
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 1.5,
    marginBottom: 10,
  },
  deviceCard: {
    backgroundColor: '#1b2535',
    borderColor: '#36435a',
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 10,
  },
  deviceIcon: {
    width: 42,
    height: 42,
    borderRadius: 10,
    backgroundColor: '#273449',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  deviceName: {
    color: '#f8fafc',
    fontSize: 15,
    fontWeight: '700',
  },
  deviceHost: {
    color: '#94a3b8',
    fontSize: 12,
    marginTop: 2,
  },
  connectArrow: {
    color: '#f7d488',
    fontSize: 18,
    fontWeight: 'bold',
  },
  emptyText: {
    color: '#64748b',
    fontSize: 13,
    textAlign: 'center',
    marginVertical: 20,
    lineHeight: 18,
  },
  manualCard: {
    backgroundColor: '#161e2b',
    borderColor: '#2b374e',
    borderWidth: 1,
    borderRadius: 14,
    padding: 14,
  },
  manualTitle: {
    color: '#8da0b8',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 1.5,
    marginBottom: 8,
  },
  manualRow: {
    flexDirection: 'row',
    gap: 8,
  },
  input: {
    backgroundColor: '#0f172a',
    borderColor: '#334155',
    borderWidth: 1,
    borderRadius: 10,
    color: '#f8fafc',
    paddingHorizontal: 12,
    minWidth: 48,
    minHeight: 48,
    fontSize: 14,
  },
  manualBtn: {
    backgroundColor: '#f7d488',
    borderRadius: 10,
    paddingHorizontal: 16,
    minWidth: 48,
    minHeight: 48,
    justifyContent: 'center',
    alignItems: 'center',
  },
  manualBtnText: {
    color: '#141820',
    fontWeight: '800',
    fontSize: 13,
  },
  scannerModal: {
    flex: 1,
    backgroundColor: '#000',
  },
  scannerOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  scannerTitle: {
    color: '#ffffff',
    fontSize: 15,
    fontWeight: '800',
    letterSpacing: 1.5,
    marginBottom: 30,
  },
  scanTarget: {
    width: 240,
    height: 240,
    borderColor: '#f7d488',
    borderWidth: 2,
    borderRadius: 20,
    backgroundColor: 'transparent',
    marginBottom: 40,
  },
  closeScannerBtn: {
    backgroundColor: '#1b2535',
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderRadius: 12,
    borderColor: '#36435a',
    borderWidth: 1,
    minWidth: 48,
    minHeight: 48,
  },
  closeScannerText: {
    color: '#f8fafc',
    fontWeight: '700',
    fontSize: 14,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.75)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  pairCard: {
    width: '100%',
    backgroundColor: '#1b2535',
    borderColor: '#36435a',
    borderWidth: 1,
    borderRadius: 20,
    padding: 24,
  },
  pairCardTitle: {
    color: '#f7d488',
    fontSize: 16,
    fontWeight: '800',
    letterSpacing: 1.5,
  },
  pairCardDesc: {
    color: '#94a3b8',
    fontSize: 13,
    marginTop: 6,
    marginBottom: 20,
  },
  codeInput: {
    backgroundColor: '#0f172a',
    borderColor: '#475569',
    borderWidth: 1.5,
    borderRadius: 14,
    color: '#f7d488',
    fontSize: 32,
    fontWeight: 'bold',
    letterSpacing: 12,
    textAlign: 'center',
    height: 64,
    marginBottom: 20,
  },
  pairActions: {
    flexDirection: 'row',
    gap: 12,
  },
  cancelPairBtn: {
    flex: 1,
    minWidth: 48,
    minHeight: 48,
    borderRadius: 12,
    backgroundColor: '#273449',
    justifyContent: 'center',
    alignItems: 'center',
  },
  cancelPairText: {
    color: '#cbd5e1',
    fontWeight: '700',
  },
  confirmPairBtn: {
    flex: 1,
    minWidth: 48,
    minHeight: 48,
    borderRadius: 12,
    backgroundColor: '#f7d488',
    justifyContent: 'center',
    alignItems: 'center',
  },
  confirmPairText: {
    color: '#141820',
    fontWeight: '800',
  },
})
