import { controllerOrigin } from '../api/controllerEndpoint'


export async function pairWithDevice(
  host: string,
  port: number,
  code: string,
): Promise<{ token: string } | { error: string }> {
  const sanitizedCode = typeof code === 'string' ? code.trim() : ''
  if (!/^\d{6}$/.test(sanitizedCode)) {
    return { error: 'Pairing code must be 6 digits.' }
  }
  try {
    const origin = controllerOrigin(host, port)
    const response = await fetch(`${origin}/api/pair`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: origin,
      },
      body: JSON.stringify({ code: sanitizedCode }),
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

export async function revokeDeviceToken(host: string, port: number, token: string): Promise<void> {
  const origin = controllerOrigin(host, port)
  let response: Response
  try {
    response = await fetch(`${origin}/api/remote-token`, {
      method: 'DELETE',
      headers: {
        Authorization: `Bearer ${token}`,
        Origin: origin,
      },
    })
  } catch {
    throw new Error('Could not reach this PC TV Box to revoke the remote token.')
  }

  if (!response.ok && response.status !== 401) {
    throw new Error('The PC TV Box did not revoke the remote token.')
  }
}
