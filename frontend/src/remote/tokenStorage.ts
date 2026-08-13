const TOKEN_KEY = 'pc-tv-box.remote-token'

export function storedRemoteToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function rememberRemoteToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function forgetStoredRemoteToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export async function revokeRemoteToken(token: string): Promise<void> {
  let response: Response
  try {
    response = await fetch('/api/remote-token', {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
  } catch {
    throw new Error('Could not unpair this remote.')
  }
  if (!response.ok && response.status !== 401) {
    throw new Error('Could not unpair this remote.')
  }
}
