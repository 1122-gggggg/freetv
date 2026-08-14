import AsyncStorage from '@react-native-async-storage/async-storage'

export interface SavedDevice {
  id: string
  name: string
  host: string
  port: number
  token: string
  lastConnected: number
}

const STORAGE_KEYS = {
  CURRENT_DEVICE: '@pctv/current_device',
  SAVED_DEVICES: '@pctv/saved_devices',
} as const

export async function getCurrentDevice(): Promise<SavedDevice | null> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEYS.CURRENT_DEVICE)
    if (!raw) return null
    return JSON.parse(raw) as SavedDevice
  } catch {
    return null
  }
}

export async function saveCurrentDevice(device: SavedDevice): Promise<void> {
  await AsyncStorage.setItem(STORAGE_KEYS.CURRENT_DEVICE, JSON.stringify(device))
  const devices = await getSavedDevices()
  const updated = [device, ...devices.filter((d) => d.host !== device.host || d.port !== device.port)]
  await AsyncStorage.setItem(STORAGE_KEYS.SAVED_DEVICES, JSON.stringify(updated.slice(0, 10)))
}

export async function getSavedDevices(): Promise<SavedDevice[]> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEYS.SAVED_DEVICES)
    if (!raw) return []
    return JSON.parse(raw) as SavedDevice[]
  } catch {
    return []
  }
}

export async function forgetCurrentDevice(): Promise<void> {
  const current = await getCurrentDevice()
  if (current) {
    const devices = await getSavedDevices()
    const updated = devices.filter((d) => d.host !== current.host || d.port !== current.port)
    await AsyncStorage.setItem(STORAGE_KEYS.SAVED_DEVICES, JSON.stringify(updated))
  }
  await AsyncStorage.removeItem(STORAGE_KEYS.CURRENT_DEVICE)
}
