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
import type { Command, ControllerState, PointerAction } from '../types/protocol'

interface RemoteScreenProps {
  device: SavedDevice
  onDisconnect: () => void
}

type ControlMode = 'dpad' | 'touchpad'

export function RemoteScreen({ device, onDisconnect }: RemoteScreenProps): React.ReactElement {
  const insets = useSafeAreaInsets()
  const [socket, setSocket] = useState<ControllerSocket | null>(null)
  const [status, setStatus] = useState<SocketStatus>('connecting')
  const [hasEverConnected, setHasEverConnected] = useState(false)
  const [controllerState, setControllerState] = useState<ControllerState | null>(null)
  const [mode, setMode] = useState<ControlMode>('dpad')
  const [isTextModalVisible, setIsTextModalVisible] = useState(false)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const [commandError, setCommandError] = useState<string | null>(null)
  const [isUnpairing, setIsUnpairing] = useState(false)

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
        Alert.alert('Session Expired', 'The pairing token has expired or was revoked. Please pair again.')
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

  const handleCommand = async (command: Command) => {
    if (!socket || status !== 'authenticated') {
      setCommandError('TV is not connected')
      return
    }
    try {
      setCommandError(null)
      const ack = await socket.sendCommand(command)
      if (!ack.success) {
        setCommandError(ack.message || ack.error_code || `Command ${command} failed`)
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : `Command ${command} failed`
      setCommandError(message)
    }
  }

  const handlePointer = (action: PointerAction, dx: number, dy: number) => {
    socket?.sendPointer(action, dx, dy)
  }

  const handleSendText = async (text: string) => {
    if (!socket || status !== 'authenticated') {
      throw new Error('TV is not connected')
    }
    const ack = await socket.sendTextInput(text)
    if (!ack.success) {
      throw new Error(ack.message || ack.error_code || 'Failed to send text')
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
          'Still Paired',
          'Could not securely revoke this remote. Keep it paired, reconnect to the TV Box, then try again.',
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

  const handleForgetPress = () => {
    if (isUnpairing) return
    Alert.alert(
      'Forget TV',
      'Are you sure you want to unpair from this TV? You will need to pair again to control it.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Forget',
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
              {connectionError ?? (isConnected ? 'Connected' : status === 'connecting' ? (hasEverConnected ? 'Reconnecting...' : 'Connecting...') : 'Disconnected')}
            </Text>
          </View>
        </View>

        <TouchableOpacity
          style={[styles.forgetBtn, isUnpairing && styles.disabledBtn]}
          onPress={handleForgetPress}
          disabled={isUnpairing}
          accessibilityRole="button"
          accessibilityLabel={`Disconnect and unpair from ${device.name}`}
          accessibilityHint="Revokes this controller's access and returns to TV selection."
          accessibilityState={{ disabled: isUnpairing, busy: isUnpairing }}
        >
          <Text style={styles.forgetText}>{isUnpairing ? 'FORGETTING...' : 'FORGET TV'}</Text>
        </TouchableOpacity>
      </View>

      {/* Now Controlling Status Readout */}
      {isConnected && controllerState && (
        <View style={styles.stateBanner}>
          <View style={styles.stateLeft}>
            <Text style={styles.stateLabel}>NOW CONTROLLING</Text>
            <Text style={styles.stateApp}>{controllerState.active_app.toUpperCase().replace('_', ' ')}</Text>
            {controllerState.channel_name && (
              <Text style={styles.channelText}>
                CH {String(controllerState.channel_number).padStart(2, '0')} · {controllerState.channel_name}
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
            <Text style={styles.volLabel}>VOL</Text>
            <Text style={[styles.volValue, controllerState.muted && styles.mutedValue]}>
              {controllerState.muted ? 'MUTED' : controllerState.volume}
            </Text>
          </View>
        </View>
      )}

      {isConnected && commandError && (
        <View style={styles.errorBanner}>
          <Text style={styles.errorBannerText}>{commandError}</Text>
        </View>
      )}

      {/* Mode Switcher Tabs */}
      <View
        style={styles.tabs}
        accessibilityRole="tablist"
        accessibilityLabel="Remote control mode"
      >
        <TouchableOpacity
          style={[styles.tab, mode === 'dpad' && styles.activeTab]}
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
            setMode('dpad')
          }}
          accessibilityRole="tab"
          accessibilityLabel="D-pad mode"
          accessibilityHint="Shows directional buttons for remote navigation."
          accessibilityState={{ selected: mode === 'dpad' }}
        >
          <Text style={[styles.tabText, mode === 'dpad' && styles.activeTabText]}>🎮 D-PAD</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.tab, mode === 'touchpad' && styles.activeTab]}
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
            setMode('touchpad')
          }}
          accessibilityRole="tab"
          accessibilityLabel="Touchpad mode"
          accessibilityHint="Shows the touchpad for pointer control."
          accessibilityState={{ selected: mode === 'touchpad' }}
        >
          <Text style={[styles.tabText, mode === 'touchpad' && styles.activeTabText]}>🖱 TOUCHPAD</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.textInputBtn, !isConnected && styles.disabledBtn]}
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
            setIsTextModalVisible(true)
          }}
          disabled={!isConnected}
          accessibilityRole="button"
          accessibilityLabel="Type text on TV"
          accessibilityHint="Opens a text field for sending text to the focused TV app."
          accessibilityState={{ disabled: !isConnected }}
        >
          <Text style={styles.textInputBtnText}>⌨ TYPE</Text>
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
        />

        <AppLaunchers
          onCommand={handleCommand}
          activeApp={isConnected ? controllerState?.active_app : undefined}
          disabled={!isConnected}
        />
      </ScrollView>

      {/* Text Input Modal */}
      <TextInputModal
        visible={isTextModalVisible}
        onClose={() => setIsTextModalVisible(false)}
        onSend={handleSendText}
      />
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0c111d',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 18,
    paddingBottom: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  headerInfo: {
    flex: 1,
  },
  deviceName: {
    color: '#f8fafc',
    fontSize: 18,
    fontWeight: '800',
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 3,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  dotConnected: {
    backgroundColor: '#22c55e',
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
    paddingVertical: 6,
    paddingHorizontal: 12,
    minWidth: 48,
    minHeight: 48,
    backgroundColor: '#273449',
    borderRadius: 8,
    borderColor: '#3e4d66',
    borderWidth: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  disabledBtn: {
    opacity: 0.5,
  },
  forgetText: {
    color: '#cbd5e1',
    fontSize: 11,
    fontWeight: '700',
  },
  stateBanner: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    backgroundColor: '#162132',
    marginHorizontal: 16,
    marginTop: 10,
    padding: 12,
    borderRadius: 14,
    borderColor: '#2b3a50',
    borderWidth: 1,
  },
  stateLeft: {
    flex: 1,
  },
  stateLabel: {
    color: '#8da0b8',
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 1,
  },
  stateApp: {
    color: '#f7d488',
    fontSize: 16,
    fontWeight: '800',
    marginTop: 2,
  },
  channelText: {
    color: '#cbd5e1',
    fontSize: 12,
    marginTop: 2,
  },
  stateRight: {
    alignItems: 'flex-end',
    justifyContent: 'center',
  },
  volLabel: {
    color: '#8da0b8',
    fontSize: 10,
    fontWeight: '800',
  },
  volValue: {
    color: '#f8fafc',
    fontSize: 16,
    fontWeight: '800',
  },
  mutedValue: {
    color: '#ff8a8a',
  },
  serverStatusText: {
    color: '#93c5fd',
    fontSize: 12,
    marginTop: 2,
  },
  serverErrorText: {
    color: '#fca5a5',
    fontSize: 12,
    marginTop: 2,
  },
  errorBanner: {
    backgroundColor: '#3b1219',
    borderColor: '#7f1d1d',
    borderWidth: 1,
    borderRadius: 10,
    marginHorizontal: 16,
    marginTop: 8,
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  errorBannerText: {
    color: '#fca5a5',
    fontSize: 12,
    fontWeight: '600',
  },
  tabs: {
    flexDirection: 'row',
    paddingHorizontal: 16,
    marginTop: 10,
    gap: 8,
  },
  tab: {
    flex: 1,
    minHeight: 48,
    minWidth: 48,
    backgroundColor: '#161f2e',
    borderColor: '#2b384c',
    borderWidth: 1,
    borderRadius: 10,
    justifyContent: 'center',
    alignItems: 'center',
  },
  activeTab: {
    backgroundColor: '#27384f',
    borderColor: '#f7d488',
  },
  tabText: {
    color: '#94a3b8',
    fontWeight: '700',
    fontSize: 12,
  },
  activeTabText: {
    color: '#f7d488',
  },
  textInputBtn: {
    width: 80,
    minHeight: 48,
    backgroundColor: '#202a3a',
    borderColor: '#38465d',
    borderWidth: 1,
    borderRadius: 10,
    justifyContent: 'center',
    alignItems: 'center',
  },
  textInputBtnText: {
    color: '#f8fafc',
    fontWeight: '700',
    fontSize: 12,
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: 30,
  },
})
