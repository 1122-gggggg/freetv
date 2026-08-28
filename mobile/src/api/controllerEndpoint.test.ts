import {
  controllerOrigin,
  isIpv4Literal,
  parseControllerPort,
  validateControllerTarget,
} from './controllerEndpoint'

describe('isIpv4Literal', () => {
  it('accepts valid numeric IPv4 addresses', () => {
    expect(isIpv4Literal('192.168.1.1')).toBe(true)
    expect(isIpv4Literal('10.0.0.1')).toBe(true)
    expect(isIpv4Literal('127.0.0.1')).toBe(true)
    expect(isIpv4Literal('0.0.0.0')).toBe(true)
    expect(isIpv4Literal('255.255.255.255')).toBe(true)
  })

  it('rejects invalid octets, leading zeros, non-numeric, or wrong octet count', () => {
    expect(isIpv4Literal('192.168.01.1')).toBe(false)
    expect(isIpv4Literal('192.168.1.256')).toBe(false)
    expect(isIpv4Literal('192.168.1.1.1')).toBe(false)
    expect(isIpv4Literal('192.168.1')).toBe(false)
    expect(isIpv4Literal('pc-tv.local')).toBe(false)
    expect(isIpv4Literal('')).toBe(false)
    expect(isIpv4Literal('192.168.1.a')).toBe(false)
  })
})

describe('parseControllerPort', () => {
  it('defaults blank or omitted port to 8765', () => {
    expect(parseControllerPort(undefined)).toBe(8765)
    expect(parseControllerPort(null)).toBe(8765)
    expect(parseControllerPort('')).toBe(8765)
    expect(parseControllerPort('   ')).toBe(8765)
  })

  it('parses valid numeric ports between 1 and 65535', () => {
    expect(parseControllerPort(8765)).toBe(8765)
    expect(parseControllerPort('8765')).toBe(8765)
    expect(parseControllerPort('1')).toBe(1)
    expect(parseControllerPort('65535')).toBe(65535)
    expect(parseControllerPort(80)).toBe(80)
  })

  it('rejects out of range or non-numeric port strings', () => {
    expect(() => parseControllerPort('0')).toThrow('連接埠必須是 1 到 65535 之間的數字。')
    expect(() => parseControllerPort('65536')).toThrow('連接埠必須是 1 到 65535 之間的數字。')
    expect(() => parseControllerPort('-1')).toThrow('連接埠必須是 1 到 65535 之間的數字。')
    expect(() => parseControllerPort('abc')).toThrow('連接埠必須是 1 到 65535 之間的數字。')
    expect(() => parseControllerPort('8765a')).toThrow('連接埠必須是 1 到 65535 之間的數字。')
    expect(() => parseControllerPort(0)).toThrow('連接埠必須是 1 到 65535 之間的數字。')
    expect(() => parseControllerPort(65536)).toThrow('連接埠必須是 1 到 65535 之間的數字。')
  })
})

describe('validateControllerTarget', () => {
  it('validates and returns sanitized host and port with default port when blank', () => {
    expect(validateControllerTarget(' 192.168.1.50 ', '')).toEqual({
      host: '192.168.1.50',
      port: 8765,
    })
    expect(validateControllerTarget('192.168.1.50', '9000')).toEqual({
      host: '192.168.1.50',
      port: 9000,
    })
  })

  it('accepts a secure tunnel hostname', () => {
    expect(validateControllerTarget('example.trycloudflare.com', 443)).toEqual({
      host: 'example.trycloudflare.com',
      port: 443,
    })
  })

  it('throws for invalid hosts', () => {
    for (const host of ['', 'https://example.com', '-example.com', '192.168.1.256']) {
      expect(() => validateControllerTarget(host, '8765')).toThrow(
        '請輸入有效的 IPv4 位址或安全網域名稱。',
      )
    }
  })

  it('throws for invalid port', () => {
    expect(() => validateControllerTarget('192.168.1.50', 'invalid')).toThrow(
      '連接埠必須是 1 到 65535 之間的數字。',
    )
  })
})

describe('controllerOrigin', () => {
  it('builds the exact HTTPS origin for controller endpoints', () => {
    expect(controllerOrigin('192.168.1.42', 8765)).toBe('https://192.168.1.42:8765')
    expect(controllerOrigin('example.trycloudflare.com', 443)).toBe(
      'https://example.trycloudflare.com',
    )
  })

  it('rejects an authority that could change the request destination', () => {
    expect(() => controllerOrigin('192.168.1.42:444', 8765)).toThrow('控制器主機或連接埠無效。')
    expect(() => controllerOrigin('https://192.168.1.42', 8765)).toThrow('控制器主機或連接埠無效。')
  })
  it('rejects malformed hostnames and IPv4 controller addresses', () => {
    expect(() => controllerOrigin('-pc-tv.local', 8765)).toThrow(
      '控制器主機或連接埠無效。',
    )
    expect(() => controllerOrigin('192.168.1.256', 8765)).toThrow(
      '控制器主機或連接埠無效。',
    )
  })
})
