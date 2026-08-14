export interface DiscoveredBox {
  id: string
  name: string
  host: string
  port: number
  braveAvailable: boolean
  edgeAvailable: boolean
  mpvAvailable: boolean
}

export async function checkDeviceHealth(host: string, port = 8765, timeoutMs = 2000): Promise<DiscoveredBox | null> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(`https://${host}:${port}/api/health`, {
      method: 'GET',
      signal: controller.signal,
    })
    clearTimeout(timer)

    if (!response.ok) return null
    const data = await response.json()
    if (data.status === 'ok' && data.backend === true) {
      return {
        id: `${host}:${port}`,
        name: `PC TV Box (${host})`,
        host,
        port,
        braveAvailable: !!data.brave_available,
        edgeAvailable: !!data.edge_available,
        mpvAvailable: !!data.mpv_available,
      }
    }
    return null
  } catch {
    clearTimeout(timer)
    return null
  }
}

export async function pairWithDevice(host: string, port: number, code: string): Promise<{ token: string } | { error: string }> {
  try {
    const response = await fetch(`https://${host}:${port}/api/pair`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ code }),
    })
    const data = await response.json()
    if (!response.ok || !data.token) {
      return { error: data.detail || 'Pairing failed. Please check the code.' }
    }
    return { token: data.token }
  } catch (err) {
    return { error: err instanceof Error ? err.message : 'Network error connecting to PC TV' }
  }
}
