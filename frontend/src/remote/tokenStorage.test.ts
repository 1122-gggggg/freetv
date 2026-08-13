import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { revokeRemoteToken } from './tokenStorage'

describe('revokeRemoteToken', () => {
  const token = 'paired-token-value-that-is-long-enough'

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends the paired token only as a bearer credential to the local revoke endpoint', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValue({ ok: true, status: 204 } as Response)

    await revokeRemoteToken(token)

    expect(fetchMock).toHaveBeenCalledWith('/api/remote-token', {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
  })

  it('keeps the remote paired when the controller cannot revoke it', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValue({ ok: false, status: 500 } as Response)

    await expect(revokeRemoteToken(token)).rejects.toThrow('Could not unpair this remote.')
  })
})
