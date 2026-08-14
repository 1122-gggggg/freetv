import { pairWithDevice, revokeDeviceToken } from './deviceScanner'

function response(status: number, body: unknown = {}): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

describe('controller HTTP transport', () => {
  const nativeFetch = globalThis.fetch

  afterEach(() => {
    globalThis.fetch = nativeFetch
  })

  it('sends the controller origin when pairing', async () => {
    const fetchMock = jest.fn().mockResolvedValue(response(200, { token: 'paired-token' }))
    globalThis.fetch = fetchMock

    await expect(pairWithDevice('192.168.1.42', 8765, '123456')).resolves.toEqual({
      token: 'paired-token',
    })
    expect(fetchMock).toHaveBeenCalledWith('https://192.168.1.42:8765/api/pair', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: 'https://192.168.1.42:8765',
      },
      body: JSON.stringify({ code: '123456' }),
    })
  })
  it('rejects invalid pairing codes without making a network request', async () => {
    const fetchMock = jest.fn()
    globalThis.fetch = fetchMock

    await expect(pairWithDevice('192.168.1.42', 8765, '12345')).resolves.toEqual({
      error: 'Pairing code must be 6 digits.',
    })
    await expect(pairWithDevice('192.168.1.42', 8765, '1234567')).resolves.toEqual({
      error: 'Pairing code must be 6 digits.',
    })
    await expect(pairWithDevice('192.168.1.42', 8765, 'abcdef')).resolves.toEqual({
      error: 'Pairing code must be 6 digits.',
    })
    await expect(pairWithDevice('192.168.1.42', 8765, '')).resolves.toEqual({
      error: 'Pairing code must be 6 digits.',
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('returns an error when endpoint origin is invalid', async () => {
    const fetchMock = jest.fn()
    globalThis.fetch = fetchMock

    const result = await pairWithDevice('invalid-host', 8765, '123456')
    expect(result).toEqual({ error: 'Invalid controller host or port.' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('returns detail message when server returns an error response', async () => {
    const fetchMock = jest.fn().mockResolvedValue(
      response(400, { detail: 'Incorrect pairing code entered.' }),
    )
    globalThis.fetch = fetchMock

    await expect(pairWithDevice('192.168.1.42', 8765, '123456')).resolves.toEqual({
      error: 'Incorrect pairing code entered.',
    })
  })

  it('sends the controller origin when revoking a paired remote', async () => {
    const fetchMock = jest.fn().mockResolvedValue(response(204))
    globalThis.fetch = fetchMock

    await expect(revokeDeviceToken('192.168.1.42', 8765, 'paired-token')).resolves.toBeUndefined()
    expect(fetchMock).toHaveBeenCalledWith('https://192.168.1.42:8765/api/remote-token', {
      method: 'DELETE',
      headers: {
        Authorization: 'Bearer paired-token',
        Origin: 'https://192.168.1.42:8765',
      },
    })
  })
})
