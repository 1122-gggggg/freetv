export function isIpv4Literal(host: string): boolean {
  const octets = host.split('.')
  return (
    octets.length === 4 &&
    octets.every((octet) => /^(0|[1-9]\d{0,2})$/.test(octet) && Number(octet) <= 255)
  )
}

function isDnsHostname(host: string): boolean {
  if (host.length > 253 || host.startsWith('.') || host.endsWith('.')) return false
  if (/^[\d.]+$/.test(host)) return false
  const labels = host.split('.')
  return (
    labels.length >= 2 &&
    labels.every(
      (label) =>
        label.length >= 1 &&
        label.length <= 63 &&
        /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/i.test(label),
    )
  )
}

function isControllerHost(host: string): boolean {
  return isIpv4Literal(host) || isDnsHostname(host)
}

export function parseControllerPort(rawPort: string | number | undefined | null): number {
  if (rawPort === undefined || rawPort === null) {
    return 8765
  }
  if (typeof rawPort === 'number') {
    if (!Number.isInteger(rawPort) || rawPort < 1 || rawPort > 65_535) {
      throw new Error('連接埠必須是 1 到 65535 之間的數字。')
    }
    return rawPort
  }
  const str = rawPort.trim()
  if (str === '') {
    return 8765
  }
  if (!/^\d+$/.test(str)) {
    throw new Error('連接埠必須是 1 到 65535 之間的數字。')
  }
  const port = parseInt(str, 10)
  if (port < 1 || port > 65_535) {
    throw new Error('連接埠必須是 1 到 65535 之間的數字。')
  }
  return port
}

export function validateControllerTarget(
  host: string,
  rawPort?: string | number | null,
): { host: string; port: number } {
  if (typeof host !== 'string') {
    throw new Error('請輸入有效的 IPv4 位址或安全網域名稱。')
  }
  const trimmedHost = host.trim()
  if (!isControllerHost(trimmedHost)) {
    throw new Error('請輸入有效的 IPv4 位址或安全網域名稱。')
  }
  const port = parseControllerPort(rawPort)
  return {
    host: isIpv4Literal(trimmedHost) ? trimmedHost : trimmedHost.toLowerCase(),
    port,
  }
}

export function controllerOrigin(host: string, port: number): string {
  if (
    !Number.isInteger(port) ||
    port < 1 ||
    port > 65_535 ||
    typeof host !== 'string' ||
    host !== host.trim() ||
    !isControllerHost(host)
  ) {
    throw new Error('控制器主機或連接埠無效。')
  }

  let url: URL
  try {
    url = new URL(`https://${host}:${port}`)
  } catch {
    throw new Error('控制器主機或連接埠無效。')
  }

  if (
    url.protocol !== 'https:' ||
    !url.hostname ||
    url.username ||
    url.password ||
    url.pathname !== '/' ||
    url.search ||
    url.hash
  ) {
    throw new Error('控制器主機或連接埠無效。')
  }

  return url.origin
}
