import React, { useEffect, useState } from 'react'
import {
  Alert,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native'
import * as Haptics from 'expo-haptics'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { ControllerSocket, type SocketStatus } from '../api/controllerSocket'
import { revokeDeviceToken } from '../discovery/deviceScanner'

import { AppLaunchers } from '../components/AppLaunchers'
import { Dpad } from '../components/Dpad'
import { MediaControls } from '../components/MediaControls'
import { TextInputModal } from '../components/TextInputModal'
import { Trackpad } from '../components/Trackpad'
import { forgetCurrentDevice, type SavedDevice } from '../storage/tokenStorage'
import type {
  Acknowledgement,
  Command,
  ControllerState,
  NetflixInputKind,
  PointerAction,
} from '../types/protocol'

interface RemoteScreenProps {
  device: SavedDevice
  onDisconnect: () => void
}

type ControlMode = 'dpad' | 'touchpad'

interface TextInputSource {
  inputKind: NetflixInputKind
  submit: boolean
}

function formatActiveApp(app: ControllerState['active_app']): string {
  switch (app) {
    case 'youtube':
      return 'YouTube'
    case 'netflix':
      return 'Netflix'
    case 'news':
      return '新聞'
    case 'live_tv':
      return '電視'
    case 'browser':
      return '瀏覽器'
    default:
      return '主畫面'
  }
}


export function RemoteScreen({ device, onDisconnect }: RemoteScreenProps): React.ReactElement {
  const insets = useSafeAreaInsets()
  const [socket, setSocket] = useState<ControllerSocket | null>(null)
  const [status, setStatus] = useState<SocketStatus>('connecting')
  const [hasEverConnected, setHasEverConnected] = useState(false)
  const [controllerState, setControllerState] = useState<ControllerState | null>(null)
  const [mode, setMode] = useState<ControlMode>('dpad')
  const [textInputSource, setTextInputSource] = useState<TextInputSource | null>(null)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const [commandError, setCommandError] = useState<string | null>(null)
  const [isUnpairing, setIsUnpairing] = useState(false)
  const [waitingForNetflix, setWaitingForNetflix] = useState(false)
  const [netflixSendFailed, setNetflixSendFailed] = useState(false)
  const [isUpdating, setIsUpdating] = useState(false)
  useEffect(() => {
    const client = new ControllerSocket({
      host: device.host,
      port: device.port,
      token: device.token,
      onStatusChange: (newStatus) => {
        setStatus(newStatus)
        if (newStatus === 'authenticated') {
          setHasEverConnected(true)
          setConnectionError(null)
          setCommandError(null)
        } else {
          setControllerState(null)
        }
      },
      onStateChange: (newState) => {
        setControllerState(newState)
      },
      onAuthenticationFailed: async () => {
        setConnectionError(null)
        setCommandError(null)
        Alert.alert('連線已過期', '配對權杖已過期或已撤銷。請重新配對。')
        await forgetCurrentDevice()
        client.disconnect()
        onDisconnect()
      },
      onError: (error) => {
        setConnectionError(error.message)
      },
    })

    client.connect()
    setSocket(client)

    return () => {
      client.disconnect()
    }
  }, [device])

  const netflixContext =
    controllerState?.active_app === 'netflix'
      ? (controllerState.netflix_context ?? null)
      : null
  const knownNetflixContext =
    netflixContext !== null && netflixContext.stage !== 'unknown'
  const netflixSemanticKey = JSON.stringify([
    controllerState?.active_app ?? null,
    netflixContext?.stage ?? null,
    netflixContext?.input_kind ?? null,
    netflixContext?.focused_title ?? null,
    netflixContext?.has_error ?? null,
  ])

  useEffect(() => {
    setWaitingForNetflix(false)
    setNetflixSendFailed(false)
    setTextInputSource(null)
  }, [netflixSemanticKey])

  const handleCommand = async (command: Command) => {
    if (!socket || status !== 'authenticated') {
      setCommandError('電視未連線')
      return
    }
    try {
      setCommandError(null)
      const ack = await socket.sendCommand(command)
      if (!ack.success) {
        setCommandError(ack.message || ack.error_code || '指令失敗')
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : '指令失敗'
      setCommandError(message)
    }
  }

  const handlePointer = (action: PointerAction, dx: number, dy: number) => {
    socket?.sendPointer(action, dx, dy)
  }

  const handleSendText = async (text: string, submit: boolean) => {
    if (!socket || status !== 'authenticated') {
      throw new Error('電視未連線')
    }
    if (submit && !netflixContext?.can_submit) {
      setWaitingForNetflix(false)
      setNetflixSendFailed(true)
      throw new Error('Netflix 尚未可送出，請稍後再試')
    }
    if (submit) {
      setWaitingForNetflix(true)
      setNetflixSendFailed(false)
    }
    let ack: Acknowledgement
    try {
      ack = await socket.sendTextInput(text, submit)
    } catch {
      if (submit) {
        setWaitingForNetflix(false)
        setNetflixSendFailed(true)
        throw new Error('無法送出，請重試')
      }
      throw new Error('無法送出文字')
    }
    if (!ack.success) {
      if (submit) {
        setWaitingForNetflix(false)
        setNetflixSendFailed(true)
        throw new Error('無法送出，請重試')
      }
      throw new Error(ack.message || ack.error_code || '無法送出文字')
    }
  }

  const handleLiveSync = (text: string) => {
    if (socket && status === 'authenticated') {
      void socket.sendTextInput(text, false).catch(() => {})
    }
  }

  const executeForget = async () => {
    if (isUnpairing) return
    setIsUnpairing(true)
    try {
      try {
        await revokeDeviceToken(device.host, device.port, device.token)
      } catch {
        Alert.alert(
          '仍保持配對',
          '無法安全撤銷此遙控器。請保持配對、重新連線電視盒後再試一次。',
        )
        return
      }
      await forgetCurrentDevice()
      socket?.disconnect()
      onDisconnect()
    } finally {
      setIsUnpairing(false)
    }
  }

  const handleApplyUpdate = async () => {
    if (isUpdating) return
    setIsUpdating(true)
    try {
      const res = await fetch(`http://${device.host}:${device.port}/api/update/apply`, {
        method: 'POST',
      })
      if (!res.ok) throw new Error('更新失敗')
      Alert.alert('更新成功', '電視盒正在更新並重新載入。')
    } catch {
      Alert.alert('更新失敗', '請確認電視盒與網路連線。')
    } finally {
      setIsUpdating(false)
    }
  }

  const handleForgetPress = () => {
    if (isUnpairing) return
    Alert.alert(
      '解除配對',
      '確定要解除與此電視的配對嗎？之後需重新配對才能控制。',
      [
        { text: '取消', style: 'cancel' },
        {
          text: '解除配對',
          style: 'destructive',
          onPress: () => {
            void executeForget()
          },
        },
      ],
    )
  }
  const isConnected = status === 'authenticated'

  return (
    <View
      style={[
        styles.container,
        { paddingTop: insets.top + 12, paddingBottom: insets.bottom },
      ]}
    >
      {/* Top Header */}
      <View style={styles.header}>
        <View style={styles.headerInfo}>
          <Text style={styles.deviceName}>{device.name}</Text>
          <View style={styles.statusRow}>
            <View
              style={[
                styles.statusDot,
                isConnected ? styles.dotConnected : status === 'connecting' ? styles.dotConnecting : styles.dotDisconnected,
              ]}
            />
            <Text style={styles.statusText}>
              {connectionError ?? (isConnected ? '已連線' : status === 'connecting' ? (hasEverConnected ? '重新連線中…' : '連線中…') : '已斷線')}
            </Text>
          </View>
        </View>

        <TouchableOpacity
          style={[styles.forgetBtn, isUnpairing && styles.disabledBtn]}
          onPress={handleForgetPress}
          disabled={isUnpairing}
          accessibilityRole="button"
          accessibilityLabel={`中斷並解除與 ${device.name} 的配對`}
          accessibilityHint="撤銷此遙控器權限並回到電視選擇畫面。"
          accessibilityState={{ disabled: isUnpairing, busy: isUnpairing }}
        >
          <Text style={styles.forgetText}>{isUnpairing ? '解除中…' : '解除配對'}</Text>
        </TouchableOpacity>
      </View>

      {controllerState?.update_available ? (
        <View style={styles.updateCard}>
          <Text style={styles.updateText}>
            🚀 發現新版本 FreeTV ({controllerState.update_available})
          </Text>
          <TouchableOpacity
            style={[styles.updateBtn, isUpdating && styles.disabledBtn]}
            onPress={() => void handleApplyUpdate()}
            disabled={isUpdating}
          >
            <Text style={styles.updateBtnText}>{isUpdating ? '更新中…' : '立即更新'}</Text>
          </TouchableOpacity>
        </View>
      ) : null}

      {/* Now Controlling Status Readout */}
      {isConnected && controllerState && (
        <View style={styles.stateBanner}>
          <View style={styles.stateLeft}>
            <Text style={styles.stateLabel}>目前控制</Text>
            <Text style={styles.stateApp}>{formatActiveApp(controllerState.active_app)}</Text>
            {controllerState.channel_name && (
              <Text style={styles.channelText}>
                頻道 {String(controllerState.channel_number).padStart(2, '0')} · {controllerState.channel_name}
              </Text>
            )}
            {controllerState.status_message && (
              <Text style={styles.serverStatusText}>{controllerState.status_message}</Text>
            )}
            {controllerState.error_message && (
              <Text style={styles.serverErrorText}>{controllerState.error_message}</Text>
            )}
          </View>
          <View style={styles.stateRight}>
            <Text style={styles.volLabel}>音量</Text>
            <Text style={[styles.volValue, controllerState.muted && styles.mutedValue]}>
              {controllerState.muted ? '靜音' : controllerState.volume}
            </Text>
          </View>
        </View>
      )}

      {isConnected && commandError && (
        <View style={styles.errorBanner}>
          <Text style={styles.errorBannerText}>{commandError}</Text>
        </View>
      )}

      {isConnected && knownNetflixContext ? (
        <View
          style={[
            styles.netflixContextCard,
            netflixContext.has_error && styles.netflixContextError,
          ]}
          accessibilityLabel="Netflix 情境卡"
        >
          <Text style={styles.netflixContextEyebrow}>Netflix 電視情境</Text>
          {netflixContext.has_error ? (
            <Text
              style={styles.netflixErrorText}
              accessibilityRole="alert"
              accessibilityLiveRegion="assertive"
            >
              登入或驗證失敗，請檢查電視畫面後重試
            </Text>
          ) : null}
          {['email', 'password', 'code'].includes(netflixContext.input_kind) ? (
            <>
              <Text style={styles.netflixContextText}>
                {netflixContext.input_kind === 'email'
                  ? '請輸入 Netflix 電子郵件或手機號碼'
                  : netflixContext.input_kind === 'password'
                    ? '請輸入 Netflix 密碼'
                    : '請輸入驗證碼 (OTP)'}
              </Text>
              <TouchableOpacity
                style={[
                  styles.netflixInputButton,
                  (waitingForNetflix || !netflixContext.can_submit) &&
                    styles.disabledBtn,
                ]}
                accessibilityRole="button"
                accessibilityLabel="開啟 Netflix 情境輸入"
                disabled={waitingForNetflix || !netflixContext.can_submit}
                onPress={() => {
                  if (!netflixContext.can_submit) return
                  setTextInputSource({
                    inputKind: netflixContext.input_kind,
                    submit: true,
                  })
                }}
              >
                <Text style={styles.netflixInputButtonText}>輸入並繼續</Text>
              </TouchableOpacity>
            </>
          ) : netflixContext.stage === 'browse' ? (
            <>
              {netflixContext.focused_title ? (
                <Text style={styles.netflixFocusedTitle}>
                  目前選取：{netflixContext.focused_title}
                </Text>
              ) : null}
              <Text style={styles.netflixContextText}>
                左右換片、上下換列，按確定播放。
              </Text>
            </>
          ) : (
            <Text style={styles.netflixContextText}>
              使用方向鍵與確定鍵操作目前 Netflix 畫面。
            </Text>
          )}
          {waitingForNetflix ? (
            <Text
              style={styles.netflixWaitingText}
              accessibilityLabel="等待電視端回應"
              accessibilityLiveRegion="polite"
            >
              等待電視端回應...
            </Text>
          ) : null}
          {netflixSendFailed ? (
            <Text
              style={styles.netflixErrorText}
              accessibilityLiveRegion="polite"
            >
              無法送出，請重試
            </Text>
          ) : null}
        </View>
      ) : null}

      {/* Mode Switcher Tabs */}
      <View
        style={styles.tabs}
        accessibilityRole="tablist"
        accessibilityLabel="遙控模式"
      >
        <TouchableOpacity
          style={[styles.tab, mode === 'dpad' && styles.activeTab]}
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
            setMode('dpad')
          }}
          accessibilityRole="tab"
          accessibilityLabel="方向鍵"
          accessibilityHint="顯示方向鍵以便遙控操作。"
          accessibilityState={{ selected: mode === 'dpad' }}
        >
          <Text style={[styles.tabText, mode === 'dpad' && styles.activeTabText]}>🎮 方向鍵</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.tab, mode === 'touchpad' && styles.activeTab]}
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
            setMode('touchpad')
          }}
          accessibilityRole="tab"
          accessibilityLabel="觸控板"
          accessibilityHint="顯示觸控板以便指標操作。"
          accessibilityState={{ selected: mode === 'touchpad' }}
        >
          <Text style={[styles.tabText, mode === 'touchpad' && styles.activeTabText]}>🖱 觸控板</Text>
        </TouchableOpacity>

        {!knownNetflixContext ? (
          <TouchableOpacity
            style={[styles.textInputBtn, !isConnected && styles.disabledBtn]}
            onPress={() => {
              Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
              setTextInputSource({ inputKind: 'none', submit: false })
            }}
            disabled={!isConnected}
            accessibilityRole="button"
            accessibilityLabel="在電視上輸入文字"
            accessibilityHint="開啟文字欄位，將文字傳送到電視上目前焦點的應用程式。"
            accessibilityState={{ disabled: !isConnected }}
          >
            <Text style={styles.textInputBtnText}>⌨ 輸入</Text>
          </TouchableOpacity>
        ) : null}

        <TouchableOpacity
          style={[styles.textInputBtn, !isConnected && styles.disabledBtn]}
          onPress={() => {
            void handleCommand('TAB')
          }}
          disabled={!isConnected}
          accessibilityRole="button"
          accessibilityLabel="下一欄"
          accessibilityHint="切換到 Netflix 或瀏覽器的下一個輸入欄位。"
          accessibilityState={{ disabled: !isConnected }}
        >
          <Text style={styles.textInputBtnText}>下一欄</Text>
        </TouchableOpacity>
      </View>

      {/* Main Control Area */}
      <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent}>
        {mode === 'dpad' ? (
          <Dpad onCommand={handleCommand} disabled={!isConnected} />
        ) : (
          <Trackpad onPointer={handlePointer} disabled={!isConnected} />
        )}

        <MediaControls
          onCommand={handleCommand}
          disabled={!isConnected}
          muted={isConnected ? controllerState?.muted : undefined}
          volume={isConnected ? controllerState?.volume : undefined}
          brightness={isConnected ? controllerState?.brightness : undefined}
        />

        <AppLaunchers
          onCommand={handleCommand}
          activeApp={isConnected ? controllerState?.active_app : undefined}
          disabled={!isConnected}
        />
      </ScrollView>

      {textInputSource ? (
        <TextInputModal
          visible
          inputKind={textInputSource.inputKind}
          submit={textInputSource.submit}
          canSubmit={
            !textInputSource.submit || Boolean(netflixContext?.can_submit)
          }
          onClose={() => setTextInputSource(null)}
          onSend={handleSendText}
          onLiveSync={handleLiveSync}
        />
      ) : null}
    </View>
  )
}
const styles = StyleSheet.create({
  updateCard: {
    marginHorizontal: 12,
    marginTop: 8,
    padding: 12,
    backgroundColor: '#1e293b',
    borderColor: '#38bdf8',
    borderWidth: 1,
    borderRadius: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  updateText: {
    flex: 1,
    color: '#f7d488',
    fontSize: 13,
    fontWeight: '700',
  },
  updateBtn: {
    backgroundColor: '#f7d488',
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 10,
  },
  updateBtnText: {
    color: '#0f172a',
    fontSize: 12,
    fontWeight: '800',
  },
  container: {
    flex: 1,
    backgroundColor: '#0b0f19',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  headerInfo: {
    flex: 1,
  },
  deviceName: {
    color: '#f8fafc',
    fontSize: 19,
    fontWeight: '800',
    letterSpacing: 0.3,
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 4,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  dotConnected: {
    backgroundColor: '#10b981',
    shadowColor: '#10b981',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.8,
    shadowRadius: 4,
  },
  dotConnecting: {
    backgroundColor: '#f59e0b',
  },
  dotDisconnected: {
    backgroundColor: '#ef4444',
  },
  statusText: {
    color: '#94a3b8',
    fontSize: 12,
    fontWeight: '600',
  },
  forgetBtn: {
    paddingVertical: 8,
    paddingHorizontal: 14,
    minWidth: 48,
    minHeight: 48,
    backgroundColor: '#1e293b',
    borderRadius: 12,
    borderColor: '#334155',
    borderWidth: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  disabledBtn: {
    opacity: 0.4,
  },
  forgetText: {
    color: '#94a3b8',
    fontSize: 12,
    fontWeight: '700',
  },
  stateBanner: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    backgroundColor: '#162132',
    marginHorizontal: 12,
    marginTop: 10,
    padding: 14,
    borderRadius: 18,
    borderColor: '#2b3a50',
    borderWidth: 1,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 4,
  },
  stateLeft: {
    flex: 1,
  },
  stateLabel: {
    color: '#64748b',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 1,
  },
  stateApp: {
    color: '#f7d488',
    fontSize: 17,
    fontWeight: '800',
    marginTop: 2,
  },
  channelText: {
    color: '#cbd5e1',
    fontSize: 13,
    fontWeight: '600',
    marginTop: 3,
  },
  stateRight: {
    alignItems: 'flex-end',
    justifyContent: 'center',
    paddingLeft: 8,
  },
  volLabel: {
    color: '#64748b',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 1,
  },
  volValue: {
    color: '#f8fafc',
    fontSize: 18,
    fontWeight: '800',
    marginTop: 2,
  },
  mutedValue: {
    color: '#f87171',
  },
  serverStatusText: {
    color: '#38bdf8',
    fontSize: 13,
    fontWeight: '700',
    marginTop: 4,
  },
  serverErrorText: {
    color: '#f87171',
    fontSize: 13,
    fontWeight: '600',
    marginTop: 4,
  },
  errorBanner: {
    backgroundColor: '#451a1a',
    borderColor: '#991b1b',
    borderWidth: 1,
    borderRadius: 14,
    marginHorizontal: 12,
    marginTop: 8,
    paddingVertical: 10,
    paddingHorizontal: 14,
  },
  errorBannerText: {
    color: '#fca5a5',
    fontSize: 13,
    fontWeight: '600',
  },
  netflixContextCard: {
    marginHorizontal: 12,
    marginTop: 8,
    padding: 14,
    borderRadius: 18,
    borderColor: '#334155',
    borderWidth: 1,
    backgroundColor: '#0f172a',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 4,
  },
  netflixContextError: {
    borderColor: '#e50914',
  },
  netflixContextEyebrow: {
    color: '#f7d488',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 1,
  },
  netflixContextText: {
    color: '#e2e8f0',
    fontSize: 13,
    lineHeight: 20,
    marginTop: 6,
  },
  netflixFocusedTitle: {
    color: '#f8fafc',
    fontSize: 16,
    fontWeight: '800',
    marginTop: 6,
  },
  netflixInputButton: {
    minHeight: 48,
    marginTop: 12,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f7d488',
  },
  netflixInputButtonText: {
    color: '#0f172a',
    fontWeight: '800',
    fontSize: 14,
  },
  netflixWaitingText: {
    color: '#94a3b8',
    marginTop: 8,
    fontSize: 13,
  },
  netflixErrorText: {
    color: '#f87171',
    marginTop: 8,
    fontSize: 13,
    fontWeight: '600',
  },
  tabs: {
    flexDirection: 'row',
    paddingHorizontal: 12,
    marginTop: 10,
    gap: 8,
  },
  tab: {
    flex: 1,
    minHeight: 48,
    minWidth: 48,
    backgroundColor: '#0f172a',
    borderColor: '#1e293b',
    borderWidth: 1,
    borderRadius: 14,
    justifyContent: 'center',
    alignItems: 'center',
  },
  activeTab: {
    backgroundColor: '#1e293b',
    borderColor: '#f7d488',
    shadowColor: '#f7d488',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.2,
    shadowRadius: 6,
  },
  tabText: {
    color: '#94a3b8',
    fontWeight: '700',
    fontSize: 13,
  },
  activeTabText: {
    color: '#f7d488',
  },
  textInputBtn: {
    width: 82,
    minHeight: 48,
    backgroundColor: '#1e293b',
    borderColor: '#334155',
    borderWidth: 1,
    borderRadius: 14,
    justifyContent: 'center',
    alignItems: 'center',
  },
  textInputBtnText: {
    color: '#f8fafc',
    fontWeight: '700',
    fontSize: 13,
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: 36,
  },
})
