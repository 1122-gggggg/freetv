export interface ParsedPairingPayload {
  host: string | null
  port: number
  code: string | null
}

export interface PairingTarget {
  host: string
  port: number
}

export function parsePairingPayload(raw: string): ParsedPairingPayload | null {
  const trimmed = raw.trim()
  if (!trimmed) return null

  // 1. Plain 6-digit code
  if (/^\d{6}$/.test(trimmed)) {
    return {
      host: null,
      port: 8765,
      code: trimmed,
    }
  }

  // 2. Custom schema: pctv://pair?host=...&port=...&code=...
  if (trimmed.startsWith('pctv://')) {
    try {
      const url = new URL(trimmed)
      const host = url.searchParams.get('host') || url.searchParams.get('ip')
      const portStr = url.searchParams.get('port')
      const code = url.searchParams.get('code')
      const port = portStr ? parseInt(portStr, 10) : 8765
      return {
        host: host || null,
        port: Number.isNaN(port) ? 8765 : port,
        code: code && /^\d{6}$/.test(code) ? code : null,
      }
    } catch {
      return null
    }
  }

  // 3. HTTP / HTTPS URL: https://<host>:<port>/remote?code=...
  if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
    try {
      const url = new URL(trimmed)
      const host = url.hostname
      const portStr = url.port
      const port = portStr ? parseInt(portStr, 10) : (url.protocol === 'https:' ? 443 : 80)
      const code = url.searchParams.get('code')
      return {
        host,
        port: port === 443 || port === 80 ? (portStr ? port : 8765) : port,
        code: code && /^\d{6}$/.test(code) ? code : null,
      }
    } catch {
      return null
    }
  }

  return null
}

export function resolvePairingTarget(
  payload: ParsedPairingPayload,
  manuallyEnteredHost: string,
  manuallyEnteredPort: string | number,
): PairingTarget | null {
  const host = payload.host ?? manuallyEnteredHost.trim()
  const port = payload.host ? payload.port : Number(manuallyEnteredPort)
  return host ? { host, port } : null
}
