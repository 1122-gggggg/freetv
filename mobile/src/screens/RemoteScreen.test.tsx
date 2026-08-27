import React from 'react'
import { Alert, Text, TouchableOpacity, View } from 'react-native'
import ReactTestRenderer, { act } from 'react-test-renderer'
import { RemoteScreen } from './RemoteScreen'
import { ControllerSocket, type SocketOptions, type SocketStatus } from '../api/controllerSocket'
import { revokeDeviceToken } from '../discovery/deviceScanner'
import { forgetCurrentDevice, type SavedDevice } from '../storage/tokenStorage'
import type { Acknowledgement, Command, ControllerState } from '../types/protocol'
import { Dpad } from '../components/Dpad'
import { MediaControls } from '../components/MediaControls'
import { AppLaunchers } from '../components/AppLaunchers'
import { Trackpad } from '../components/Trackpad'
import { TextInputModal } from '../components/TextInputModal'

interface MockSocket {
  options: SocketOptions
  connect: jest.Mock
  disconnect: jest.Mock
  sendCommand: jest.Mock<Promise<Acknowledgement>, [Command]>
  sendTextInput: jest.Mock<Promise<Acknowledgement>, [string]>
  sendPointer: jest.Mock<void, [string, number, number]>
  simulateStatusChange: (status: SocketStatus) => void
  simulateStateChange: (state: ControllerState) => void
  simulateAuthFailed: () => void
  simulateError: (error: Error) => void
}

let latestMockSocket: MockSocket | null = null
function mockAck(overrides: Partial<Acknowledgement> = {}): Acknowledgement {
  return {
    version: 1,
    type: 'ack',
    request_id: 'req-test-1',
    success: true,
    error_code: null,
    message: null,
    ...overrides,
  }
}

jest.mock('../api/controllerSocket', () => {
  return {
    ControllerSocket: jest.fn().mockImplementation((options: SocketOptions) => {
      const socket: MockSocket = {
        options,
        connect: jest.fn(),
        disconnect: jest.fn(),
        sendCommand: jest.fn().mockImplementation(() => Promise.resolve(mockAck())),
        sendTextInput: jest.fn().mockImplementation(() => Promise.resolve(mockAck())),
        sendPointer: jest.fn(),
        simulateStatusChange: (status: SocketStatus) => {
          options.onStatusChange?.(status)
        },
        simulateStateChange: (state: ControllerState) => {
          options.onStateChange?.(state)
        },
        simulateAuthFailed: () => {
          void options.onAuthenticationFailed?.()
        },
        simulateError: (error: Error) => {
          options.onError?.(error)
        },
      }
      latestMockSocket = socket
      return socket
    }),
  }
})

jest.mock('expo-haptics', () => ({
  impactAsync: jest.fn().mockResolvedValue(undefined),
  notificationAsync: jest.fn().mockResolvedValue(undefined),
  ImpactFeedbackStyle: {
    Light: 'light',
    Medium: 'medium',
    Heavy: 'heavy',
  },
  NotificationFeedbackType: {
    Success: 'success',
    Warning: 'warning',
    Error: 'error',
  },
}))

jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 10, bottom: 10, left: 0, right: 0 }),
}))

jest.mock('../discovery/deviceScanner', () => ({
  revokeDeviceToken: jest.fn().mockResolvedValue(undefined),
}))

jest.mock('../storage/tokenStorage', () => ({
  forgetCurrentDevice: jest.fn().mockResolvedValue(undefined),
}))

const mockRevokeDeviceToken = revokeDeviceToken as jest.MockedFunction<typeof revokeDeviceToken>
const mockForgetCurrentDevice = forgetCurrentDevice as jest.MockedFunction<typeof forgetCurrentDevice>

const mockDevice: SavedDevice = {
  id: '192.168.1.100:8765',
  name: 'Living Room TV',
  host: '192.168.1.100',
  port: 8765,
  token: 'auth-token-xyz',
  lastConnected: 1700000000000,
}

function findTextNodes(root: ReactTestRenderer.ReactTestInstance, text: string): ReactTestRenderer.ReactTestInstance[] {
  return root.findAllByType(Text).filter((node) => {
    const children = node.props?.children
    if (typeof children === 'string' || typeof children === 'number') {
      const s = String(children)
      return s === text || s.trim() === text
    }
    if (Array.isArray(children)) {
      const flattened = children
        .map((c) => (typeof c === 'string' || typeof c === 'number' ? String(c) : ''))
        .join('')
      return (
        flattened === text ||
        flattened.trim() === text ||
        flattened.replace(/\s+/g, ' ').trim() === text
      )
    }
    return false
  })
}

function getForgetTextButton(root: ReactTestRenderer.ReactTestInstance): ReactTestRenderer.ReactTestInstance {
  const touchables = root.findAllByType(TouchableOpacity)
  const btn = touchables.find((t) =>
    findTextNodes(t, '解除配對').length > 0 || findTextNodes(t, '解除中…').length > 0,
  )
  if (!btn) throw new Error('Forget TV button not found')
  return btn
}

function getTypeButton(root: ReactTestRenderer.ReactTestInstance): ReactTestRenderer.ReactTestInstance {
  const touchables = root.findAllByType(TouchableOpacity)
  const btn = touchables.find((t) =>
    findTextNodes(t, '⌨ 輸入').length > 0,
  )
  if (!btn) throw new Error('Type button not found')
  return btn
}

function getTouchpadTab(root: ReactTestRenderer.ReactTestInstance): ReactTestRenderer.ReactTestInstance {
  const touchables = root.findAllByType(TouchableOpacity)
  const btn = touchables.find((t) =>
    findTextNodes(t, '🖱 觸控板').length > 0,
  )
  if (!btn) throw new Error('Touchpad tab not found')
  return btn
}

function getDpadTab(root: ReactTestRenderer.ReactTestInstance): ReactTestRenderer.ReactTestInstance {
  const touchables = root.findAllByType(TouchableOpacity)
  const btn = touchables.find((t) =>
    findTextNodes(t, '🎮 方向鍵').length > 0,
  )
  if (!btn) throw new Error('Dpad tab not found')
  return btn
}

describe('RemoteScreen', () => {
  let alertSpy: jest.SpyInstance
  let renderer: ReactTestRenderer.ReactTestRenderer | null = null
  const mockOnDisconnect = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
    jest.useFakeTimers()
    latestMockSocket = null
    renderer = null
    alertSpy = jest.spyOn(Alert, 'alert').mockImplementation(() => {})
    mockRevokeDeviceToken.mockResolvedValue(undefined)
    mockForgetCurrentDevice.mockResolvedValue(undefined)
  })

  afterEach(() => {
    if (renderer) {
      act(() => {
        try {
          renderer?.unmount()
        } catch {
          // ignore already unmounted
        }
      })
      renderer = null
    }
    act(() => {
      jest.runOnlyPendingTimers()
    })
    jest.clearAllTimers()
    jest.useRealTimers()
    alertSpy.mockRestore()
    latestMockSocket = null
  })
  it('disables controls while unauthenticated and enables when authenticated', async () => {

    await act(async () => {
      renderer = ReactTestRenderer.create(
        <RemoteScreen device={mockDevice} onDisconnect={mockOnDisconnect} />,
      )
    })

    const root = renderer!.root
    expect(latestMockSocket).not.toBeNull()
    expect(latestMockSocket!.connect).toHaveBeenCalledTimes(1)

    // Initially in connecting state -> controls disabled
    const dpad = root.findByType(Dpad)
    expect(dpad.props.disabled).toBe(true)

    const mediaControls = root.findByType(MediaControls)
    expect(mediaControls.props.disabled).toBe(true)

    const appLaunchers = root.findByType(AppLaunchers)
    expect(appLaunchers.props.disabled).toBe(true)

    const typeBtn = getTypeButton(root)
    expect(typeBtn.props.disabled).toBe(true)

    // Switch to touchpad mode while unauthenticated
    act(() => {
      getTouchpadTab(root).props.onPress()
    })
    const trackpad = root.findByType(Trackpad)
    expect(trackpad.props.disabled).toBe(true)

    // Transition to disconnected
    act(() => {
      latestMockSocket!.simulateStatusChange('disconnected')
    })
    expect(root.findByType(Trackpad).props.disabled).toBe(true)

    // Transition to authenticated
    act(() => {
      latestMockSocket!.simulateStatusChange('authenticated')
    })
    expect(root.findByType(Trackpad).props.disabled).toBe(false)

    // Switch back to D-pad
    act(() => {
      getDpadTab(root).props.onPress()
    })
    expect(root.findByType(Dpad).props.disabled).toBe(false)
    expect(root.findByType(MediaControls).props.disabled).toBe(false)
    expect(root.findByType(AppLaunchers).props.disabled).toBe(false)
    expect(getTypeButton(root).props.disabled).toBe(false)
  })

  it('sends existing Netflix D-pad media and 256-character text commands', async () => {
    await act(async () => {
      renderer = ReactTestRenderer.create(
        <RemoteScreen device={mockDevice} onDisconnect={mockOnDisconnect} />,
      )
    })
    const root = renderer!.root
    act(() => {
      latestMockSocket!.simulateStatusChange('authenticated')
    })

    const dpad = root.findByType(Dpad)
    for (const command of ['NAV_UP', 'NAV_DOWN', 'NAV_LEFT', 'NAV_RIGHT', 'OK'] as const) {
      await act(async () => {
        await dpad.props.onCommand(command)
      })
    }
    const media = root.findByType(MediaControls)
    for (const command of ['BACK', 'PLAY_PAUSE'] as const) {
      await act(async () => {
        await media.props.onCommand(command)
      })
    }
    act(() => {
      getTypeButton(root).props.onPress()
    })
    const text = 'x'.repeat(256)
    await expect(root.findByType(TextInputModal).props.onSend(text)).resolves.toBeUndefined()

    expect(latestMockSocket!.sendCommand.mock.calls.map(([command]) => command)).toEqual([
      'NAV_UP',
      'NAV_DOWN',
      'NAV_LEFT',
      'NAV_RIGHT',
      'OK',
      'BACK',
      'PLAY_PAUSE',
    ])
    expect(latestMockSocket!.sendTextInput).toHaveBeenCalledWith(text)
  })

  it('surfaces failed command ACK in error banner and clears on success', async () => {

    await act(async () => {
      renderer = ReactTestRenderer.create(
        <RemoteScreen device={mockDevice} onDisconnect={mockOnDisconnect} />,
      )
    })

    const root = renderer!.root
    act(() => {
      latestMockSocket!.simulateStatusChange('authenticated')
    })

    const dpad = root.findByType(Dpad)

    // 1. Failed command with custom error message
    latestMockSocket!.sendCommand.mockResolvedValueOnce(
      mockAck({
        success: false,
        message: 'Active player is busy',
      }),
    )
    await act(async () => {
      await dpad.props.onCommand('up')
    })

    let errorBannerTexts = findTextNodes(root, 'Active player is busy')
    expect(errorBannerTexts.length).toBe(1)
    // 2. Failed command with error_code fallback
    latestMockSocket!.sendCommand.mockResolvedValueOnce(
      mockAck({
        success: false,
        error_code: 'ERR_NOT_SUPPORTED',
      }),
    )
    await act(async () => {
      await dpad.props.onCommand('down')
    })

    errorBannerTexts = findTextNodes(root, 'ERR_NOT_SUPPORTED')
    expect(errorBannerTexts.length).toBe(1)
    // 3. Command throws an exception
    latestMockSocket!.sendCommand.mockRejectedValueOnce(new Error('Socket transport write timeout'))
    await act(async () => {
      await dpad.props.onCommand('select')
    })

    errorBannerTexts = findTextNodes(root, 'Socket transport write timeout')
    expect(errorBannerTexts.length).toBe(1)
    // 4. Successful command clears error banner
    latestMockSocket!.sendCommand.mockResolvedValueOnce(mockAck())
    await act(async () => {
      await dpad.props.onCommand('left')
    })

    const remainingErrorTexts = root.findAllByType(Text).filter((n) => {
      const c = n.props?.children
      if (typeof c === 'string') {
        return (
          c.includes('busy') ||
          c.includes('ERR_NOT_SUPPORTED') ||
          c.includes('timeout')
        )
      }
      return false
    })
    expect(remainingErrorTexts.length).toBe(0)
  })

  it('surfaces failed text input ACK through TextInputModal handler', async () => {
    await act(async () => {
      renderer = ReactTestRenderer.create(
        <RemoteScreen device={mockDevice} onDisconnect={mockOnDisconnect} />,
      )
    })

    const root = renderer!.root
    act(() => {
      latestMockSocket!.simulateStatusChange('authenticated')
    })

    act(() => {
      getTypeButton(root).props.onPress()
    })

    const textModal = root.findByType(TextInputModal)
    expect(textModal.props.visible).toBe(true)

    // Failed text ACK
    latestMockSocket!.sendTextInput.mockResolvedValueOnce(
      mockAck({
        success: false,
        message: 'Target input field not focused',
      }),
    )

    await expect(textModal.props.onSend('Hello TV')).rejects.toThrow('Target input field not focused')

    // Successful text ACK
    latestMockSocket!.sendTextInput.mockResolvedValueOnce(mockAck())
    await expect(textModal.props.onSend('Valid query')).resolves.toBeUndefined()
  })

  it('confirms destructive unpair dialog, revokes token, forgets device, and disconnects', async () => {

    await act(async () => {
      renderer = ReactTestRenderer.create(
        <RemoteScreen device={mockDevice} onDisconnect={mockOnDisconnect} />,
      )
    })

    const root = renderer!.root
    const forgetBtn = getForgetTextButton(root)

    act(() => {
      forgetBtn.props.onPress()
    })

    expect(alertSpy).toHaveBeenCalledWith(
      '解除配對',
      expect.stringContaining('確定要解除與此電視的配對'),
      expect.any(Array),
    )

    const alertButtons = alertSpy.mock.calls[0][2] as Array<{
      text: string
      style?: string
      onPress?: () => void
    }>
    const cancelBtn = alertButtons.find((b) => b.style === 'cancel' || b.text === '取消')
    const destructiveBtn = alertButtons.find((b) => b.style === 'destructive' || b.text === '解除配對')

    expect(cancelBtn).toBeDefined()
    expect(destructiveBtn).toBeDefined()

    // Canceling should not revoke or forget
    cancelBtn?.onPress?.()
    expect(mockRevokeDeviceToken).not.toHaveBeenCalled()
    expect(mockForgetCurrentDevice).not.toHaveBeenCalled()
    expect(mockOnDisconnect).not.toHaveBeenCalled()

    // Confirming destructive unpair
    await act(async () => {
      destructiveBtn?.onPress?.()
    })

    expect(mockRevokeDeviceToken).toHaveBeenCalledWith(
      mockDevice.host,
      mockDevice.port,
      mockDevice.token,
    )
    expect(mockForgetCurrentDevice).toHaveBeenCalled()
    expect(latestMockSocket!.disconnect).toHaveBeenCalled()
    expect(mockOnDisconnect).toHaveBeenCalled()
  })

  it('preserves pairing and shows alert when remote token revocation fails', async () => {
    mockRevokeDeviceToken.mockRejectedValueOnce(new Error('Network offline'))


    await act(async () => {
      renderer = ReactTestRenderer.create(
        <RemoteScreen device={mockDevice} onDisconnect={mockOnDisconnect} />,
      )
    })

    const root = renderer!.root
    act(() => {
      getForgetTextButton(root).props.onPress()
    })

    const alertButtons = alertSpy.mock.calls[0][2] as Array<{
      text: string
      style?: string
      onPress?: () => void
    }>
    const destructiveBtn = alertButtons.find((b) => b.style === 'destructive' || b.text === '解除配對')

    alertSpy.mockClear()
    await act(async () => {
      destructiveBtn?.onPress?.()
    })

    expect(alertSpy).toHaveBeenCalledWith('仍保持配對', expect.any(String))
    expect(mockForgetCurrentDevice).not.toHaveBeenCalled()
    expect(mockOnDisconnect).not.toHaveBeenCalled()
  })

  it('displays live state when authenticated and clears stale presentation on disconnect', async () => {

    await act(async () => {
      renderer = ReactTestRenderer.create(
        <RemoteScreen device={mockDevice} onDisconnect={mockOnDisconnect} />,
      )
    })

    const root = renderer!.root
    act(() => {
      latestMockSocket!.simulateStatusChange('authenticated')
    })

    const liveState: ControllerState = {
      version: 1,
      type: 'state',
      active_app: 'youtube',
      focused_tile: 'youtube',
      volume: 60,
      muted: false,
      channel_number: 7,
      channel_name: 'Documentary HD',
      status_message: 'Playing video stream',
      error_message: null,
      netflix_context: null,
    }

    act(() => {
      latestMockSocket!.simulateStateChange(liveState)
    })

    const stateBanner = root.findAllByType(View).find((node) => node.props?.style?.backgroundColor === '#162132')
    expect(stateBanner).toBeDefined()
    expect(findTextNodes(stateBanner!, '目前控制').length).toBe(1)
    expect(findTextNodes(stateBanner!, 'YouTube').length).toBe(1)
    expect(findTextNodes(stateBanner!, '頻道 07 · Documentary HD').length).toBe(1)
    expect(findTextNodes(stateBanner!, 'Playing video stream').length).toBe(1)

    // When connection drops to disconnected, live state readout must be cleared immediately
    act(() => {
      latestMockSocket!.simulateStatusChange('disconnected')
    })

    expect(findTextNodes(root, '目前控制').length).toBe(0)
    expect(root.findAllByType(View).some((node) => node.props?.style?.backgroundColor === '#162132')).toBe(false)
  })

  it('handles authentication failure by showing alert, clearing storage, and triggering disconnect', async () => {

    await act(async () => {
      renderer = ReactTestRenderer.create(
        <RemoteScreen device={mockDevice} onDisconnect={mockOnDisconnect} />,
      )
    })

    await act(async () => {
      latestMockSocket!.simulateAuthFailed()
    })

    expect(alertSpy).toHaveBeenCalledWith('連線已過期', expect.any(String))
    expect(mockForgetCurrentDevice).toHaveBeenCalled()
    expect(latestMockSocket!.disconnect).toHaveBeenCalled()
    expect(mockOnDisconnect).toHaveBeenCalled()
  })

  it('cleans up socket connection upon unmount', async () => {
    await act(async () => {
      renderer = ReactTestRenderer.create(
        <RemoteScreen device={mockDevice} onDisconnect={mockOnDisconnect} />,
      )
    })

    const socketInstance = latestMockSocket!
    act(() => {
      renderer!.unmount()
      renderer = null
    })
    expect(socketInstance.disconnect).toHaveBeenCalled()
  })
})
