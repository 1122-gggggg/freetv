import AsyncStorage from '@react-native-async-storage/async-storage'
import * as SecureStore from 'expo-secure-store'

export interface SavedDevice {
  id: string
  name: string
  host: string
  port: number
  token: string
  lastConnected: number
}

interface StoredDevice extends Omit<SavedDevice, 'token'> {
  token?: string
}

const STORAGE_KEYS = {
  CURRENT_DEVICE: '@pctv/current_device',
  SAVED_DEVICES: '@pctv/saved_devices',
  REMOTE_TOKENS: 'pctv.remote_tokens',
} as const

const SECURE_STORE_OPTIONS = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
} as const

export async function getCurrentDevice(): Promise<SavedDevice | null> {
  try {
    const current = await readStoredDevice(STORAGE_KEYS.CURRENT_DEVICE)
    if (!current) return null

    const tokens = await readTokenRecord()
    const storedDevices = await readStoredDevices()
    const currentMigrated = migrateLegacyToken(current, tokens)
    let savedDevicesMigrated = false
    for (const storedDevice of storedDevices) {
      savedDevicesMigrated = migrateLegacyToken(storedDevice, tokens) || savedDevicesMigrated
    }
    if (currentMigrated || savedDevicesMigrated) {
      await writeTokenRecord(tokens)
    }
    if (currentMigrated) {
      await AsyncStorage.setItem(STORAGE_KEYS.CURRENT_DEVICE, JSON.stringify(deviceMetadata(current)))
    }
    if (savedDevicesMigrated) {
      await AsyncStorage.setItem(
        STORAGE_KEYS.SAVED_DEVICES,
        JSON.stringify(storedDevices.map(deviceMetadata)),
      )
    }
    return hydrateDevice(current, tokens)
  } catch {
    return null
  }
}

export async function saveCurrentDevice(device: SavedDevice): Promise<void> {
  if (!device.token) throw new Error('A paired device requires a token.')

  const tokens = await readTokenRecord()
  const storedDevices = await readStoredDevices()
  for (const storedDevice of storedDevices) {
    migrateLegacyToken(storedDevice, tokens)
  }
  tokens.set(device.id, device.token)

  const currentMetadata = deviceMetadata(device)
  const updated = [
    currentMetadata,
    ...storedDevices
      .map(deviceMetadata)
      .filter((storedDevice) => storedDevice.host !== device.host || storedDevice.port !== device.port),
  ].slice(0, 10)
  const retainedIds = new Set(updated.map((storedDevice) => storedDevice.id))
  for (const id of tokens.keys()) {
    if (!retainedIds.has(id)) tokens.delete(id)
  }

  await writeTokenRecord(tokens)
  await AsyncStorage.setItem(STORAGE_KEYS.CURRENT_DEVICE, JSON.stringify(currentMetadata))
  await AsyncStorage.setItem(STORAGE_KEYS.SAVED_DEVICES, JSON.stringify(updated))
}

export async function getSavedDevices(): Promise<SavedDevice[]> {
  try {
    const storedDevices = await readStoredDevices()
    const tokens = await readTokenRecord()
    let tokensChanged = false
    let metadataChanged = false
    const devices: SavedDevice[] = []

    for (const storedDevice of storedDevices) {
      tokensChanged = migrateLegacyToken(storedDevice, tokens) || tokensChanged
      const hydrated = hydrateDevice(storedDevice, tokens)
      if (hydrated) {
        devices.push(hydrated)
        metadataChanged ||= storedDevice.token !== undefined
      } else {
        metadataChanged = true
      }
    }

    if (tokensChanged) await writeTokenRecord(tokens)
    if (metadataChanged) {
      await AsyncStorage.setItem(
        STORAGE_KEYS.SAVED_DEVICES,
        JSON.stringify(devices.map(deviceMetadata)),
      )
    }
    return devices
  } catch {
    return []
  }
}

export async function forgetCurrentDevice(): Promise<void> {
  const current = await readStoredDevice(STORAGE_KEYS.CURRENT_DEVICE)
  const storedDevices = await readStoredDevices()
  const tokens = await readTokenRecord()
  const remaining = current
    ? storedDevices.filter(
        (storedDevice) =>
          storedDevice.host !== current.host || storedDevice.port !== current.port,
      )
    : storedDevices

  if (current) tokens.delete(current.id)
  for (const storedDevice of storedDevices) {
    if (!remaining.some((device) => device.id === storedDevice.id)) {
      tokens.delete(storedDevice.id)
    }
  }

  await writeTokenRecord(tokens)
  await AsyncStorage.setItem(
    STORAGE_KEYS.SAVED_DEVICES,
    JSON.stringify(remaining.map(deviceMetadata)),
  )
  await AsyncStorage.removeItem(STORAGE_KEYS.CURRENT_DEVICE)
}

async function readStoredDevice(key: string): Promise<StoredDevice | null> {
  const raw = await AsyncStorage.getItem(key)
  if (!raw) return null
  try {
    return parseStoredDevice(JSON.parse(raw))
  } catch {
    return null
  }
}

async function readStoredDevices(): Promise<StoredDevice[]> {
  const raw = await AsyncStorage.getItem(STORAGE_KEYS.SAVED_DEVICES)
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .map(parseStoredDevice)
      .filter((device): device is StoredDevice => device !== null)
      .slice(0, 10)
  } catch {
    return []
  }
}

function parseStoredDevice(value: unknown): StoredDevice | null {
  if (!value || typeof value !== 'object') return null
  const device = value as Record<string, unknown>
  const id = device.id
  const name = device.name
  const host = device.host
  const port = device.port
  const lastConnected = device.lastConnected
  const token = device.token
  if (
    typeof id !== 'string' ||
    !id ||
    typeof name !== 'string' ||
    !name ||
    typeof host !== 'string' ||
    !host ||
    typeof port !== 'number' ||
    !Number.isInteger(port) ||
    typeof lastConnected !== 'number' ||
    !Number.isFinite(lastConnected) ||
    (token !== undefined && (typeof token !== 'string' || !token))
  ) {
    return null
  }
  return {
    id,
    name,
    host,
    port,
    lastConnected,
    ...(typeof token === 'string' ? { token } : {}),
  }
}

function deviceMetadata(device: StoredDevice | SavedDevice): Omit<SavedDevice, 'token'> {
  return {
    id: device.id,
    name: device.name,
    host: device.host,
    port: device.port,
    lastConnected: device.lastConnected,
  }
}

function hydrateDevice(device: StoredDevice, tokens: ReadonlyMap<string, string>): SavedDevice | null {
  const token = tokens.get(device.id)
  return token ? { ...deviceMetadata(device), token } : null
}

function migrateLegacyToken(device: StoredDevice, tokens: Map<string, string>): boolean {
  if (!device.token) return false
  if (!tokens.has(device.id)) tokens.set(device.id, device.token)
  return true
}

async function readTokenRecord(): Promise<Map<string, string>> {
  const raw = await SecureStore.getItemAsync(STORAGE_KEYS.REMOTE_TOKENS, SECURE_STORE_OPTIONS)
  if (!raw) return new Map()
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return new Map()
    const tokens = new Map<string, string>()
    for (const [id, token] of Object.entries(parsed)) {
      if (typeof token === 'string' && token.length > 0) tokens.set(id, token)
    }
    return tokens
  } catch {
    return new Map()
  }
}

async function writeTokenRecord(tokens: ReadonlyMap<string, string>): Promise<void> {
  if (tokens.size === 0) {
    await SecureStore.deleteItemAsync(STORAGE_KEYS.REMOTE_TOKENS, SECURE_STORE_OPTIONS)
    return
  }
  await SecureStore.setItemAsync(
    STORAGE_KEYS.REMOTE_TOKENS,
    JSON.stringify(Object.fromEntries(tokens)),
    SECURE_STORE_OPTIONS,
  )
}
