import { parsePairingPayload, resolvePairingTarget } from './qrScanner'

describe('parsePairingPayload', () => {
  it('parses raw 6-digit pairing code', () => {
    const result = parsePairingPayload('123456')
    expect(result).toEqual({
      host: null,
      port: 8765,
      code: '123456',
    })
  })

  it('parses custom pctv:// scheme', () => {
    const result = parsePairingPayload('pctv://pair?host=192.168.1.50&port=8765&code=654321')
    expect(result).toEqual({
      host: '192.168.1.50',
      port: 8765,
      code: '654321',
    })
  })

  it('parses HTTPS web remote URL', () => {
    const result = parsePairingPayload('https://172.20.10.8:8765/remote?code=998877')
    expect(result).toEqual({
      host: '172.20.10.8',
      port: 8765,
      code: '998877',
    })
  })

  it('uses the standard HTTPS port for a public tunnel URL', () => {
    const result = parsePairingPayload(
      'https://example.trycloudflare.com/remote?code=112233',
    )
    expect(result).toEqual({
      host: 'example.trycloudflare.com',
      port: 443,
      code: '112233',
    })
  })

  it('returns null for invalid inputs', () => {
    expect(parsePairingPayload('')).toBeNull()
    expect(parsePairingPayload('invalid text')).toBeNull()
  })
})

describe('resolvePairingTarget', () => {
  it('does not invent an endpoint for a code-only QR scan', () => {
    const payload = parsePairingPayload('123456')

    expect(payload).not.toBeNull()
    expect(resolvePairingTarget(payload!, '', 8765)).toBeNull()
  })

  it('uses the entered port with a code-only QR scan', () => {
    const payload = parsePairingPayload('123456')

    expect(resolvePairingTarget(payload!, '192.168.1.42', 9000)).toEqual({
      host: '192.168.1.42',
      port: 9000,
    })
  })

  it('uses the QR endpoint port when the payload supplies its host', () => {
    const payload = parsePairingPayload('pctv://pair?host=192.168.1.42&port=9000&code=123456')

    expect(resolvePairingTarget(payload!, '192.168.1.99', 8765)).toEqual({
      host: '192.168.1.42',
      port: 9000,
    })
  })
})
