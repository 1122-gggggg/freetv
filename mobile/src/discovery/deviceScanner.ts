import { controllerOrigin } from '../api/controllerEndpoint'


export async function pairWithDevice(
  host: string,
  port: number,
  code: string,
): Promise<{ token: string } | { error: string }> {
  const sanitizedCode = typeof code === 'string' ? code.trim() : ''
  if (!/^\d{6}$/.test(sanitizedCode)) {
    return { error: '配對碼必須是六位數字。' }
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
      return { error: data.detail || '配對失敗。請確認配對碼。' }
    }
    return { token: data.token }
  } catch (err) {
    return { error: err instanceof Error ? err.message : '連線到電視盒時發生網路錯誤' }
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
    throw new Error('無法連上這台電視盒以撤銷遙控器權杖。')
  }

  if (!response.ok && response.status !== 401) {
    throw new Error('電視盒未撤銷遙控器權杖。')
  }
}
