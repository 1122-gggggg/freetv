import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const runtimeSource = readFileSync(
  resolve(process.cwd(), '../backend/app/applications/netflix_control.js'),
  'utf8',
)

type FocusFingerprint = {
  role: string
  label: string
  uia: string
  text: string
  pathKind: string
  rail: string
  index: number
}

type NetflixContext = {
  stage: 'login' | 'verification' | 'browse' | 'details' | 'watch' | 'unknown'
  input_kind: 'email' | 'password' | 'code' | 'search' | 'none'
  has_error: boolean
  can_submit: boolean
  focused_title: string | null
}

type RuntimeResult = {
  ok: boolean
  status: string
  code?: string
  focus?: FocusFingerprint
  context?: NetflixContext
}

type Runtime = {
  version: string
  run: (action: string, focus: FocusFingerprint | null) => Promise<RuntimeResult>
}

function runtime(): Runtime {
  return (globalThis as typeof globalThis & { __freeTvNetflixControl: Runtime })
    .__freeTvNetflixControl
}

function setRect(element: Element, left: number, top: number, width = 120, height = 60): void {
  Object.defineProperty(element, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({
      left,
      top,
      right: left + width,
      bottom: top + height,
      width,
      height,
      x: left,
      y: top,
      toJSON: () => ({}),
    }),
  })
}

function setReadyVideo(): void {
  const video = document.querySelector('video') as HTMLVideoElement
  setRect(video, 20, 20, 640, 360)
  Object.defineProperty(video, 'readyState', { configurable: true, value: 2 })
  Object.defineProperty(video, 'paused', { configurable: true, value: false })
}

function setSequentialRects(selector = 'button,a,input,textarea,[tabindex],video'): void {
  document.querySelectorAll(selector).forEach((element, index) => {
    setRect(element, 40 + index * 160, 80)
  })
}

function installHitTesting(): void {
  Object.defineProperty(document, 'elementFromPoint', {
    configurable: true,
    value: vi.fn((x: number, y: number) => {
      const elements = [...document.querySelectorAll('*')].reverse()
      return elements.find((element) => {
        if (!(element instanceof HTMLElement) || element.hidden) return false
        const style = window.getComputedStyle(element)
        if (style.display === 'none' || style.visibility === 'hidden') return false
        const rect = element.getBoundingClientRect()
        return rect.width > 0 && rect.height > 0 && x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom
      }) ?? null
    }),
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
  document.body.innerHTML = ''
  window.history.replaceState({}, '', '/')
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1280 })
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: 720 })
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: vi.fn(),
  })
  installHitTesting()
  window.eval(runtimeSource)
})

describe('Netflix DOM control runtime', () => {
  it('returns strict safe contexts without reading input values or lengths', async () => {
    document.body.innerHTML =
      '<form><input id="email" type="email"><button type="submit">下一步</button></form>'
    const email = document.querySelector('#email') as HTMLInputElement
    setRect(email, 20, 20)
    setRect(document.querySelector('button')!, 180, 20)
    const valueRead = vi.fn(() => {
      throw new Error('secret read')
    })
    Object.defineProperty(email, 'value', {
      configurable: true,
      get: valueRead,
      set: () => undefined,
    })

    const login = await runtime().run('READ_CONTEXT', null)
    expect(login.context).toEqual({
      stage: 'login',
      input_kind: 'email',
      has_error: false,
      can_submit: true,
      focused_title: null,
    })
    expect(valueRead).not.toHaveBeenCalled()

    document.body.innerHTML =
      '<input id="code" inputmode="numeric" autocomplete="one-time-code"><button>驗證</button>'
    setRect(document.querySelector('#code')!, 20, 20)
    setRect(document.querySelector('button')!, 180, 20)
    const verification = await runtime().run('READ_CONTEXT', null)
    expect(verification.context).toMatchObject({
      stage: 'verification',
      input_kind: 'code',
      has_error: false,
      can_submit: true,
      focused_title: null,
    })
    expect(Object.keys(verification.context!).sort()).toEqual([
      'can_submit',
      'focused_title',
      'has_error',
      'input_kind',
      'stage',
    ])
  })

  it('uses the focused visible editable field before another login field', async () => {
    document.body.innerHTML =
      '<input id="email" type="email"><input id="password" type="password">'
    const email = document.querySelector('#email') as HTMLInputElement
    const password = document.querySelector('#password') as HTMLInputElement
    setRect(email, 20, 20)
    setRect(password, 180, 20)
    password.focus()

    const result = await runtime().run('READ_CONTEXT', null)

    expect(result.context).toMatchObject({
      stage: 'login',
      input_kind: 'password',
    })
  })

  it('ignores hidden details overlays and hidden errors when deriving context', async () => {
    document.body.innerHTML = `
      <div class="lolomoRow"><div class="title-card" tabindex="0">Visible</div></div>
      <div class="detail-modal" hidden><button>Play</button></div>
      <div role="alert" hidden>Hidden credential error</div>
    `
    const card = document.querySelector('.title-card') as HTMLElement
    setRect(card, 20, 80)
    card.focus()

    const result = await runtime().run('READ_CONTEXT', null)

    expect(result.context).toMatchObject({
      stage: 'browse',
      has_error: false,
      focused_title: 'Visible',
    })
  })

  it('never clicks an unrelated hero Play for a focused title card', async () => {
    document.body.innerHTML = `
      <button id="hero-play">Play</button>
      <div class="lolomoRow"><div id="card" class="title-card" tabindex="0">Focused</div></div>
    `
    const hero = document.querySelector('#hero-play') as HTMLButtonElement
    const card = document.querySelector('#card') as HTMLElement
    setRect(hero, 20, 20)
    setRect(card, 20, 100)
    card.focus()
    const heroClick = vi.spyOn(hero, 'click')
    const cardClick = vi.spyOn(card, 'click').mockImplementation(() => {
      const overlay = document.createElement('div')
      overlay.className = 'detail-modal'
      const play = document.createElement('button')
      play.id = 'focused-play'
      play.textContent = 'Play'
      overlay.append(play)
      document.body.append(overlay)
      setRect(overlay, 20, 20, 800, 600)
      setRect(play, 40, 40)
      play.addEventListener('click', () => {
        window.history.replaceState({}, '', '/watch/focused')
        document.body.innerHTML = '<video></video>'
        setReadyVideo()
      })
    })

    const result = await runtime().run('OK', null)

    expect(result.status).toBe('playing')
    expect(heroClick).not.toHaveBeenCalled()
    expect(cardClick).toHaveBeenCalledOnce()
  })

  it('uses the Netflix player back-to-browsing control before history', async () => {
    window.history.replaceState({}, '', '/watch/123')
    document.body.innerHTML =
      '<button data-uia="player-back-to-browsing">Back to browsing</button>'
    const playerBack = document.querySelector('button') as HTMLButtonElement
    setRect(playerBack, 20, 20)
    const click = vi.spyOn(playerBack, 'click').mockImplementation(() => {
      window.history.replaceState({}, '', '/browse')
      document.body.innerHTML =
        '<div class="lolomoRow"><div class="title-card" tabindex="0">Browse</div></div>'
      setRect(document.querySelector('.title-card')!, 20, 80)
    })
    const historyBack = vi.spyOn(window.history, 'back').mockImplementation(() => undefined)

    const result = await runtime().run('BACK', null)

    expect(result.ok).toBe(true)
    expect(click).toHaveBeenCalledOnce()
    expect(historyBack).not.toHaveBeenCalled()
  })

  it('moves within one rail and chooses the nearest x card in the adjacent rail', async () => {
    document.body.innerHTML = `
      <header><button id="header">Header</button></header>
      <div class="lolomoRow" id="top">
        <button class="handle-prev">Previous</button>
        <div class="title-card" tabindex="0">A</div>
        <div class="title-card" tabindex="0">B</div>
        <button class="handle-next">Next</button>
      </div>
      <div class="previewModal--wrapper"><button id="preview">Preview</button></div>
      <div class="lolomoRow" id="bottom">
        <div class="title-card" tabindex="0">C</div>
        <div class="title-card" tabindex="0">D</div>
      </div>
    `
    const [a, b, c, d] = [...document.querySelectorAll('.title-card')]
    setRect(document.querySelector('#header')!, 0, 0)
    setRect(document.querySelector('.handle-prev')!, -140, 0)
    setRect(a, 0, 80)
    setRect(b, 180, 80)
    setRect(document.querySelector('.handle-next')!, 340, 80)
    setRect(document.querySelector('#preview')!, 180, 150)
    setRect(c, 20, 240)
    setRect(d, 230, 240)
    ;(a as HTMLElement).focus()

    await runtime().run('NAV_RIGHT', null)
    expect(document.activeElement).toBe(b)
    await runtime().run('NAV_DOWN', null)
    expect(document.activeElement).toBe(d)
    await runtime().run('NAV_LEFT', null)
    expect(document.activeElement).toBe(c)
  })

  it('keeps focused titles browse-only, strips markup text, truncates, and reports errors as booleans', async () => {
    document.body.innerHTML = `
      <div class="lolomoRow">
        <div class="title-card" tabindex="0"><span>${'Title'.repeat(40)}</span></div>
      </div>
      <div role="alert">credential details must never be returned</div>
    `
    const card = document.querySelector('.title-card') as HTMLElement
    setRect(card, 20, 80)
    setRect(card.querySelector('span')!, 20, 80)
    setRect(document.querySelector('[role="alert"]')!, 20, 180)
    card.focus()
    const browse = await runtime().run('READ_CONTEXT', null)
    expect(browse.context?.stage).toBe('browse')
    expect(browse.context?.focused_title).toHaveLength(120)
    expect(browse.context?.focused_title).not.toContain('<')
    expect(browse.context?.has_error).toBe(true)
    expect(JSON.stringify(browse.context)).not.toContain('credential details')

    document.body.innerHTML =
      '<div class="detail-modal"><button data-uia="play-button">Play</button></div>'
    setRect(document.querySelector('.detail-modal')!, 20, 20, 800, 600)
    setRect(document.querySelector('button')!, 40, 40)
    const details = await runtime().run('READ_CONTEXT', null)
    expect(details.context).toMatchObject({ stage: 'details', focused_title: null })
  })

  it('direct-plays once immediately or after bounded detail settle without synthesizing a watch URL', async () => {
    document.body.innerHTML = `
      <div class="lolomoRow">
        <div id="card" class="title-card" tabindex="0">
          Example <button id="play">Resume</button>
        </div>
      </div>
    `
    const card = document.querySelector('#card') as HTMLElement
    const play = document.querySelector('#play') as HTMLButtonElement
    setRect(card, 20, 80)
    setRect(play, 40, 40)
    card.focus()
    const cardClick = vi.spyOn(card, 'click')
    const playClick = vi.spyOn(play, 'click').mockImplementation(() => {
      window.history.replaceState({}, '', '/watch/immediate')
      document.body.innerHTML = '<video></video>'
      setReadyVideo()
    })
    expect((await runtime().run('OK', null)).status).toBe('playing')
    expect(playClick).toHaveBeenCalledOnce()
    expect(cardClick).not.toHaveBeenCalled()

    document.body.innerHTML =
      '<div class="lolomoRow"><div id="delayed" class="title-card" tabindex="0">Delayed</div></div>'
    const delayed = document.querySelector('#delayed') as HTMLElement
    setRect(delayed, 20, 80)
    delayed.focus()
    let detailPlayClicks = 0
    const delayedClick = vi.spyOn(delayed, 'click').mockImplementation(() => {
      const modal = document.createElement('div')
      modal.className = 'detail-modal'
      const detailPlay = document.createElement('button')
      detailPlay.id = 'detail-play'
      detailPlay.textContent = 'Play'
      vi.spyOn(detailPlay, 'click').mockImplementation(() => {
        detailPlayClicks += 1
        window.history.replaceState({}, '', '/watch/delayed')
        document.body.innerHTML = '<video></video>'
        setReadyVideo()
      })
      modal.append(detailPlay)
      document.body.append(modal)
      setRect(modal, 20, 20, 800, 600)
      setRect(detailPlay, 40, 40)
    })
    const historyPush = vi.spyOn(window.history, 'pushState')
    const delayedResult = await runtime().run('OK', null)
    expect(delayedResult.status).toBe('playing')
    expect(delayedClick).toHaveBeenCalledOnce()
    expect(detailPlayClicks).toBe(1)
    expect(historyPush).not.toHaveBeenCalled()
  })

  it('plays from a current details modal play-button anchor', async () => {
    window.history.replaceState({}, '', '/browse')
    document.body.innerHTML = `
      <div class="lolomoRow">
        <a data-uia="standard-card" href="/title/one" aria-label="陽光女子合唱團"><img alt=""></a>
      </div>
      <div class="previewModal--wrapper detail-modal">
        <h1>陽光女子合唱團</h1>
        <a data-uia="play-button" aria-label="播放" href="/watch/one">播放</a>
      </div>
    `
    const card = document.querySelector('[data-uia="standard-card"]') as HTMLAnchorElement
    const play = document.querySelector('[data-uia="play-button"]') as HTMLAnchorElement
    const modal = document.querySelector('.previewModal--wrapper') as HTMLElement

    setRect(card, 20, 100, 160, 90)
    setRect(card.querySelector('img') as HTMLElement, 20, 100, 160, 90)
    setRect(modal, 0, 0, 800, 600)
    setRect(play, 40, 40, 118, 45)

    card.tabIndex = 0
    card.focus()
    expect(document.activeElement).toBe(card)
    const cardClick = vi.spyOn(card, 'click')
    const playClick = vi.spyOn(play, 'click').mockImplementation(() => {
      window.history.replaceState({}, '', '/watch/one')
      document.body.innerHTML = '<video></video>'
      setReadyVideo()
    })
    const result = await runtime().run('OK', null)
    expect(playClick).toHaveBeenCalledOnce()
    expect(cardClick).not.toHaveBeenCalled()
    expect(result).toMatchObject({
      ok: true,
      status: 'playing',
      context: { stage: 'watch' },
    })
  })

  it('settles OK playback when a ready watch video is covered by player chrome', async () => {
    window.history.replaceState({}, '', '/browse')
    document.body.innerHTML = `
      <div class="lolomoRow">
        <div id="card" class="title-card" tabindex="0">
          陽光女子合唱團 <button id="play">播放</button>
        </div>
      </div>
    `
    const card = document.querySelector('#card') as HTMLElement
    const play = document.querySelector('#play') as HTMLButtonElement
    setRect(card, 20, 80)
    setRect(play, 40, 40)
    card.focus()
    vi.spyOn(play, 'click').mockImplementation(() => {
      window.history.replaceState({}, '', '/watch/one')
      document.body.innerHTML = '<video></video><div id="spinner"></div>'
      const video = document.querySelector('video') as HTMLVideoElement
      const spinner = document.querySelector('#spinner') as HTMLElement
      setRect(video, 0, 0, 640, 360)
      setRect(spinner, 0, 0, 640, 360)
      Object.defineProperty(video, 'readyState', { configurable: true, value: 4 })
      Object.defineProperty(video, 'paused', { configurable: true, value: false })
    })

    const result = await runtime().run('OK', null)

    expect(result).toMatchObject({
      ok: true,
      status: 'playing',
      context: { stage: 'watch' },
    })
  })





  it('direct-play timeout clicks the card once and returns a fixed error', async () => {
    vi.useFakeTimers()
    document.body.innerHTML =
      '<div class="lolomoRow"><div id="card" class="title-card" tabindex="0">No Play</div></div>'
    const card = document.querySelector('#card') as HTMLElement
    setRect(card, 20, 80)
    card.focus()
    const click = vi.spyOn(card, 'click')

    const pending = runtime().run('OK', null)
    await vi.runAllTimersAsync()
    await expect(pending).resolves.toMatchObject({
      ok: false,
      status: 'error',
      code: 'netflix_direct_play_unavailable',
    })
    expect(click).toHaveBeenCalledOnce()
    vi.useRealTimers()
  })

  it('keeps delayed detail play and late watch video inside one 8s budget', async () => {
    vi.useFakeTimers()
    document.body.innerHTML =
      '<div class="lolomoRow"><div id="card" class="title-card" tabindex="0">Selected</div></div>'
    const card = document.querySelector('#card') as HTMLElement
    setRect(card, 20, 80)
    card.focus()
    let detailPlayClicks = 0
    const cardClick = vi.spyOn(card, 'click').mockImplementation(() => {
      setTimeout(() => {
        const modal = document.createElement('div')
        modal.className = 'detail-modal'
        const detailPlay = document.createElement('button')
        detailPlay.id = 'detail-play'
        detailPlay.textContent = 'Play'
        vi.spyOn(detailPlay, 'click').mockImplementation(() => {
          detailPlayClicks += 1
          window.history.replaceState({}, '', '/watch/late')
          document.body.innerHTML = '<video></video>'
          const video = document.querySelector('video') as HTMLVideoElement
          setRect(video, 20, 20, 640, 360)
          Object.defineProperty(video, 'readyState', { configurable: true, value: 1 })
          Object.defineProperty(video, 'paused', { configurable: true, value: true })
          setTimeout(() => {
            Object.defineProperty(video, 'readyState', { configurable: true, value: 2 })
            Object.defineProperty(video, 'paused', { configurable: true, value: false })
          }, 5700)
        })
        modal.append(detailPlay)
        document.body.append(modal)
        setRect(modal, 20, 20, 800, 600)
        setRect(detailPlay, 40, 40)
      }, 2000)
    })

    let settled = false
    const pending = runtime().run('OK', null).then((result) => {
      settled = true
      return result
    })
    await vi.advanceTimersByTimeAsync(7690)
    expect(settled).toBe(false)
    await vi.advanceTimersByTimeAsync(200)
    const result = await pending
    vi.useRealTimers()

    expect(cardClick).toHaveBeenCalledOnce()
    expect(detailPlayClicks).toBe(1)
    expect(result).toMatchObject({
      ok: true,
      status: 'playing',
      context: { stage: 'watch' },
    })
  })

  it('returns a fixed direct-play error before the backend CDP timeout after delayed detail play', async () => {
    vi.useFakeTimers()
    document.body.innerHTML =
      '<div class="lolomoRow"><div id="card" class="title-card" tabindex="0">Selected</div></div>'
    const card = document.querySelector('#card') as HTMLElement
    setRect(card, 20, 80)
    card.focus()
    let detailPlayClicks = 0
    const cardClick = vi.spyOn(card, 'click').mockImplementation(() => {
      setTimeout(() => {
        const modal = document.createElement('div')
        modal.className = 'detail-modal'
        const detailPlay = document.createElement('button')
        detailPlay.id = 'detail-play'
        detailPlay.textContent = 'Play'
        vi.spyOn(detailPlay, 'click').mockImplementation(() => {
          detailPlayClicks += 1
          window.history.replaceState({}, '', '/watch/never-ready')
          document.body.innerHTML = '<video></video>'
          const video = document.querySelector('video') as HTMLVideoElement
          setRect(video, 20, 20, 640, 360)
          Object.defineProperty(video, 'readyState', { configurable: true, value: 1 })
          Object.defineProperty(video, 'paused', { configurable: true, value: true })
        })
        modal.append(detailPlay)
        document.body.append(modal)
        setRect(modal, 20, 20, 800, 600)
        setRect(detailPlay, 40, 40)
      }, 2000)
    })

    let settled = false
    const pending = runtime().run('OK', null).then((result) => {
      settled = true
      return result
    })
    await vi.advanceTimersByTimeAsync(8010)
    expect(settled).toBe(true)
    const result = await pending
    vi.useRealTimers()

    expect(result).toMatchObject({
      ok: false,
      status: 'error',
      code: 'netflix_direct_play_unavailable',
    })
    expect(cardClick).toHaveBeenCalledOnce()
    expect(detailPlayClicks).toBeLessThanOrEqual(1)
    expect(detailPlayClicks).toBe(1)
  })

  it('exposes only the fixed global version and run interface and re-enumerates every run', async () => { expect(runtime().version).toBe('4')

  expect(Object.keys(runtime()).sort()).toEqual(['run', 'version'])
  document.body.innerHTML = '<button id="first">First</button>'
  const first = document.querySelector('#first') as HTMLButtonElement
  setRect(first, 20, 20)
  expect((await runtime().run('FOCUS_PRIMARY', null)).focus?.text).toBe('First')
  document.body.innerHTML = '<button id="replacement">Replacement</button>'
  const replacement = document.querySelector('#replacement') as HTMLButtonElement
  setRect(replacement, 20, 20)
  expect(await runtime().run('FOCUS_PRIMARY', null)).toMatchObject({
    ok: true,
    status: 'focused',
    focus: { text: 'Replacement' },
  })
  expect(document.activeElement).toBe(replacement)
  expect(await runtime().run('NOT_AN_ACTION', null)).toEqual({
    ok: false,
    status: 'error',
    code: 'netflix_focus_unavailable',
  }) })

  it('moves right by rectangles and keeps focus at the boundary', async () => { document.body.innerHTML = '<button id="a">A</button><button id="b">B</button><button id="c">C</button>'
  const [a, b, c] = [...document.querySelectorAll('button')]
  setRect(a, 0, 0)
  setRect(b, 180, 0)
  setRect(c, 180, 140)
  ;(a as HTMLElement).focus()
  expect((await runtime().run('NAV_RIGHT', null)).status).toBe('moved')
  expect(document.activeElement).toBe(b)
  expect((await runtime().run('NAV_RIGHT', null)).status).toBe('boundary')
  expect(document.activeElement).toBe(b) })

  it('moves in all four directions from the current rectangle', async () => { document.body.innerHTML = `
    <button id="center">Center</button><button id="up">Up</button>
    <button id="down">Down</button><button id="left">Left</button><button id="right">Right</button>
  `
  const center = document.querySelector('#center') as HTMLButtonElement
  const targets = {
    NAV_UP: document.querySelector('#up') as HTMLButtonElement,
    NAV_DOWN: document.querySelector('#down') as HTMLButtonElement,
    NAV_LEFT: document.querySelector('#left') as HTMLButtonElement,
    NAV_RIGHT: document.querySelector('#right') as HTMLButtonElement,
  }
  setRect(center, 300, 300, 100, 100)
  setRect(targets.NAV_UP, 300, 100, 100, 100)
  setRect(targets.NAV_DOWN, 300, 500, 100, 100)
  setRect(targets.NAV_LEFT, 100, 300, 100, 100)
  setRect(targets.NAV_RIGHT, 500, 300, 100, 100)
  for (const [action, target] of Object.entries(targets)) {
    center.focus()
    expect((await runtime().run(action, null)).status).toBe('moved')
    expect(document.activeElement).toBe(target)
  } })

  it('filters hidden disabled zero-area offscreen and covered candidates', async () => { document.body.innerHTML = `
    <button id="source">Source</button><button id="hidden" hidden>Hidden</button>
    <button id="disabled" disabled>Disabled</button><button id="zero">Zero</button>
    <button id="offscreen">Offscreen</button><button id="covered">Covered</button>
    <button id="valid">Valid</button><div id="cover"></div>
  `
  const source = document.querySelector('#source') as HTMLButtonElement
  setRect(source, 10, 100)
  setRect(document.querySelector('#hidden')!, 160, 100)
  setRect(document.querySelector('#disabled')!, 280, 100)
  setRect(document.querySelector('#zero')!, 400, 100, 0, 0)
  setRect(document.querySelector('#offscreen')!, 1400, 100)
  setRect(document.querySelector('#covered')!, 520, 100)
  setRect(document.querySelector('#valid')!, 760, 100)
  setRect(document.querySelector('#cover')!, 520, 100)
  source.focus()
  expect((await runtime().run('NAV_RIGHT', null)).status).toBe('moved')
  expect(document.activeElement).toBe(document.querySelector('#valid')) })

  it('excludes structural data-uia containers and focuses their child control', async () => { document.body.innerHTML = `
    <div id="modal" data-uia="modal-dialog">
      <button id="continue">Continue</button>
    </div>
  `
  const modal = document.querySelector('#modal') as HTMLElement
  const child = document.querySelector('#continue') as HTMLButtonElement
  setRect(modal, 20, 20, 800, 500)
  setRect(child, 80, 80)
  expect(await runtime().run('FOCUS_PRIMARY', null)).toMatchObject({
    ok: true,
    status: 'focused',
    focus: { text: 'Continue' },
  })
  expect(document.activeElement).toBe(child) })

  it('programmatically focuses and clicks actionable non-native data-uia cards', async () => { document.body.innerHTML = '<div id="card" data-uia="title-card">Title</div>'
  const card = document.querySelector('#card') as HTMLElement
  setRect(card, 20, 20)
  expect(await runtime().run('FOCUS_PRIMARY', null)).toMatchObject({
    ok: true,
    status: 'focused',
    focus: { uia: 'title-card', text: 'Title' },
  })
  expect(card.tabIndex).toBe(-1)
  expect(document.activeElement).toBe(card)
})

  it('prefers axis overlap then primary distance then perpendicular distance then DOM order', async () => { document.body.innerHTML = '<button id="source">S</button><button id="near">Near</button><button id="overlap">Overlap</button>'
  let source = document.querySelector('#source') as HTMLButtonElement
  setRect(source, 0, 100, 100, 100)
  setRect(document.querySelector('#near')!, 130, 260, 100, 100)
  setRect(document.querySelector('#overlap')!, 500, 120, 100, 100)
  source.focus()
  await runtime().run('NAV_RIGHT', null)
  expect(document.activeElement).toBe(document.querySelector('#overlap'))
  document.body.innerHTML = '<button id="source">S</button><button id="primary">Primary</button><button id="perpendicular">Perpendicular</button>'
  source = document.querySelector('#source') as HTMLButtonElement
  setRect(source, 0, 0, 100, 100)
  setRect(document.querySelector('#primary')!, 150, 300, 100, 100)
  setRect(document.querySelector('#perpendicular')!, 250, 120, 100, 100)
  source.focus()
  await runtime().run('NAV_RIGHT', null)
  expect(document.activeElement).toBe(document.querySelector('#primary'))
  document.body.innerHTML = '<button id="source">S</button><button id="first">First</button><button id="second">Second</button>'
  source = document.querySelector('#source') as HTMLButtonElement
  setRect(source, 0, 0, 100, 100)
  setRect(document.querySelector('#first')!, 200, 0, 100, 80)
  setRect(document.querySelector('#second')!, 200, 220, 100, 80)
  source.focus()
  await runtime().run('NAV_RIGHT', null)
  expect(document.activeElement).toBe(document.querySelector('#first')) })

  it('restores a rebuilt card by role label data-uia path rail and index', async () => { document.body.innerHTML = `
    <section data-rail-title="Trending">
      <a role="button" aria-label="Play Alpha" data-uia="title-card" href="/title/101">Alpha</a>
      <a role="button" aria-label="Play Beta" data-uia="title-card" href="/title/202">Beta</a>
    </section>
  `
  setSequentialRects()
  const previous = (await runtime().run('FOCUS_PRIMARY', null)).focus!
  expect(Object.keys(previous).sort()).toEqual([
    'index', 'label', 'pathKind', 'rail', 'role', 'text', 'uia',
  ])
  expect(previous).toEqual({
    role: 'button',
    label: 'Play Alpha',
    uia: 'title-card',
    text: 'Alpha',
    pathKind: 'title',
    rail: 'Trending',
    index: 0,
  })
  document.body.innerHTML = `
    <section data-rail-title="Other"><a role="button" aria-label="Other" data-uia="promo" href="/browse">Other</a></section>
    <section data-rail-title="Trending"><a role="button" aria-label="Play Alpha" data-uia="title-card" href="/title/999">Alpha</a></section>
  `
  setSequentialRects()
  const result = await runtime().run('FOCUS_PRIMARY', previous)
  expect(result.status).toBe('restored')
  expect(document.activeElement?.getAttribute('aria-label')).toBe('Play Alpha') })

  it('falls back to the page primary action when the previous semantic target disappeared', async () => { const missing: FocusFingerprint = {
    role: 'button',
    label: 'Missing title',
    uia: 'missing-card',
    text: 'Missing',
    pathKind: 'title',
    rail: 'Gone',
    index: 9,
  }
  const fixtures = [
    {
      html: '<button data-uia="login-submit">Submit</button><input id="login" data-uia="login-field" aria-label="Email">',
      expected: '#login',
    },
    {
      html: '<button id="settings">Settings</button><button id="profile" data-uia="profile-link">Profile</button>',
      expected: '#profile',
    },
    {
      html: '<a id="card" data-uia="title-card" href="/title/1">Card</a><a id="nav" data-uia="navigation-menu-home" href="/browse">Home</a>',
      expected: '#card',
    },
    {
      html: '<div role="dialog" data-uia="detail-modal"><button id="secondary">More</button><button id="play" data-uia="play-button">Play</button></div>',
      expected: '#play',
    },
    {
      html: '<video id="movie"></video><button id="player" data-uia="control-play-pause">Pause</button>',
      expected: '#player',
    },
  ]
  for (const fixture of fixtures) {
    document.body.innerHTML = fixture.html
    setSequentialRects()
    document.querySelectorAll('[role="dialog"],[data-uia*="modal"]').forEach((overlay) => {
      setRect(overlay, 20, 20, 900, 600)
    })
    expect((await runtime().run('FOCUS_PRIMARY', missing)).status).toBe('focused')
    expect(document.activeElement).toBe(document.querySelector(fixture.expected))
  } })

  it('refocuses the login field at an explicit recovery entry point', async () => { document.body.innerHTML = `
    <input id="email" aria-label="Email"><input id="password" aria-label="Password" aria-invalid="true" aria-describedby="password-error">
    <button id="submit">Sign in</button><div id="password-error" role="alert" data-for="password">Incorrect password</div>
  `
  setSequentialRects('input,button,[role="alert"]')
  expect(await runtime().run('FOCUS_PRIMARY', null)).toMatchObject({
    ok: true,
    status: 'error_refocused',
    focus: { label: 'Password' },
  })
  expect(document.activeElement).toBe(document.querySelector('#password')) })

  it('allows error field navigation to submit and OK without forced refocus', async () => { document.body.innerHTML = `
    <input id="password" aria-label="Password" aria-invalid="true" aria-describedby="password-error">
    <button id="submit">Sign in</button><div id="password-error" role="alert" data-for="password">Incorrect password</div>
  `
  const password = document.querySelector('#password') as HTMLInputElement
  const submit = document.querySelector('#submit') as HTMLButtonElement
  setRect(password, 20, 20)
  setRect(submit, 220, 20)
  setRect(document.querySelector('#password-error')!, 20, 120)
  const click = vi.spyOn(submit, 'click')
  password.focus()
  expect((await runtime().run('NAV_RIGHT', null)).status).toBe('moved')
  expect(document.activeElement).toBe(submit)
  expect((await runtime().run('OK', null)).status).toBe('clicked')
  expect(click).toHaveBeenCalledOnce() })

  it('skips language selects when focusing the Netflix login text field', async () => { document.body.innerHTML = `
    <select id="language" data-uia="language-picker-header"><option>中文</option></select>
    <input id="email" type="email" aria-label="Email" data-uia="field-email">
    <button data-uia="nmhp-card-cta+hero_card">Start</button>
  `
  const language = document.querySelector('#language') as HTMLSelectElement
  const email = document.querySelector('#email') as HTMLInputElement
  setRect(language, 20, 20)
  setRect(email, 180, 20)
  setRect(document.querySelector('button')!, 340, 20)
  expect(await runtime().run('FOCUS_PRIMARY', null)).toMatchObject({
    ok: true,
    status: 'focused',
    focus: { role: 'textbox', uia: 'field-email' },
  })
  expect(document.activeElement).toBe(email)
  document.body.focus()
  expect((await runtime().run('FOCUS_EDITABLE', null)).focus).toMatchObject({
    role: 'textbox',
    uia: 'field-email',
  })
  expect(document.activeElement).toBe(email) })

  it('focuses editable fields without reading value', async () => { document.body.innerHTML = '<input id="secret" aria-label="Password" data-uia="password-field" type="password">'
  const input = document.querySelector('#secret') as HTMLInputElement
  setRect(input, 20, 20)
  const valueRead = vi.fn(() => 'never-read-this')
  Object.defineProperty(input, 'value', { configurable: true, get: valueRead })
  const result = await runtime().run('FOCUS_EDITABLE', null)
  expect(result).toMatchObject({
    ok: true,
    status: 'focused',
    focus: { role: 'textbox', label: 'Password', text: '' },
  })
  expect(valueRead).not.toHaveBeenCalled()
  expect(result.focus).not.toHaveProperty('value')
  expect(document.activeElement).toBe(input) })

  it('does not read or expose text from contenteditable and role textboxes', async () => { const fixtures = [
    '<div id="editable" contenteditable="true" aria-label="Message">contenteditable secret</div>',
    '<div id="editable" role="textbox" aria-label="Code">role textbox secret</div>',
  ]
  for (const html of fixtures) {
    document.body.innerHTML = html
    const field = document.querySelector('#editable') as HTMLElement
    setRect(field, 20, 20)
    const textRead = vi.fn(() => 'must-not-leak')
    Object.defineProperty(field, 'textContent', { configurable: true, get: textRead })
    const result = await runtime().run('FOCUS_EDITABLE', null)
    expect(result).toMatchObject({ ok: true, status: 'focused', focus: { text: '' } })
    expect(result.focus).not.toHaveProperty('value')
    expect(textRead).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(field)
  } })

  it('clicks generic buttons but only focuses input on OK', async () => { document.body.innerHTML = '<button id="card" data-uia="action-button">Card</button><input id="search" aria-label="Search">'
  const card = document.querySelector('#card') as HTMLButtonElement
  const input = document.querySelector('#search') as HTMLInputElement
  setRect(card, 20, 20)
  setRect(input, 200, 20)
  const cardClick = vi.spyOn(card, 'click')
  const inputClick = vi.spyOn(input, 'click')
  card.focus()
  expect((await runtime().run('OK', null)).status).toBe('clicked')
  expect(cardClick).toHaveBeenCalledOnce()
  input.focus()
  expect((await runtime().run('OK', null)).status).toBe('focused')
  expect(inputClick).not.toHaveBeenCalled()
  expect(document.activeElement).toBe(input) })

  it('closes the top dialog or detail layer before history back', async () => { document.body.innerHTML = `
    <div role="dialog" id="lower"><button aria-label="Close">Lower close</button></div>
    <div data-uia="detail-modal" id="top"><button id="top-close" data-uia="close-button">Top close</button></div>
  `
  const lower = document.querySelector('#lower') as HTMLElement
  const top = document.querySelector('#top') as HTMLElement
  const topClose = document.querySelector('#top-close') as HTMLButtonElement
  setRect(lower, 50, 50, 500, 400)
  setRect(lower.querySelector('button')!, 80, 80)
  setRect(top, 100, 100, 500, 400)
  setRect(topClose, 140, 140)
  const closeClick = vi.spyOn(topClose, 'click').mockImplementation(() => {
    top.remove()
  })
  const historyBack = vi.spyOn(window.history, 'back').mockImplementation(() => {
    window.history.replaceState({}, '', '/browse')
  })
  expect((await runtime().run('BACK', null)).status).toBe('closed')
  expect(closeClick).toHaveBeenCalledOnce()
  expect(historyBack).not.toHaveBeenCalled()
  lower.remove()
  top.remove()
  expect((await runtime().run('BACK', null)).status).toBe('history')
  expect(historyBack).toHaveBeenCalledOnce() })

  it('toggles only the visible video in the current document', async () => { document.body.innerHTML = '<video id="hidden"></video><video id="visible"></video>'
  const hidden = document.querySelector('#hidden') as HTMLVideoElement
  const video = document.querySelector('#visible') as HTMLVideoElement
  setRect(hidden, 20, 20, 0, 0)
  setRect(video, 200, 100, 640, 360)
  let paused = true
  Object.defineProperty(video, 'paused', { configurable: true, get: () => paused })
  Object.defineProperty(video, 'readyState', { configurable: true, value: 2 })
  const play = vi.spyOn(video, 'play').mockResolvedValue(undefined)
  const pause = vi.spyOn(video, 'pause').mockImplementation(() => undefined)
  const hiddenPlay = vi.spyOn(hidden, 'play').mockResolvedValue(undefined)
  expect((await runtime().run('PLAY_PAUSE', null)).status).toBe('playing')
  expect(play).toHaveBeenCalledOnce()
  expect(hiddenPlay).not.toHaveBeenCalled()
  paused = false
  expect((await runtime().run('PLAY_PAUSE', null)).status).toBe('paused')
  expect(pause).toHaveBeenCalledOnce() })

  it('returns stable focus input and video error codes', async () => { expect(await runtime().run('FOCUS_PRIMARY', null)).toEqual({
    ok: false,
    status: 'error',
    code: 'netflix_focus_unavailable',
  })
  document.body.innerHTML = '<button>Only button</button>'
  setSequentialRects()
  expect(await runtime().run('FOCUS_EDITABLE', null)).toEqual({
    ok: false,
    status: 'error',
    code: 'netflix_input_unavailable',
  })
  expect(await runtime().run('PLAY_PAUSE', null)).toEqual({
    ok: false,
    status: 'error',
    code: 'netflix_video_unavailable',
  }) })

  it('supports focus next without retaining stale element references', async () => { document.body.innerHTML = '<button id="first">First</button><button id="second">Second</button>'
  setSequentialRects()
  const first = document.querySelector('#first') as HTMLButtonElement
  first.focus()
  expect((await runtime().run('FOCUS_NEXT', null)).status).toBe('moved')
  expect(document.activeElement).toBe(document.querySelector('#second'))
  document.querySelector('#second')?.remove()
  expect((await runtime().run('FOCUS_NEXT', null)).status).toBe('focused')
  expect(document.activeElement).toBe(first) })

  it('adds white outline red glow and center-center scrollIntoView', async () => { document.body.innerHTML = '<button id="target">Target</button>'
  const button = document.querySelector('#target') as HTMLButtonElement
  setRect(button, 20, 20)
  const scrollIntoView = vi.fn()
  Object.defineProperty(button, 'scrollIntoView', { configurable: true, value: scrollIntoView })
  expect((await runtime().run('FOCUS_PRIMARY', null)).ok).toBe(true)
  expect(button.style.outline).toContain('3px solid')
  expect(button.style.outline).toMatch(/#fff|rgb\(255, 255, 255\)/)
  expect(button.style.boxShadow).toMatch(/rgba\(229,\s*9,\s*20,\s*(?:0?\.95)\)/)
  expect(scrollIntoView).toHaveBeenCalledWith({ block: 'center', inline: 'center' }) })

  it('submits one primary action and returns context after bounded settle', async () => {
    document.body.innerHTML =
      '<form><input type="password"><button id="submit">Sign in</button></form>'
    const input = document.querySelector('input') as HTMLInputElement
    const submit = document.querySelector('#submit') as HTMLButtonElement
    setRect(input, 20, 20)
    setRect(submit, 180, 20)
    const click = vi.spyOn(submit, 'click').mockImplementation(() => {
      document.body.innerHTML =
        '<div class="lolomoRow"><div class="title-card" tabindex="0">Browse</div></div>'
      setRect(document.querySelector('.title-card')!, 20, 80)
    })

    const result = await runtime().run('SUBMIT_PRIMARY', null)

    expect(click).toHaveBeenCalledOnce()
    expect(result).toMatchObject({
      ok: true,
      status: 'submitted',
      context: { stage: 'browse', input_kind: 'none' },
    })
  })

  it('requires a ready video and uses history back from watch', async () => {
    window.history.replaceState({}, '', '/watch/123')
    document.body.innerHTML = '<video></video>'

    const video = document.querySelector('video') as HTMLVideoElement
    setRect(video, 20, 20, 640, 360)
    Object.defineProperty(video, 'paused', { configurable: true, value: true })
    Object.defineProperty(video, 'readyState', { configurable: true, value: 1 })
    expect(await runtime().run('PLAY_PAUSE', null)).toMatchObject({
      ok: false,
      code: 'netflix_video_unavailable',
    })

    Object.defineProperty(video, 'readyState', { configurable: true, value: 2 })
    const play = vi.spyOn(video, 'play').mockResolvedValue(undefined)
    expect((await runtime().run('PLAY_PAUSE', null)).status).toBe('playing')
    expect(play).toHaveBeenCalledOnce()

    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {
      window.history.replaceState({}, '', '/browse')
      document.body.innerHTML =
        '<div class="lolomoRow"><div class="title-card" tabindex="0">Browse</div></div>'
      setRect(document.querySelector('.title-card')!, 20, 80)
    })
    expect((await runtime().run('BACK', null)).status).toBe('history')
    expect(back).toHaveBeenCalledOnce()
  })
  it('returns fixed errors without repeating route-changing clicks on timeout', async () => {
    vi.useFakeTimers()
    document.body.innerHTML =
      '<form><input type="email"><button id="submit">開始使用</button></form>'
    const email = document.querySelector('input') as HTMLInputElement
    const submit = document.querySelector('#submit') as HTMLButtonElement
    setRect(email, 20, 20)
    setRect(submit, 180, 20)
    email.focus()
    const submitClick = vi.spyOn(submit, 'click').mockImplementation(() => undefined)
    const submitPending = runtime().run('SUBMIT_PRIMARY', null)
    await vi.runAllTimersAsync()
    await expect(submitPending).resolves.toMatchObject({
      ok: false,
      code: 'netflix_submit_unavailable',
    })
    expect(submitClick).toHaveBeenCalledOnce()

    window.history.replaceState({}, '', '/watch/timeout')
    document.body.innerHTML =
      '<button data-uia="player-back-to-browsing">Back</button>'
    const back = document.querySelector('button') as HTMLButtonElement
    setRect(back, 20, 20)
    const backClick = vi.spyOn(back, 'click')
    const backPending = runtime().run('BACK', null)
    await vi.runAllTimersAsync()
    await expect(backPending).resolves.toMatchObject({
      ok: false,
      code: 'netflix_back_unavailable',
    })
    expect(backClick).toHaveBeenCalledOnce()
    vi.useRealTimers()
  })

  it('scopes submit to the active login form and supports zh-TW start copy', async () => {
    vi.useFakeTimers()
    document.body.innerHTML = `
      <header><button id="header-login">登入</button></header>
      <main class="login-panel">
        <form id="landing-form">
          <input id="email" type="email">
          <button id="start">開始使用</button>
        </form>
      </main>
    `
    const headerLogin = document.querySelector('#header-login') as HTMLButtonElement
    const email = document.querySelector('#email') as HTMLInputElement
    const start = document.querySelector('#start') as HTMLButtonElement
    setRect(headerLogin, 20, 20)
    setRect(email, 20, 100)
    setRect(start, 180, 100)
    email.focus()
    const headerClick = vi.spyOn(headerLogin, 'click')
    const startClick = vi.spyOn(start, 'click').mockImplementation(() => {
      setTimeout(() => {
        const loading = document.createElement('div')
        loading.className = 'detail-modal'
        loading.id = 'loading'
        document.body.append(loading)
        setRect(loading, 20, 20, 800, 600)
      }, 20)
      setTimeout(() => {
        document.body.innerHTML =
          '<div class="lolomoRow"><div class="title-card" tabindex="0">Browse</div></div>'
        setRect(document.querySelector('.title-card')!, 20, 80)
      }, 80)
    })

    let settled = false
    const pending = runtime().run('SUBMIT_PRIMARY', null).then((result) => {
      settled = true
      return result
    })
    await vi.advanceTimersByTimeAsync(30)
    expect(settled).toBe(false)
    await vi.runAllTimersAsync()
    const result = await pending
    vi.useRealTimers()

    expect(headerClick).not.toHaveBeenCalled()
    expect(startClick).toHaveBeenCalledOnce()
    expect(result.context).toMatchObject({ stage: 'browse', input_kind: 'none' })
  })

  it('waits for the watch transition after a card-contained Play click', async () => {
    vi.useFakeTimers()
    document.body.innerHTML = `
      <div class="lolomoRow">
        <div class="title-card" tabindex="0">
          Example <button id="play">Play</button>
        </div>
      </div>
    `
    const card = document.querySelector('.title-card') as HTMLElement
    const play = document.querySelector('#play') as HTMLButtonElement
    setRect(card, 20, 80)
    setRect(play, 40, 90)
    card.focus()
    const click = vi.spyOn(play, 'click').mockImplementation(() => {
      setTimeout(() => {
        const loading = document.createElement('div')
        loading.className = 'detail-modal'
        loading.id = 'loading'
        document.body.append(loading)
        setRect(loading, 20, 20, 800, 600)
      }, 20)
      setTimeout(() => {
        window.history.replaceState({}, '', '/watch/next')
        document.body.innerHTML = '<video></video>'
        setReadyVideo()
      }, 80)
    })

    let settled = false
    const pending = runtime().run('OK', null).then((result) => {
      settled = true
      return result
    })
    await vi.advanceTimersByTimeAsync(30)
    expect(settled).toBe(false)
    await vi.runAllTimersAsync()
    const result = await pending
    vi.useRealTimers()

    expect(click).toHaveBeenCalledOnce()
    expect(result).toMatchObject({
      ok: true,
      status: 'playing',
      context: { stage: 'watch', focused_title: null },
    })
  })

  it('waits for browse context after the player back control click', async () => {
    vi.useFakeTimers()
    window.history.replaceState({}, '', '/watch/current')
    document.body.innerHTML =
      '<button data-uia="player-back-to-browsing">Back to browsing</button>'
    const back = document.querySelector('button') as HTMLButtonElement
    setRect(back, 20, 20)
    const click = vi.spyOn(back, 'click').mockImplementation(() => {
      setTimeout(() => {
        const loading = document.createElement('div')
        loading.className = 'detail-modal'
        loading.id = 'loading'
        document.body.append(loading)
        setRect(loading, 20, 20, 800, 600)
      }, 20)
      setTimeout(() => {
        window.history.replaceState({}, '', '/browse')
        document.body.innerHTML =
          '<div class="lolomoRow"><div class="title-card" tabindex="0">Browse</div></div>'
        setRect(document.querySelector('.title-card')!, 20, 80)
      }, 80)
    })

    let settled = false
    const pending = runtime().run('BACK', null).then((result) => {
      settled = true
      return result
    })
    await vi.advanceTimersByTimeAsync(30)
    expect(settled).toBe(false)
    await vi.runAllTimersAsync()
    const result = await pending
    vi.useRealTimers()

    expect(click).toHaveBeenCalledOnce()
    expect(result).toMatchObject({
      ok: true,
      status: 'history',
      context: { stage: 'browse' },
    })
  })

  it('requests fullscreen once on a visible ready Netflix video', async () => {
    window.history.replaceState({}, '', '/watch/fullscreen')
    document.body.innerHTML = '<video></video>'
    const video = document.querySelector('video') as HTMLVideoElement
    setRect(video, 20, 20, 640, 360)
    Object.defineProperty(video, 'readyState', { configurable: true, value: 2 })
    const requestFullscreen = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(video, 'requestFullscreen', {
      configurable: true,
      value: requestFullscreen,
    })

    const result = await runtime().run('FULLSCREEN', null)

    expect(requestFullscreen).toHaveBeenCalledOnce()
    expect(result).toMatchObject({
      ok: true,
      status: 'fullscreen',
      context: { stage: 'watch' },
    })
  })

  it('requests fullscreen on a ready watch video even when player chrome covers it', async () => {
    window.history.replaceState({}, '', '/watch/covered')
    document.body.innerHTML = '<video></video><div id="cover"></div>'
    const video = document.querySelector('video') as HTMLVideoElement
    const cover = document.querySelector('#cover') as HTMLElement
    setRect(video, 0, 0, 640, 360)
    setRect(cover, 0, 0, 640, 360)
    Object.defineProperty(video, 'readyState', { configurable: true, value: 4 })
    const requestFullscreen = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(video, 'requestFullscreen', {
      configurable: true,
      value: requestFullscreen,
    })

    const result = await runtime().run('FULLSCREEN', null)

    expect(requestFullscreen).toHaveBeenCalledOnce()
    expect(result).toMatchObject({ ok: true, status: 'fullscreen' })
  })


  it('falls back to the visible Netflix player container for fullscreen', async () => {
    document.body.innerHTML = '<div id="movie_player"></div>'
    const player = document.querySelector('#movie_player') as HTMLElement
    setRect(player, 20, 20, 640, 360)
    const requestFullscreen = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(player, 'requestFullscreen', {
      configurable: true,
      value: requestFullscreen,
    })

    const result = await runtime().run('FULLSCREEN', null)

    expect(requestFullscreen).toHaveBeenCalledOnce()
    expect(result).toMatchObject({ ok: true, status: 'fullscreen' })
  })

  it('returns a fixed fullscreen error when no visible target is ready', async () => {
    document.body.innerHTML = '<video></video>'
    const video = document.querySelector('video') as HTMLVideoElement
    setRect(video, 20, 20, 640, 360)
    Object.defineProperty(video, 'readyState', { configurable: true, value: 1 })
    const requestFullscreen = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(video, 'requestFullscreen', {
      configurable: true,
      value: requestFullscreen,
    })

    const result = await runtime().run('FULLSCREEN', null)

    expect(result).toEqual({
      ok: false,
      status: 'error',
      code: 'netflix_fullscreen_unavailable',
    })
    expect(requestFullscreen).not.toHaveBeenCalled()
  })

  it('deduplicates nested cards and advances through five logical cards in order', async () => {
    document.body.innerHTML = `
      <div class="lolomoRow">
        ${[1, 2, 3, 4, 5]
          .map(
            (index) =>
              `<div class="title-card" tabindex="0" data-index="${index}"><div class="slider-item" tabindex="0">${index}</div></div>`,
          )
          .join('')}
      </div>
    `
    const cards = [...document.querySelectorAll('.title-card')]
    const nested = [...document.querySelectorAll('.slider-item')]
    cards.forEach((card, index) => setRect(card, index * 180, 80))
    nested.forEach((card, index) => setRect(card, index * 180 + 10, 80))
    ;(nested[0] as HTMLElement).focus()

    for (const expected of [2, 3, 4, 5]) {
      await runtime().run('NAV_RIGHT', null)
      expect(document.activeElement?.textContent?.trim()).toBe(String(expected))
    }
  })

  it('autoplays the ready watch video before direct-play success', async () => {
    vi.useFakeTimers()
    document.body.innerHTML = `
      <div class="lolomoRow">
        <div class="title-card" tabindex="0">Example <button>Play</button></div>
      </div>
    `
    const card = document.querySelector('.title-card') as HTMLElement
    const button = document.querySelector('button') as HTMLButtonElement
    setRect(card, 20, 80)
    setRect(button, 40, 90)
    card.focus()
    let paused = true
    let playCalls = 0
    const click = vi.spyOn(button, 'click').mockImplementation(() => {
      setTimeout(() => {
        window.history.replaceState({}, '', '/watch/autoplay')
        document.body.innerHTML = '<video></video>'
        const video = document.querySelector('video') as HTMLVideoElement
        setRect(video, 20, 20, 640, 360)
        Object.defineProperty(video, 'readyState', { configurable: true, value: 2 })
        Object.defineProperty(video, 'paused', {
          configurable: true,
          get: () => paused,
        })
        const playVideo = async () => {
          playCalls += 1
          paused = false
        }
        Object.defineProperty(video, 'play', {
          configurable: true,
          value: playVideo,
        })
      }, 20)
    })

    const pending = runtime().run('OK', null)
    await vi.runAllTimersAsync()
    const result = await pending
    vi.useRealTimers()

    expect(click).toHaveBeenCalledOnce()
    expect(playCalls).toBe(1)
    expect(result).toMatchObject({
      ok: true,
      status: 'playing',
      context: { stage: 'watch' },
    })
  })

  it('fails direct play when the routed ready video remains paused', async () => {
    vi.useFakeTimers()
    document.body.innerHTML = `
      <div class="lolomoRow">
        <div class="title-card" tabindex="0">Example <button>Play</button></div>
      </div>
    `
    const card = document.querySelector('.title-card') as HTMLElement
    const button = document.querySelector('button') as HTMLButtonElement
    setRect(card, 20, 80)
    setRect(button, 40, 90)
    card.focus()
    const play = vi.fn().mockResolvedValue(undefined)
    const click = vi.spyOn(button, 'click').mockImplementation(() => {
      setTimeout(() => {
        window.history.replaceState({}, '', '/watch/still-paused')
        document.body.innerHTML = '<video></video>'
        const video = document.querySelector('video') as HTMLVideoElement
        setRect(video, 20, 20, 640, 360)
        Object.defineProperty(video, 'readyState', { configurable: true, value: 2 })
        Object.defineProperty(video, 'paused', { configurable: true, value: true })
        Object.defineProperty(video, 'play', { configurable: true, value: play })
      }, 20)
    })

    const pending = runtime().run('OK', null)
    await vi.runAllTimersAsync()
    const result = await pending
    vi.useRealTimers()

    expect(result).toEqual({
      ok: false,
      status: 'error',
      code: 'netflix_direct_play_unavailable',
    })
    expect(click).toHaveBeenCalledOnce()
    expect(play).toHaveBeenCalledOnce()
  })

  it('keeps class-only card wrappers out of the focus representatives', async () => {
    document.body.innerHTML = `
      <div class="lolomoRow">
        ${[1, 2, 3, 4, 5]
          .map(
            (index) =>
              `<div class="title-card"><button class="slider-item">${index}</button></div>`,
          )
          .join('')}
      </div>
    `
    const wrappers = [...document.querySelectorAll('.title-card')]
    const buttons = [...document.querySelectorAll('button')]
    wrappers.forEach((card, index) => setRect(card, index * 180, 80))
    buttons.forEach((card, index) => setRect(card, index * 180 + 10, 80))
    ;(buttons[0] as HTMLElement).focus()

    for (const expected of [2, 3, 4, 5]) {
      await runtime().run('NAV_RIGHT', null)
      expect(document.activeElement).toBe(buttons[expected - 1])
    }
  })

  it('does not click stale overlay Play before the selected details update', async () => {
    vi.useFakeTimers()
    document.body.innerHTML = `
      <div class="lolomoRow"><div class="title-card" tabindex="0">Selected</div></div>
      <div class="detail-modal" id="details"><button id="old-play">Play</button></div>
    `
    const card = document.querySelector('.title-card') as HTMLElement
    const overlay = document.querySelector('#details') as HTMLElement
    const oldPlay = document.querySelector('#old-play') as HTMLButtonElement
    setRect(card, 20, 80)
    setRect(overlay, 400, 20, 400, 600)
    setRect(oldPlay, 420, 40)
    card.focus()
    const oldClick = vi.spyOn(oldPlay, 'click')
    let selectedPlayClicks = 0
    vi.spyOn(card, 'click').mockImplementation(() => {
      setTimeout(() => {
        overlay.innerHTML = '<button id="selected-play">Play</button>'
        const selectedPlay = document.querySelector('#selected-play') as HTMLButtonElement
        setRect(selectedPlay, 420, 40)
        vi.spyOn(selectedPlay, 'click').mockImplementation(() => {
          selectedPlayClicks += 1
          window.history.replaceState({}, '', '/watch/selected')
          document.body.innerHTML = '<video></video>'
          setReadyVideo()
        })
      }, 80)
    })

    let settled = false
    const pending = runtime().run('OK', null).then((result) => {
      settled = true
      return result
    })
    await vi.advanceTimersByTimeAsync(30)
    expect(settled).toBe(false)
    expect(oldClick).not.toHaveBeenCalled()
    await vi.runAllTimersAsync()
    const result = await pending
    vi.useRealTimers()

    expect(oldClick).not.toHaveBeenCalled()
    expect(selectedPlayClicks).toBe(1)
    expect(result).toMatchObject({ ok: true, context: { stage: 'watch' } })
  })

  it('bounds a pending video.play promise inside the direct-play deadline', async () => {
    vi.useFakeTimers()
    document.body.innerHTML = `
      <div class="lolomoRow">
        <div class="title-card" tabindex="0">Example <button>Play</button></div>
      </div>
    `
    const card = document.querySelector('.title-card') as HTMLElement
    const button = document.querySelector('button') as HTMLButtonElement
    setRect(card, 20, 80)
    setRect(button, 40, 90)
    card.focus()
    const play = vi.fn(
      () => new Promise<void>(() => {
        // Deliberately unresolved to prove the runtime deadline owns completion.
      }),
    )
    const click = vi.spyOn(button, 'click').mockImplementation(() => {
      window.history.replaceState({}, '', '/watch/pending-play')
      document.body.innerHTML = '<video></video>'
      const video = document.querySelector('video') as HTMLVideoElement
      setRect(video, 20, 20, 640, 360)
      Object.defineProperty(video, 'readyState', { configurable: true, value: 2 })
      Object.defineProperty(video, 'paused', { configurable: true, value: true })
      Object.defineProperty(video, 'play', { configurable: true, value: play })
    })
    const sentinel = { sentinel: true }
    const outcome = Promise.race([
      runtime().run('OK', null),
      new Promise<typeof sentinel>((resolve) => setTimeout(() => resolve(sentinel), 8100)),
    ])

    await vi.runAllTimersAsync()
    const result = await outcome
    vi.useRealTimers()

    expect(result).toEqual({
      ok: false,
      status: 'error',
      code: 'netflix_direct_play_unavailable',
    })
    expect(click).toHaveBeenCalledOnce()
    expect(play).toHaveBeenCalledOnce()
  })

  it('maps requestFullscreen rejection to a fixed non-retryable error', async () => {
    window.history.replaceState({}, '', '/watch/fullscreen-reject')
    document.body.innerHTML = '<video></video>'
    const video = document.querySelector('video') as HTMLVideoElement
    setRect(video, 20, 20, 640, 360)
    Object.defineProperty(video, 'readyState', { configurable: true, value: 2 })
    const requestFullscreen = vi.fn().mockRejectedValue(new Error('denied'))
    Object.defineProperty(video, 'requestFullscreen', {
      configurable: true,
      value: requestFullscreen,
    })

    const result = await runtime().run('FULLSCREEN', null)

    expect(result).toEqual({
      ok: false,
      status: 'error',
      code: 'netflix_fullscreen_unavailable',
    })
    expect(requestFullscreen).toHaveBeenCalledOnce()
  })

  it('uses one anchor representative per class-only card wrapper', async () => {
    document.body.innerHTML = `
      <div class="lolomoRow">
        ${[1, 2, 3, 4, 5]
          .map(
            (index) =>
              `<div class="title-card"><a href="/title/${index}">${index}</a><button>Play</button></div>`,
          )
          .join('')}
      </div>
    `
    const wrappers = [...document.querySelectorAll('.title-card')]
    const anchors = [...document.querySelectorAll('a')]
    const buttons = [...document.querySelectorAll('button')]
    wrappers.forEach((card, index) => setRect(card, index * 180, 80))
    anchors.forEach((card, index) => setRect(card, index * 180 + 5, 80, 70, 60))
    buttons.forEach((card, index) => setRect(card, index * 180 + 90, 80, 20, 60))
    ;(anchors[0] as HTMLElement).focus()

    for (const expected of [2, 3, 4, 5]) {
      await runtime().run('NAV_RIGHT', null)
      expect(document.activeElement).toBe(anchors[expected - 1])
      expect(document.activeElement).not.toBe(buttons[expected - 1])
    }
  })

  it('supports current zh-TW browse card metadata and deterministic playback', async () => {
    vi.useFakeTimers()
    const uias = [
      'standard-card',
      'progress-card',
      'ranked-card',
      'standard-card',
      'progress-card',
    ]
    document.body.innerHTML = `
      <nav data-uia="navigation"><a href="/browse">首頁</a></nav>
      <div class="lolomoRow">
        ${uias
          .map(
            (uia, index) =>
              `<div data-uia="${uia}"><a href="/title/${index + 1}">Title ${index + 1}</a><button>Play</button></div>`,
          )
          .join('')}
      </div>
    `
    const navigation = document.querySelector('nav') as HTMLElement
    const navLink = navigation.querySelector('a') as HTMLAnchorElement
    const wrappers = uias.map(
      (_, index) => document.querySelector(`[href="/title/${index + 1}"]`)?.parentElement as HTMLElement,
    )
    const anchors = uias.map(
      (_, index) => document.querySelector(`[href="/title/${index + 1}"]`) as HTMLAnchorElement,
    )
    const buttons = wrappers.map((wrapper) => wrapper.querySelector('button') as HTMLButtonElement)
    setRect(navigation, 20, 20, 200, 40)
    setRect(navLink, 20, 20, 100, 40)
    wrappers.forEach((card, index) => setRect(card, index * 180, 100))
    anchors.forEach((card, index) => setRect(card, index * 180 + 5, 100, 70, 60))
    buttons.forEach((card, index) => setRect(card, index * 180 + 90, 100, 20, 60))

    const primary = await runtime().run('FOCUS_PRIMARY', null)
    expect(document.activeElement).toBe(anchors[0])
    expect(primary.context).toMatchObject({
      stage: 'browse',
      focused_title: 'Title 1',
    })

    for (const expected of [2, 3, 4, 5]) {
      await runtime().run('NAV_RIGHT', null)
      expect(document.activeElement).toBe(anchors[expected - 1])
    }
    for (const expected of [4, 3, 2, 1]) {
      await runtime().run('NAV_LEFT', null)
      expect(document.activeElement).toBe(anchors[expected - 1])
    }

    const play = vi.spyOn(buttons[0], 'click').mockImplementation(() => {
      window.history.replaceState({}, '', '/watch/current-card')
      document.body.innerHTML = '<video></video>'
      setReadyVideo()
    })
    const result = await runtime().run('OK', null)
    await vi.runAllTimersAsync()
    vi.useRealTimers()
    expect(play).toHaveBeenCalledOnce()
    expect(result).toMatchObject({
      ok: true,
      status: 'playing',
      context: { stage: 'watch' },
    })
  })

  it('uses aria-label as browse focused_title when current cards have empty text', async () => {
    window.history.replaceState({}, '', '/browse')
    document.body.innerHTML = `
      <div class="lolomoRow">
        <a data-uia="standard-card" href="/watch/one" aria-label="陽光女子合唱團"><img alt=""></a>
        <a data-uia="standard-card" href="/watch/two" aria-label="毛骨悚然的戀愛"><img alt=""></a>
      </div>
    `
    const cards = [...document.querySelectorAll('[data-uia="standard-card"]')] as HTMLAnchorElement[]
    cards.forEach((card, index) => {
      setRect(card, 20 + index * 180, 100, 160, 90)
      setRect(card.querySelector('img') as HTMLElement, 20 + index * 180, 100, 160, 90)
    })


    const primary = await runtime().run('FOCUS_PRIMARY', null)
    expect(document.activeElement).toBe(cards[0])
    expect(primary.context).toMatchObject({
      stage: 'browse',
      focused_title: '陽光女子合唱團',
    })

    await runtime().run('NAV_RIGHT', null)
    expect(document.activeElement).toBe(cards[1])
    expect((await runtime().run('READ_CONTEXT', null)).context).toMatchObject({
      stage: 'browse',
      focused_title: '毛骨悚然的戀愛',
    })
  })

  it('focuses a current card that is only partially onscreen', async () => {
    window.history.replaceState({}, '', '/browse')
    document.body.innerHTML = `
      <div class="lolomoRow">
        <a data-uia="standard-card" href="/watch/one" aria-label="陽光女子合唱團"><img alt=""></a>
      </div>
    `
    const card = document.querySelector('[data-uia="standard-card"]') as HTMLAnchorElement
    const image = card.querySelector('img') as HTMLElement
    setRect(card, 48, 680, 279, 80)
    setRect(image, 48, 680, 279, 80)

    const result = await runtime().run('FOCUS_PRIMARY', null)
    expect(document.activeElement).toBe(card)
    expect(result).toMatchObject({
      ok: true,
      status: 'focused',
      context: { stage: 'browse', focused_title: '陽光女子合唱團' },
    })
  })




  it('focuses a profile choice on the /browse profile gate instead of navigation', async () => {
    window.history.replaceState({}, '', '/browse')
    document.body.innerHTML = `
      <nav data-uia="navigation"><a href="/">Netflix</a></nav>
      <div data-uia="profile-choices-page">
        <a data-uia="action-select-profile+primary" class="profile-link" href="/SwitchProfile?tkn=one">洪靖倫</a>
        <a data-uia="action-select-profile+secondary" class="profile-link" href="/SwitchProfile?tkn=two">Angelo</a>
      </div>
    `
    const navigation = document.querySelector('nav') as HTMLElement
    const navLink = navigation.querySelector('a') as HTMLAnchorElement
    const primary = document.querySelector('[data-uia="action-select-profile+primary"]') as HTMLAnchorElement
    const secondary = document.querySelector('[data-uia="action-select-profile+secondary"]') as HTMLAnchorElement
    setRect(navigation, 20, 20, 200, 40)
    setRect(navLink, 20, 20, 80, 40)
    setRect(primary, 80, 160, 120, 120)
    setRect(secondary, 220, 160, 120, 120)

    const result = await runtime().run('FOCUS_PRIMARY', null)
    expect(document.activeElement).toBe(primary)
    expect(result).toMatchObject({
      ok: true,
      status: 'focused',
      context: {
        stage: 'browse',
        input_kind: 'none',
        has_error: false,
        can_submit: false,
        focused_title: '洪靖倫',
      },
    })
  })

  it('selects a profile gate choice then focuses the first ready browse card', async () => {
    vi.useFakeTimers()
    window.history.replaceState({}, '', '/browse')
    document.body.innerHTML = `
      <nav data-uia="navigation"><a href="/">Netflix</a></nav>
      <div data-uia="profile-choices-page">
        <a data-uia="action-select-profile+primary" class="profile-link" href="/SwitchProfile?tkn=one">洪靖倫</a>
      </div>
    `
    const navigation = document.querySelector('nav') as HTMLElement
    const navLink = navigation.querySelector('a') as HTMLAnchorElement
    const primary = document.querySelector('[data-uia="action-select-profile+primary"]') as HTMLAnchorElement
    setRect(navigation, 20, 20, 200, 40)
    setRect(navLink, 20, 20, 80, 40)
    setRect(primary, 80, 160, 120, 120)
    await runtime().run('FOCUS_PRIMARY', null)

    primary.addEventListener('click', (event) => {
      event.preventDefault()
      window.setTimeout(() => {
        document.body.innerHTML = `
          <div class="lolomoRow">
            <div data-uia="standard-card"><a href="/title/ready">Ready Title</a><button>Play</button></div>
            <div data-uia="standard-card"><a href="/title/next">Next Title</a><button>Play</button></div>
          </div>
        `
        const row = document.querySelector('.lolomoRow') as HTMLElement
        const cards = [...document.querySelectorAll('[data-uia="standard-card"]')] as HTMLElement[]
        const anchors = [...document.querySelectorAll('a')] as HTMLAnchorElement[]
        const buttons = [...document.querySelectorAll('button')] as HTMLButtonElement[]
        setRect(row, 0, 80, 1200, 120)
        cards.forEach((card, index) => setRect(card, 20 + index * 180, 100))
        anchors.forEach((card, index) => setRect(card, 25 + index * 180, 100, 70, 60))
        buttons.forEach((card, index) => setRect(card, 110 + index * 180, 100, 20, 60))
      }, 400)
    })

    const pending = runtime().run('OK', null)
    await vi.runAllTimersAsync()
    const result = await pending
    vi.useRealTimers()

    expect(document.activeElement?.getAttribute('href')).toBe('/title/ready')
    expect(result).toMatchObject({
      ok: true,
      status: 'focused',
      context: { stage: 'browse', focused_title: 'Ready Title' },
    })
  })

  it('retries browse primary focus until a logical card is ready', async () => {
    vi.useFakeTimers()
    window.history.replaceState({}, '', '/browse')
    document.body.innerHTML =
      '<nav data-uia="navigation"><a href="/browse">首頁</a></nav>'
    const navigation = document.querySelector('nav') as HTMLElement
    const navLink = navigation.querySelector('a') as HTMLAnchorElement
    setRect(navigation, 20, 20, 200, 40)
    setRect(navLink, 20, 20, 100, 40)

    const unavailable = runtime().run('FOCUS_PRIMARY', null)
    await vi.runAllTimersAsync()
    expect(await unavailable).toEqual({
      ok: false,
      status: 'error',
      code: 'netflix_focus_unavailable',
    })

    window.setTimeout(() => {
      const row = document.createElement('div')
      row.className = 'lolomoRow'
      row.innerHTML =
        '<div data-uia="standard-card"><a href="/title/ready">Ready Title</a><button>Play</button></div>'
      document.body.append(row)
      const wrapper = row.firstElementChild as HTMLElement
      const anchor = wrapper.querySelector('a') as HTMLAnchorElement
      const play = wrapper.querySelector('button') as HTMLButtonElement
      setRect(wrapper, 20, 100)
      setRect(anchor, 25, 100, 70, 60)
      setRect(play, 110, 100, 20, 60)
    }, 400)

    const pending = runtime().run('FOCUS_PRIMARY', null)
    await vi.runAllTimersAsync()
    const result = await pending
    vi.useRealTimers()

    expect(document.activeElement?.getAttribute('href')).toBe('/title/ready')
    expect(result).toMatchObject({
      ok: true,
      status: 'focused',
      context: { stage: 'browse', focused_title: 'Ready Title' },
    })
  })

})
