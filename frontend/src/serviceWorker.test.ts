import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it, vi } from 'vitest'

type FetchEvent = {
  request: Request
  respondWith: (response: Promise<Response>) => void
}

function dispatchFetch(handler: (event: FetchEvent) => void, request: Request): Promise<Response> {
  let responsePromise: Promise<Response> | undefined
  handler({
    request,
    respondWith: (response) => {
      responsePromise = response
    },
  })
  if (!responsePromise) throw new Error('The service worker did not handle the asset request.')
  return responsePromise
}

function requestUrl(request: Request | string): string {
  return typeof request === 'string'
    ? new URL(request, 'https://tv-box.test').toString()
    : request.url
}

describe('service worker asset cache', () => {
  it('serves a previously fetched immutable asset while offline', async () => {
    const handlers = new Map<string, (event: FetchEvent) => void>()
    const stored = new Map<string, Response>()
    const cache = {
      addAll: vi.fn(async () => undefined),
      match: vi.fn(async (request: Request | string) => stored.get(requestUrl(request))?.clone()),
      put: vi.fn(async (request: Request, response: Response) => {
        stored.set(request.url, response.clone())
      }),
    }
    const cacheStorage = {
      open: vi.fn(async () => cache),
      keys: vi.fn(async () => ['pc-tv-box-v2']),
      delete: vi.fn(async () => true),
      match: vi.fn(async (request: Request | string) => stored.get(requestUrl(request))?.clone()),
    }
    const worker = {
      location: { origin: 'https://tv-box.test' },
      addEventListener: (type: string, handler: (event: FetchEvent) => void) => {
        handlers.set(type, handler)
      },
      skipWaiting: vi.fn(),
      clients: { claim: vi.fn() },
    }
    let online = true
    const fetchResource = vi.fn(async () => {
      if (!online) throw new TypeError('offline')
      return new Response('route bundle', { status: 200 })
    })
    const source = readFileSync(resolve(process.cwd(), 'public/service-worker.js'), 'utf8')
    Function('self', 'caches', 'fetch', source)(worker, cacheStorage, fetchResource)
    const handleFetch = handlers.get('fetch')
    expect(handleFetch).toBeDefined()
    if (!handleFetch) throw new Error('The service worker did not register a fetch handler.')

    const request = new Request('https://tv-box.test/assets/RemotePage-abc123.js')
    expect(await dispatchFetch(handleFetch, request).then((response) => response.text())).toBe(
      'route bundle',
    )
    expect(cache.put).toHaveBeenCalledTimes(1)

    online = false
    expect(await dispatchFetch(handleFetch, request).then((response) => response.text())).toBe(
      'route bundle',
    )
    expect(fetchResource).toHaveBeenCalledTimes(1)
  })

  it('falls back to the cached remote shell for offline navigation', async () => {
    const handlers = new Map<string, (event: FetchEvent) => void>()
    const stored = new Map<string, Response>([
      ['https://tv-box.test/remote', new Response('cached remote shell', { status: 200 })],
    ])
    const cache = {
      addAll: vi.fn(async () => undefined),
      match: vi.fn(async (request: Request | string) => stored.get(requestUrl(request))?.clone()),
      put: vi.fn(async () => undefined),
    }
    const cacheStorage = {
      open: vi.fn(async () => cache),
      keys: vi.fn(async () => ['pc-tv-box-v2']),
      delete: vi.fn(async () => true),
      match: vi.fn(async (request: Request | string) => stored.get(requestUrl(request))?.clone()),
    }
    const worker = {
      location: { origin: 'https://tv-box.test' },
      addEventListener: (type: string, handler: (event: FetchEvent) => void) => {
        handlers.set(type, handler)
      },
      skipWaiting: vi.fn(),
      clients: { claim: vi.fn() },
    }
    const fetchResource = vi.fn(async () => {
      throw new TypeError('offline')
    })
    const source = readFileSync(resolve(process.cwd(), 'public/service-worker.js'), 'utf8')
    Function('self', 'caches', 'fetch', source)(worker, cacheStorage, fetchResource)
    const handleFetch = handlers.get('fetch')
    if (!handleFetch) throw new Error('The service worker did not register a fetch handler.')
    const navigation = {
      method: 'GET',
      mode: 'navigate',
      url: 'https://tv-box.test/remote?code=123456',
    } as Request

    const response = await dispatchFetch(handleFetch, navigation)

    expect(await response.text()).toBe('cached remote shell')
    expect(cache.put).not.toHaveBeenCalled()
  })
})
