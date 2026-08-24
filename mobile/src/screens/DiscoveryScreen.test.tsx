import React from 'react'
import { Alert, FlatList, Modal, TextInput, TouchableOpacity } from 'react-native'
import ReactTestRenderer, { act } from 'react-test-renderer'
import { DiscoveryScreen } from './DiscoveryScreen'
import * as Haptics from 'expo-haptics'
import { pairWithDevice } from '../discovery/deviceScanner'
import { getSavedDevices, saveCurrentDevice, type SavedDevice } from '../storage/tokenStorage'

let mockCameraPermissionGranted = true
const mockRequestPermission = jest.fn().mockImplementation(async () => ({
  granted: mockCameraPermissionGranted,
}))

jest.mock('expo-camera', () => {
  const ReactModule = require('react')
  const { View } = require('react-native')
  return {
    CameraView: (props: unknown) =>
      ReactModule.createElement(View, { testID: 'mock-camera-view', ...(props as object) }),
    useCameraPermissions: () => [{ granted: mockCameraPermissionGranted }, mockRequestPermission],
  }
})

jest.mock('expo-haptics', () => ({
  notificationAsync: jest.fn().mockResolvedValue(undefined),
  impactAsync: jest.fn().mockResolvedValue(undefined),
  NotificationFeedbackType: {
    Success: 'success',
    Warning: 'warning',
    Error: 'error',
  },
  ImpactFeedbackStyle: {
    Light: 'light',
    Medium: 'medium',
    Heavy: 'heavy',
  },
}))

jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 20, bottom: 20, left: 0, right: 0 }),
}))

jest.mock('../storage/tokenStorage', () => ({
  getSavedDevices: jest.fn().mockResolvedValue([]),
  saveCurrentDevice: jest.fn().mockResolvedValue(undefined),
}))

jest.mock('../discovery/deviceScanner', () => ({
  pairWithDevice: jest.fn(),
}))

const mockPairWithDevice = pairWithDevice as jest.MockedFunction<typeof pairWithDevice>
const mockGetSavedDevices = getSavedDevices as jest.MockedFunction<typeof getSavedDevices>
const mockSaveCurrentDevice = saveCurrentDevice as jest.MockedFunction<typeof saveCurrentDevice>

function getHostInput(root: ReactTestRenderer.ReactTestInstance): ReactTestRenderer.ReactTestInstance {
  return root.findByProps({ placeholder: 'IP 位址（例如 172.20.10.8）' })
}

function getPortInput(root: ReactTestRenderer.ReactTestInstance): ReactTestRenderer.ReactTestInstance {
  return root.findByProps({ placeholder: '連接埠' })
}

function getManualPairButton(root: ReactTestRenderer.ReactTestInstance): ReactTestRenderer.ReactTestInstance {
  const touchables = root.findAllByType(TouchableOpacity)
  const btn = touchables.find((t) =>
    t.findAll((child) => child.props?.children === '配對').length > 0,
  )
  if (!btn) throw new Error('Manual PAIR button not found')
  return btn
}

function getPairModal(root: ReactTestRenderer.ReactTestInstance): ReactTestRenderer.ReactTestInstance {
  const modals = root.findAllByType(Modal)
  const modal = modals.find((m) => m.props.transparent === true)
  if (!modal) throw new Error('Pair modal not found')
  return modal
}

function getScannerModal(root: ReactTestRenderer.ReactTestInstance): ReactTestRenderer.ReactTestInstance {
  const modals = root.findAllByType(Modal)
  const modal = modals.find((m) => m.props.transparent !== true)
  if (!modal) throw new Error('Scanner modal not found')
  return modal
}

function getCodeInput(root: ReactTestRenderer.ReactTestInstance): ReactTestRenderer.ReactTestInstance | undefined {
  const inputs = root.findAllByType(TextInput)
  return inputs.find((i) => i.props.placeholder === '000000')
}

function getConfirmPairButton(root: ReactTestRenderer.ReactTestInstance): ReactTestRenderer.ReactTestInstance | undefined {
  const touchables = root.findAllByType(TouchableOpacity)
  return touchables.find((t) =>
    t.findAll((c) => c.props?.children === '確認' || c.props?.children === '配對中…').length > 0,
  )
}

function getCancelPairButton(root: ReactTestRenderer.ReactTestInstance): ReactTestRenderer.ReactTestInstance | undefined {
  const touchables = root.findAllByType(TouchableOpacity)
  return touchables.find((t) =>
    t.findAll((c) => c.props?.children === '取消').length > 0,
  )
}

function getQRScanButton(root: ReactTestRenderer.ReactTestInstance): ReactTestRenderer.ReactTestInstance {
  const touchables = root.findAllByType(TouchableOpacity)
  const btn = touchables.find((t) =>
    t.findAll((c) => c.props?.children === '掃描電視 QR 碼').length > 0,
  )
  if (!btn) throw new Error('QR Scan button not found')
  return btn
}

describe('DiscoveryScreen', () => {
  let alertSpy: jest.SpyInstance
  let activeRenderers: ReactTestRenderer.ReactTestRenderer[] = []
  const mockOnDeviceConnected = jest.fn()

  async function renderDiscoveryScreen(
    props: Partial<React.ComponentProps<typeof DiscoveryScreen>> = {},
  ): Promise<ReactTestRenderer.ReactTestRenderer> {
    let renderer!: ReactTestRenderer.ReactTestRenderer
    await act(async () => {
      renderer = ReactTestRenderer.create(
        <DiscoveryScreen onDeviceConnected={mockOnDeviceConnected} {...props} />,
      )
    })
    await act(async () => {
      await Promise.resolve()
    })
    activeRenderers.push(renderer)
    return renderer
  }

  beforeEach(() => {
    jest.clearAllMocks()
    jest.useFakeTimers()
    mockCameraPermissionGranted = true
    activeRenderers = []
    alertSpy = jest.spyOn(Alert, 'alert').mockImplementation(() => {})
    mockGetSavedDevices.mockResolvedValue([])
    mockSaveCurrentDevice.mockResolvedValue(undefined)
  })

  afterEach(() => {
    for (const renderer of activeRenderers) {
      try {
        act(() => {
          renderer.unmount()
        })
      } catch {
        // already unmounted
      }
    }
    activeRenderers = []

    act(() => {
      try {
        jest.runOnlyPendingTimers()
      } catch {
        // ignore if no pending timers
      }
      jest.clearAllTimers()
    })
    jest.useRealTimers()
    alertSpy.mockRestore()
  })

  it('renders saved devices and invokes callback on selection', async () => {
    const saved: SavedDevice[] = [
      {
        id: '192.168.1.100:8765',
        name: 'Living Room TV',
        host: '192.168.1.100',
        port: 8765,
        token: 'saved-token',
        lastConnected: 1700000000000,
      },
    ]
    mockGetSavedDevices.mockResolvedValueOnce(saved)

    const renderer = await renderDiscoveryScreen()

    const root = renderer.root
    const flatList = root.findByType(FlatList)
    expect(flatList.props.data).toEqual(saved)

    const deviceCards = root.findAllByType(TouchableOpacity).filter((t) =>
      t.findAll((c) => c.props?.children === 'Living Room TV').length > 0,
    )
    expect(deviceCards.length).toBe(1)

    act(() => {
      deviceCards[0].props.onPress()
    })
    expect(mockOnDeviceConnected).toHaveBeenCalledWith(saved[0])
  })

  it('rejects malformed manual endpoint before showing code modal', async () => {
    const renderer = await renderDiscoveryScreen()

    const root = renderer.root
    const hostInput = getHostInput(root)
    const pairBtn = getManualPairButton(root)

    // 1. Invalid non-IP hostname
    act(() => {
      hostInput.props.onChangeText('invalid-host')
    })
    act(() => {
      pairBtn.props.onPress()
    })

    expect(alertSpy).toHaveBeenCalledWith('端點無效', expect.any(String))
    expect(getPairModal(root).props.visible).toBe(false)
    expect(mockPairWithDevice).not.toHaveBeenCalled()

    alertSpy.mockClear()

    // 2. Out-of-bounds IPv4 octet
    act(() => {
      hostInput.props.onChangeText('192.168.1.300')
    })
    act(() => {
      pairBtn.props.onPress()
    })

    expect(alertSpy).toHaveBeenCalledWith('端點無效', expect.any(String))
    expect(getPairModal(root).props.visible).toBe(false)

    alertSpy.mockClear()

    // 3. Invalid port
    const portInput = getPortInput(root)
    act(() => {
      hostInput.props.onChangeText('192.168.1.50')
      portInput.props.onChangeText('999999')
    })
    act(() => {
      pairBtn.props.onPress()
    })

    expect(alertSpy).toHaveBeenCalledWith('端點無效', expect.any(String))
    expect(getPairModal(root).props.visible).toBe(false)
  })

  it('opens code modal on valid endpoint and sanitizes pairing code input', async () => {
    const renderer = await renderDiscoveryScreen()

    const root = renderer.root
    act(() => {
      getHostInput(root).props.onChangeText('192.168.1.50')
      getPortInput(root).props.onChangeText('8765')
    })
    act(() => {
      getManualPairButton(root).props.onPress()
    })

    expect(getPairModal(root).props.visible).toBe(true)

    const codeInput = getCodeInput(root)
    expect(codeInput).toBeDefined()

    // Entering alphanumeric string should sanitize to digits only and enforce length <= 6
    act(() => {
      codeInput!.props.onChangeText('abc12#345678')
    })

    const confirmBtn = getConfirmPairButton(root)
    expect(confirmBtn).toBeDefined()
    expect(confirmBtn!.props.disabled).toBe(false)
  })

  it('prevents repeat pairing submit while pairing is in flight and handles success', async () => {
    const { promise: pairingPromise, resolve: resolvePairingPromise } =
      Promise.withResolvers<{ token: string }>()
    mockPairWithDevice.mockReturnValue(pairingPromise)

    const renderer = await renderDiscoveryScreen()

    const root = renderer.root
    act(() => {
      getHostInput(root).props.onChangeText('192.168.1.50')
      getPortInput(root).props.onChangeText('8765')
    })
    act(() => {
      getManualPairButton(root).props.onPress()
    })

    const codeInput = getCodeInput(root)!
    act(() => {
      codeInput.props.onChangeText('123456')
    })

    const confirmBtn = getConfirmPairButton(root)!
    // First submit
    act(() => {
      confirmBtn.props.onPress()
    })

    expect(mockPairWithDevice).toHaveBeenCalledTimes(1)
    expect(mockPairWithDevice).toHaveBeenCalledWith('192.168.1.50', 8765, '123456')

    // Confirm button should indicate in-flight state and be disabled
    expect(confirmBtn.props.disabled).toBe(true)
    const cancelBtn = getCancelPairButton(root)!
    expect(cancelBtn.props.disabled).toBe(true)

    // Repeat submit while in flight must be ignored
    act(() => {
      confirmBtn.props.onPress()
    })
    expect(mockPairWithDevice).toHaveBeenCalledTimes(1)

    // Resolve the pairing request
    await act(async () => {
      resolvePairingPromise!({ token: 'paired-jwt-token' })
    })

    expect(mockSaveCurrentDevice).toHaveBeenCalledWith({
      id: '192.168.1.50:8765',
      name: '電腦電視盒 (192.168.1.50)',
      host: '192.168.1.50',
      port: 8765,
      token: 'paired-jwt-token',
      lastConnected: expect.any(Number),
    })
    expect(Haptics.notificationAsync).toHaveBeenCalledWith(
      Haptics.NotificationFeedbackType.Success,
    )
    expect(mockOnDeviceConnected).toHaveBeenCalledWith(
      expect.objectContaining({
        host: '192.168.1.50',
        port: 8765,
        token: 'paired-jwt-token',
      }),
    )
    expect(getPairModal(root).props.visible).toBe(false)
  })

  it('surfaces alert on pairing failure and allows retrying', async () => {
    mockPairWithDevice.mockResolvedValueOnce({ error: 'Incorrect pairing code entered.' })

    const renderer = await renderDiscoveryScreen()

    const root = renderer.root
    act(() => {
      getHostInput(root).props.onChangeText('192.168.1.50')
      getPortInput(root).props.onChangeText('8765')
    })
    act(() => {
      getManualPairButton(root).props.onPress()
    })

    const codeInput = getCodeInput(root)!
    act(() => {
      codeInput.props.onChangeText('654321')
    })

    await act(async () => {
      getConfirmPairButton(root)!.props.onPress()
    })

    expect(alertSpy).toHaveBeenCalledWith('配對失敗', 'Incorrect pairing code entered.')
    expect(mockSaveCurrentDevice).not.toHaveBeenCalled()
    expect(mockOnDeviceConnected).not.toHaveBeenCalled()

    // Can cancel modal cleanly
    const cancelBtn = getCancelPairButton(root)!
    act(() => {
      cancelBtn.props.onPress()
    })
    expect(getPairModal(root).props.visible).toBe(false)
  })

  it('handles pairing exceptions gracefully', async () => {
    mockPairWithDevice.mockRejectedValueOnce(new Error('Secure storage unavailable'))

    const renderer = await renderDiscoveryScreen()

    const root = renderer.root
    act(() => {
      getHostInput(root).props.onChangeText('192.168.1.50')
      getPortInput(root).props.onChangeText('8765')
    })
    act(() => {
      getManualPairButton(root).props.onPress()
    })

    const codeInput = getCodeInput(root)!
    act(() => {
      codeInput.props.onChangeText('112233')
    })

    await act(async () => {
      getConfirmPairButton(root)!.props.onPress()
    })

    expect(alertSpy).toHaveBeenCalledWith('配對失敗', 'Secure storage unavailable')
  })

  it('opens camera scanner and handles full QR code payload', async () => {
    mockPairWithDevice.mockResolvedValueOnce({ token: 'qr-token' })

    const renderer = await renderDiscoveryScreen()

    const root = renderer.root
    const qrBtn = getQRScanButton(root)

    await act(async () => {
      qrBtn.props.onPress()
    })

    expect(getScannerModal(root).props.visible).toBe(true)

    const cameraView = root.findByProps({ testID: 'mock-camera-view' })
    await act(async () => {
      cameraView.props.onBarcodeScanned({
        data: 'pctv://pair?host=192.168.1.60&port=8765&code=998877',
      })
    })

    expect(mockPairWithDevice).toHaveBeenCalledWith('192.168.1.60', 8765, '998877')
    expect(mockOnDeviceConnected).toHaveBeenCalled()
  })


  it('uses the entered port for a code-only QR pairing', async () => {
    mockPairWithDevice.mockResolvedValueOnce({ token: 'qr-token' })
    const renderer = await renderDiscoveryScreen()
    const root = renderer.root

    act(() => {
      getHostInput(root).props.onChangeText('192.168.1.60')
      getPortInput(root).props.onChangeText('9000')
    })
    await act(async () => {
      getQRScanButton(root).props.onPress()
    })
    await act(async () => {
      root.findByProps({ testID: 'mock-camera-view' }).props.onBarcodeScanned({ data: '998877' })
    })

    expect(mockPairWithDevice).toHaveBeenCalledWith('192.168.1.60', 9000, '998877')
  })
  it('shows alert when scanned QR code is invalid or missing host', async () => {
    const renderer = await renderDiscoveryScreen()

    const root = renderer.root
    await act(async () => {
      getQRScanButton(root).props.onPress()
    })

    const cameraView = root.findByProps({ testID: 'mock-camera-view' })

    // Invalid QR code text
    await act(async () => {
      cameraView.props.onBarcodeScanned({ data: 'invalid-qr-text' })
    })
    expect(alertSpy).toHaveBeenCalledWith('QR 碼無效', expect.any(String))

    alertSpy.mockClear()

    // Code-only QR code without manual host entered
    await act(async () => {
      cameraView.props.onBarcodeScanned({ data: '123456' })
    })
    expect(alertSpy).toHaveBeenCalledWith('需要控制器位址', expect.any(String))
  })
})
