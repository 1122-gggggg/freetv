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
import { ControllerSocket, type SocketStatus } from '../api/controllerSocket'
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
  const [socket, setSocket] = useState<ControllerSocket | null>(null)
  const [status, setStatus] = useState<SocketStatus>('connecting')
  const [controllerState, setControllerState] = useState<ControllerState | null>(null)
  const [mode, setMode] = useState<ControlMode>('dpad')
  const [isTextModalVisible, setIsTextModalVisible] = useState(false)

  useEffect(() => {
    const client = new ControllerSocket({
      host: device.host,
      port: device.port,
      token: device.token,
      onStatusChange: (newStatus) => {
        setStatus(newStatus)
      },
      onStateChange: (newState) => {
        setControllerState(newState)
      },
      onAuthenticationFailed: () => {
        Alert.alert('Session Expired', 'The pairing token has expired or was revoked. Please pair again.')
        handleForget()
      },
    })

    client.connect()
    setSocket(client)

    return () => {
      client.disconnect()
    }
  }, [device])

  const handleCommand = (command: Command) => {
    socket?.sendCommand(command).catch(() => {
      // Ignored if acknowledged failure handled by server state
    })
  }

  const handlePointer = (action: PointerAction, dx: number, dy: number) => {
    socket?.sendPointer(action, dx, dy)
  }

  const handleSendText = async (text: string) => {
    if (!socket) return
    await socket.sendTextInput(text)
  }

  const handleForget = async () => {
    await forgetCurrentDevice()
    socket?.disconnect()
    onDisconnect()
  }

  const isConnected = status === 'authenticated'

  return (
    <View style={styles.container}>
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
              {isConnected ? 'Connected' : status === 'connecting' ? 'Reconnecting...' : 'Disconnected'}
            </Text>
          </View>
        </View>

        <TouchableOpacity style={styles.forgetBtn} onPress={handleForget}>
          <Text style={styles.forgetText}>DISCONNECT</Text>
        </TouchableOpacity>
      </View>

      {/* Now Controlling Status Readout */}
      {controllerState && (
        <View style={styles.stateBanner}>
          <View style={styles.stateLeft}>
            <Text style={styles.stateLabel}>NOW CONTROLLING</Text>
            <Text style={styles.stateApp}>{controllerState.active_app.toUpperCase().replace('_', ' ')}</Text>
            {controllerState.channel_name && (
              <Text style={styles.channelText}>
                CH {String(controllerState.channel_number).padStart(2, '0')} · {controllerState.channel_name}
              </Text>
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

      {/* Mode Switcher Tabs */}
      <View style={styles.tabs}>
        <TouchableOpacity
          style={[styles.tab, mode === 'dpad' && styles.activeTab]}
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
            setMode('dpad')
          }}
        >
          <Text style={[styles.tabText, mode === 'dpad' && styles.activeTabText]}>🎮 D-PAD</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.tab, mode === 'touchpad' && styles.activeTab]}
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
            setMode('touchpad')
          }}
        >
          <Text style={[styles.tabText, mode === 'touchpad' && styles.activeTabText]}>🖱 TOUCHPAD</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.textInputBtn}
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
            setIsTextModalVisible(true)
          }}
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
          muted={controllerState?.muted}
          volume={controllerState?.volume}
        />

        <AppLaunchers
          onCommand={handleCommand}
          activeApp={controllerState?.active_app}
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
    paddingTop: 44,
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
    backgroundColor: '#273449',
    borderRadius: 8,
    borderColor: '#3e4d66',
    borderWidth: 1,
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
  tabs: {
    flexDirection: 'row',
    paddingHorizontal: 16,
    marginTop: 10,
    gap: 8,
  },
  tab: {
    flex: 1,
    height: 40,
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
    height: 40,
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
