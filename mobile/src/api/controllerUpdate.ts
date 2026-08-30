import { controllerOrigin } from './controllerEndpoint'

export interface ControllerUpdateResult {
  success: true
  message: string
  version: string | null
  restartRequired: boolean
}

type FetchUpdate = (input: string, init: RequestInit) => Promise<Response>

export function sameControllerVersion(left: string, right: string): boolean {
  return left.replace(/^v/i, '') === right.replace(/^v/i, '')
}

export async function fetchControllerVersion(
  host: string,
  port: number,
  fetchHealth: FetchUpdate = fetch,
): Promise<string | null> {
  const origin = controllerOrigin(host, port)
  try {
    const response = await fetchHealth(`${origin}/api/health`, { method: 'GET' })
    if (!response.ok) return null
    const payload = (await response.json()) as Record<string, unknown>
    return typeof payload.version === 'string' ? payload.version : null
  } catch {
    return null
  }
}

export async function applyControllerUpdate(
  host: string,
  port: number,
  token: string,
  fetchUpdate: FetchUpdate = fetch,
): Promise<ControllerUpdateResult> {
  const origin = controllerOrigin(host, port)
  let response: Response
  try {
    response = await fetchUpdate(`${origin}/api/update/apply`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Origin: origin,
      },
    })
  } catch {
    throw new Error('無法連上電視盒，請確認 HTTPS 憑證與網路連線。')
  }
  let payload: Record<string, unknown>
  try {
    payload = (await response.json()) as Record<string, unknown>
  } catch {
    throw new Error(
      response.ok
        ? '更新服務回應格式錯誤。'
        : `更新服務暫時無法使用（HTTP ${response.status}）。`,
    )
  }
  if (!response.ok || payload.success !== true) {
    const detail = payload.detail
    const message = payload.message
    throw new Error(
      typeof detail === 'string'
        ? detail
        : typeof message === 'string'
          ? message
          : '更新失敗。',
    )
  }

  return {
    success: true,
    message: typeof payload.message === 'string' ? payload.message : '更新已下載。',
    version: typeof payload.version === 'string' ? payload.version : null,
    restartRequired: payload.restart_required === true,
  }
}
