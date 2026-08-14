import { parsePairingPayload } from './qrScanner'

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

  it('returns null for invalid inputs', () => {
    expect(parsePairingPayload('')).toBeNull()
    expect(parsePairingPayload('invalid text')).toBeNull()
  })
})
