jest.mock('@react-native-async-storage/async-storage', () => ({
  __esModule: true,
  default: {
    getItem: jest.fn(),
    setItem: jest.fn(),
    removeItem: jest.fn(),
  },
}))
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'WHEN_UNLOCKED_THIS_DEVICE_ONLY',
}))

import AsyncStorage from '@react-native-async-storage/async-storage'
import * as SecureStore from 'expo-secure-store'

import { forgetCurrentDevice, getCurrentDevice, saveCurrentDevice } from './tokenStorage'

const mockAsyncStorage = AsyncStorage as jest.Mocked<typeof AsyncStorage>
const mockSecureStore = SecureStore as jest.Mocked<typeof SecureStore>

const pairedDevice = {
  id: '192.168.1.42:8765',
  name: 'PC TV (192.168.1.42)',
  host: '192.168.1.42',
  port: 8765,
  token: 'opaque-pairing-token',
  lastConnected: 1_700_000_000_000,
}

describe('tokenStorage', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockAsyncStorage.getItem.mockResolvedValue(null)
    mockAsyncStorage.setItem.mockResolvedValue(undefined)
    mockAsyncStorage.removeItem.mockResolvedValue(undefined)
    mockSecureStore.getItemAsync.mockResolvedValue(null)
    mockSecureStore.setItemAsync.mockResolvedValue(undefined)
    mockSecureStore.deleteItemAsync.mockResolvedValue(undefined)
  })

  it('stores a pairing token in SecureStore instead of AsyncStorage', async () => {
    await saveCurrentDevice(pairedDevice)

    const asyncStoragePayloads = mockAsyncStorage.setItem.mock.calls.map(([, value]) => String(value))
    expect(asyncStoragePayloads.join('\n')).not.toContain(pairedDevice.token)
    expect(mockSecureStore.setItemAsync).toHaveBeenCalledWith(
      expect.any(String),
      expect.stringContaining(pairedDevice.token),
      expect.objectContaining({ keychainAccessible: 'WHEN_UNLOCKED_THIS_DEVICE_ONLY' }),
    )
  })

  it('restores a paired device using its encrypted token record', async () => {
    await saveCurrentDevice(pairedDevice)
    const currentDevicePayload = mockAsyncStorage.setItem.mock.calls.find(
      ([key]) => key === '@pctv/current_device',
    )?.[1]
    const tokenPayload = mockSecureStore.setItemAsync.mock.calls[0]?.[1]
    if (typeof currentDevicePayload !== 'string' || typeof tokenPayload !== 'string') {
      throw new Error('Expected paired device records to be persisted.')
    }
    mockAsyncStorage.getItem.mockImplementation(async (key: string) =>
      key === '@pctv/current_device' ? currentDevicePayload : null,
    )
    mockSecureStore.getItemAsync.mockResolvedValue(tokenPayload)

    await expect(getCurrentDevice()).resolves.toEqual(pairedDevice)
  })

  it('starts independent secure-token and saved-device reads together', async () => {
    const deviceMetadata = {
      id: pairedDevice.id,
      name: pairedDevice.name,
      host: pairedDevice.host,
      port: pairedDevice.port,
      lastConnected: pairedDevice.lastConnected,
    }
    let releaseTokens!: (value: string) => void
    let releaseSavedDevices!: (value: string) => void
    const tokenRecord = new Promise<string>((resolve) => {
      releaseTokens = resolve
    })
    const savedDevices = new Promise<string>((resolve) => {
      releaseSavedDevices = resolve
    })
    mockAsyncStorage.getItem.mockImplementation(async (key: string) => {
      if (key === '@pctv/current_device') return JSON.stringify(deviceMetadata)
      if (key === '@pctv/saved_devices') return savedDevices
      return null
    })
    mockSecureStore.getItemAsync.mockImplementation(() => tokenRecord)

    const restored = getCurrentDevice()
    await Promise.resolve()
    await Promise.resolve()

    expect(mockSecureStore.getItemAsync).toHaveBeenCalledTimes(1)
    expect(mockAsyncStorage.getItem).toHaveBeenCalledWith('@pctv/saved_devices')

    releaseTokens(JSON.stringify({ [pairedDevice.id]: pairedDevice.token }))
    releaseSavedDevices(JSON.stringify([deviceMetadata]))
    await expect(restored).resolves.toEqual(pairedDevice)
  })

  it('removes legacy plaintext tokens from every persisted device record', async () => {
    const legacyPayload = JSON.stringify(pairedDevice)
    mockAsyncStorage.getItem.mockImplementation(async (key: string) => {
      if (key === '@pctv/current_device') return legacyPayload
      if (key === '@pctv/saved_devices') return JSON.stringify([pairedDevice])
      return null
    })

    await expect(getCurrentDevice()).resolves.toEqual(pairedDevice)
    expect(mockAsyncStorage.setItem).toHaveBeenCalledWith(
      '@pctv/saved_devices',
      expect.any(String),
    )
    const asyncStoragePayloads = mockAsyncStorage.setItem.mock.calls.map(([, value]) => String(value))
    expect(asyncStoragePayloads.join('\n')).not.toContain(pairedDevice.token)
    expect(mockSecureStore.setItemAsync).toHaveBeenCalledWith(
      expect.any(String),
      expect.stringContaining(pairedDevice.token),
      expect.any(Object),
    )
  })

  it('forgets the current device and removes local credentials', async () => {
    const deviceMetadata = {
      id: pairedDevice.id,
      name: pairedDevice.name,
      host: pairedDevice.host,
      port: pairedDevice.port,
      lastConnected: pairedDevice.lastConnected,
    }
    mockAsyncStorage.getItem.mockImplementation(async (key: string) => {
      if (key === '@pctv/current_device') return JSON.stringify(deviceMetadata)
      if (key === '@pctv/saved_devices') return JSON.stringify([deviceMetadata])
      return null
    })
    mockSecureStore.getItemAsync.mockResolvedValue(
      JSON.stringify({ [pairedDevice.id]: pairedDevice.token }),
    )

    await forgetCurrentDevice()

    expect(mockAsyncStorage.removeItem).toHaveBeenCalledWith('@pctv/current_device')
    expect(mockAsyncStorage.setItem).toHaveBeenCalledWith(
      '@pctv/saved_devices',
      JSON.stringify([]),
    )
    expect(mockSecureStore.deleteItemAsync).toHaveBeenCalledWith(
      'pctv.remote_tokens',
      expect.objectContaining({ keychainAccessible: 'WHEN_UNLOCKED_THIS_DEVICE_ONLY' }),
    )
  })
})
