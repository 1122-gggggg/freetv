import React, { useEffect, useState } from 'react'
import {
  ActivityIndicator,
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
import { checkDeviceHealth, type DiscoveredBox, pairWithDevice } from '../discovery/deviceScanner'
import { parsePairingPayload } from '../discovery/qrScanner'
import { getSavedDevices, type SavedDevice, saveCurrentDevice } from '../storage/tokenStorage'

interface DiscoveryScreenProps {
  onDeviceConnected: (device: SavedDevice) => void
}

export function DiscoveryScreen({ onDeviceConnected }: DiscoveryScreenProps): React.ReactElement {
  const [permission, requestPermission] = useCameraPermissions()
  const [isScanningQR, setIsScanningQR] = useState(false)
  const [manualHost, setManualHost] = useState('')
  const [manualPort, setManualPort] = useState('8765')
  const [pairingCode, setPairingCode] = useState('')
  const [selectedBox, setSelectedBox] = useState<{ host: string; port: number } | null>(null)
  const [showPairModal, setShowPairModal] = useState(false)
  const [isPairing, setIsPairing] = useState(false)
  const [savedDevices, setSavedDevices] = useState<SavedDevice[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [discoveredBoxes, setDiscoveredBoxes] = useState<DiscoveredBox[]>([])

  useEffect(() => {
    loadSaved()
    scanLocalNetwork()
  }, [])

  const loadSaved = async () => {
    const list = await getSavedDevices()
    setSavedDevices(list)
  }

  const scanLocalNetwork = async () => {
    setIsSearching(true)
    const candidates = ['172.20.10.8', '10.0.0.102', '192.168.1.100', '192.168.0.100', '127.0.0.1']
    const found: DiscoveredBox[] = []

    await Promise.all(
      candidates.map(async (ip) => {
        const box = await checkDeviceHealth(ip, 8765, 1500)
        if (box) found.push(box)
      })
    )

    setDiscoveredBoxes(found)
    setIsSearching(false)
  }

  const handleBarCodeScanned = async ({ data }: { data: string }) => {
    setIsScanningQR(false)
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)
    const parsed = parsePairingPayload(data)
    if (!parsed) {
      Alert.alert('Invalid QR Code', 'The scanned QR code is not a valid PC TV Box pairing code.')
      return
    }

    const host = parsed.host || manualHost.trim() || '172.20.10.8'
    const port = parsed.port || 8765

    if (parsed.code) {
      // Direct pair!
      await performPairing(host, port, parsed.code)
    } else {
      setSelectedBox({ host, port })
      setShowPairModal(true)
    }
  }

  const performPairing = async (host: string, port: number, code: string) => {
    setIsPairing(true)
    try {
      const result = await pairWithDevice(host, port, code)
      if ('token' in result) {
        const device: SavedDevice = {
          id: `${host}:${port}`,
          name: `PC TV (${host})`,
          host,
          port,
          token: result.token,
          lastConnected: Date.now(),
        }
        await saveCurrentDevice(device)
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)
        setShowPairModal(false)
        onDeviceConnected(device)
      } else {
        Alert.alert('Pairing Failed', result.error)
      }
    } finally {
      setIsPairing(false)
    }
  }

  const handleOpenQRScanner = async () => {
    if (!permission?.granted) {
      const res = await requestPermission()
      if (!res.granted) {
        Alert.alert('Camera Permission Required', 'Please enable camera permission in system settings to scan the TV pairing QR code.')
        return
      }
    }
    setIsScanningQR(true)
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.eyebrow}>PC TV BOX</Text>
        <Text style={styles.title}>Connect Your TV</Text>
        <Text style={styles.subtitle}>Scan the QR code on your TV screen or select a discovered device on your Wi-Fi.</Text>
      </View>

      {/* Primary Action: QR Code Scan */}
      <TouchableOpacity style={styles.qrButton} onPress={handleOpenQRScanner}>
        <Text style={styles.qrIcon}>📷</Text>
        <View style={styles.qrTextCol}>
          <Text style={styles.qrButtonTitle}>SCAN TV QR CODE</Text>
          <Text style={styles.qrButtonDesc}>Point camera at the QR code on the TV screen</Text>
        </View>
      </TouchableOpacity>

      {/* Discovered / Saved Devices Section */}
      <View style={styles.section}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>DISCOVERED TVS</Text>
          <TouchableOpacity onPress={scanLocalNetwork} disabled={isSearching}>
            <Text style={styles.refreshText}>{isSearching ? 'Searching...' : '🔄 Rescan'}</Text>
          </TouchableOpacity>
        </View>

        {isSearching && (
          <View style={styles.loadingRow}>
            <ActivityIndicator color="#f7d488" size="small" />
            <Text style={styles.searchingText}>Scanning local network...</Text>
          </View>
        )}

        <FlatList
          data={[...discoveredBoxes, ...savedDevices.map((d) => ({ id: d.id, name: d.name, host: d.host, port: d.port, braveAvailable: true, edgeAvailable: true, mpvAvailable: true }))]}
          keyExtractor={(item, index) => `${item.host}-${index}`}
          renderItem={({ item }) => (
            <TouchableOpacity
              style={styles.deviceCard}
              onPress={() => {
                const saved = savedDevices.find((d) => d.host === item.host && d.port === item.port)
                if (saved) {
                  onDeviceConnected(saved)
                } else {
                  setSelectedBox({ host: item.host, port: item.port })
                  setShowPairModal(true)
                }
              }}
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
            !isSearching ? (
              <Text style={styles.emptyText}>No PC TV Box found automatically. Try scanning the QR code or enter the IP below.</Text>
            ) : null
          }
        />
      </View>

      {/* Manual Connection Option */}
      <View style={styles.manualCard}>
        <Text style={styles.manualTitle}>MANUAL CONNECT</Text>
        <View style={styles.manualRow}>
          <TextInput
            style={[styles.input, { flex: 2 }]}
            placeholder="IP Address (e.g. 172.20.10.8)"
            placeholderTextColor="#64748b"
            value={manualHost}
            onChangeText={setManualHost}
            autoCapitalize="none"
          />
          <TextInput
            style={[styles.input, { flex: 1 }]}
            placeholder="Port"
            placeholderTextColor="#64748b"
            value={manualPort}
            onChangeText={setManualPort}
            keyboardType="number-pad"
          />
          <TouchableOpacity
            style={styles.manualBtn}
            onPress={() => {
              if (!manualHost.trim()) {
                Alert.alert('Error', 'Please enter the TV Box IP address.')
                return
              }
              setSelectedBox({ host: manualHost.trim(), port: parseInt(manualPort, 10) || 8765 })
              setShowPairModal(true)
            }}
          >
            <Text style={styles.manualBtnText}>PAIR</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* QR Scanner Modal */}
      <Modal visible={isScanningQR} animationType="slide" onRequestClose={() => setIsScanningQR(false)}>
        <View style={styles.scannerModal}>
          <CameraView
            style={StyleSheet.absoluteFill}
            facing="back"
            barcodeScannerSettings={{
              barcodeTypes: ['qr'],
            }}
            onBarcodeScanned={handleBarCodeScanned}
          />
          <View style={styles.scannerOverlay}>
            <Text style={styles.scannerTitle}>ALIGN QR CODE WITHIN FRAME</Text>
            <View style={styles.scanTarget} />
            <TouchableOpacity style={styles.closeScannerBtn} onPress={() => setIsScanningQR(false)}>
              <Text style={styles.closeScannerText}>CLOSE SCANNER</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* 6-Digit Pairing Modal */}
      <Modal visible={showPairModal} transparent animationType="fade" onRequestClose={() => setShowPairModal(false)}>
        <View style={styles.modalOverlay}>
          <View style={styles.pairCard}>
            <Text style={styles.pairCardTitle}>ENTER 6-DIGIT CODE</Text>
            <Text style={styles.pairCardDesc}>
              Enter the pairing code displayed at the bottom-left of your TV screen.
            </Text>

            <TextInput
              style={styles.codeInput}
              placeholder="000000"
              placeholderTextColor="#475569"
              keyboardType="number-pad"
              maxLength={6}
              value={pairingCode}
              onChangeText={setPairingCode}
              autoFocus
            />

            <View style={styles.pairActions}>
              <TouchableOpacity style={styles.cancelPairBtn} onPress={() => setShowPairModal(false)}>
                <Text style={styles.cancelPairText}>CANCEL</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.confirmPairBtn, (pairingCode.length !== 6 || isPairing) && { opacity: 0.5 }]}
                disabled={pairingCode.length !== 6 || isPairing}
                onPress={() => {
                  if (selectedBox) {
                    performPairing(selectedBox.host, selectedBox.port, pairingCode)
                  }
                }}
              >
                <Text style={styles.confirmPairText}>{isPairing ? 'PAIRING...' : 'CONFIRM'}</Text>
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
    paddingTop: 50,
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
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  sectionTitle: {
    color: '#8da0b8',
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 1.5,
  },
  refreshText: {
    color: '#f7d488',
    fontSize: 12,
    fontWeight: '600',
  },
  loadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginVertical: 8,
  },
  searchingText: {
    color: '#94a3b8',
    fontSize: 13,
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
    height: 42,
    fontSize: 14,
  },
  manualBtn: {
    backgroundColor: '#f7d488',
    borderRadius: 10,
    paddingHorizontal: 16,
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
    height: 46,
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
    height: 46,
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
