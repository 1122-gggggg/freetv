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

type RuntimeResult = {
  ok: boolean
  status: string
  code?: string
  focus?: FocusFingerprint
}

type Runtime = {
  version: string
  run: (action: string, focus: FocusFingerprint | null) => RuntimeResult
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
  it('exposes only the fixed global version and run interface and re-enumerates every run', () => {
    expect(runtime().version).toBe('1')
    expect(Object.keys(runtime()).sort()).toEqual(['run', 'version'])

    document.body.innerHTML = '<button id="first">First</button>'
    const first = document.querySelector('#first') as HTMLButtonElement
    setRect(first, 20, 20)
    expect(runtime().run('FOCUS_PRIMARY', null).focus?.text).toBe('First')

    document.body.innerHTML = '<button id="replacement">Replacement</button>'
    const replacement = document.querySelector('#replacement') as HTMLButtonElement
    setRect(replacement, 20, 20)
    expect(runtime().run('FOCUS_PRIMARY', null)).toMatchObject({
      ok: true,
      status: 'focused',
      focus: { text: 'Replacement' },
    })
    expect(document.activeElement).toBe(replacement)
    expect(runtime().run('NOT_AN_ACTION', null)).toEqual({
      ok: false,
      status: 'error',
      code: 'netflix_focus_unavailable',
    })
  })

  it('moves right by rectangles and keeps focus at the boundary', () => {
    document.body.innerHTML = '<button id="a">A</button><button id="b">B</button><button id="c">C</button>'
    const [a, b, c] = [...document.querySelectorAll('button')]
    setRect(a, 0, 0)
    setRect(b, 180, 0)
    setRect(c, 180, 140)
    ;(a as HTMLElement).focus()

    expect(runtime().run('NAV_RIGHT', null).status).toBe('moved')
    expect(document.activeElement).toBe(b)
    expect(runtime().run('NAV_RIGHT', null).status).toBe('boundary')
    expect(document.activeElement).toBe(b)
  })

  it('moves in all four directions from the current rectangle', () => {
    document.body.innerHTML = `
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
      expect(runtime().run(action, null).status).toBe('moved')
      expect(document.activeElement).toBe(target)
    }
  })

  it('filters hidden disabled zero-area offscreen and covered candidates', () => {
    document.body.innerHTML = `
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

    expect(runtime().run('NAV_RIGHT', null).status).toBe('moved')
    expect(document.activeElement).toBe(document.querySelector('#valid'))
  })

  it('excludes structural data-uia containers and focuses their child control', () => {
    document.body.innerHTML = `
      <div id="modal" data-uia="modal-dialog">
        <button id="continue">Continue</button>
      </div>
    `
    const modal = document.querySelector('#modal') as HTMLElement
    const child = document.querySelector('#continue') as HTMLButtonElement
    setRect(modal, 20, 20, 800, 500)
    setRect(child, 80, 80)

    expect(runtime().run('FOCUS_PRIMARY', null)).toMatchObject({
      ok: true,
      status: 'focused',
      focus: { text: 'Continue' },
    })
    expect(document.activeElement).toBe(child)
  })

  it('programmatically focuses and clicks actionable non-native data-uia cards', () => {
    document.body.innerHTML = '<div id="card" data-uia="title-card">Title</div>'
    const card = document.querySelector('#card') as HTMLElement
    setRect(card, 20, 20)
    const click = vi.spyOn(card, 'click')

    expect(runtime().run('FOCUS_PRIMARY', null)).toMatchObject({
      ok: true,
      status: 'focused',
      focus: { uia: 'title-card', text: 'Title' },
    })
    expect(card.tabIndex).toBe(-1)
    expect(document.activeElement).toBe(card)
    expect(runtime().run('OK', null).status).toBe('clicked')
    expect(click).toHaveBeenCalledOnce()
  })

  it('prefers axis overlap then primary distance then perpendicular distance then DOM order', () => {
    document.body.innerHTML = '<button id="source">S</button><button id="near">Near</button><button id="overlap">Overlap</button>'
    let source = document.querySelector('#source') as HTMLButtonElement
    setRect(source, 0, 100, 100, 100)
    setRect(document.querySelector('#near')!, 130, 260, 100, 100)
    setRect(document.querySelector('#overlap')!, 500, 120, 100, 100)
    source.focus()
    runtime().run('NAV_RIGHT', null)
    expect(document.activeElement).toBe(document.querySelector('#overlap'))

    document.body.innerHTML = '<button id="source">S</button><button id="primary">Primary</button><button id="perpendicular">Perpendicular</button>'
    source = document.querySelector('#source') as HTMLButtonElement
    setRect(source, 0, 0, 100, 100)
    setRect(document.querySelector('#primary')!, 150, 300, 100, 100)
    setRect(document.querySelector('#perpendicular')!, 250, 120, 100, 100)
    source.focus()
    runtime().run('NAV_RIGHT', null)
    expect(document.activeElement).toBe(document.querySelector('#primary'))

    document.body.innerHTML = '<button id="source">S</button><button id="first">First</button><button id="second">Second</button>'
    source = document.querySelector('#source') as HTMLButtonElement
    setRect(source, 0, 0, 100, 100)
    setRect(document.querySelector('#first')!, 200, 0, 100, 80)
    setRect(document.querySelector('#second')!, 200, 220, 100, 80)
    source.focus()
    runtime().run('NAV_RIGHT', null)
    expect(document.activeElement).toBe(document.querySelector('#first'))
  })

  it('restores a rebuilt card by role label data-uia path rail and index', () => {
    document.body.innerHTML = `
      <section data-rail-title="Trending">
        <a role="button" aria-label="Play Alpha" data-uia="title-card" href="/title/101">Alpha</a>
        <a role="button" aria-label="Play Beta" data-uia="title-card" href="/title/202">Beta</a>
      </section>
    `
    setSequentialRects()
    const previous = runtime().run('FOCUS_PRIMARY', null).focus!
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
    const result = runtime().run('FOCUS_PRIMARY', previous)
    expect(result.status).toBe('restored')
    expect(document.activeElement?.getAttribute('aria-label')).toBe('Play Alpha')
  })

  it('falls back to the page primary action when the previous semantic target disappeared', () => {
    const missing: FocusFingerprint = {
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
        expected: '#nav',
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
      expect(runtime().run('FOCUS_PRIMARY', missing).status).toBe('focused')
      expect(document.activeElement).toBe(document.querySelector(fixture.expected))
    }
  })

  it('refocuses the login field at an explicit recovery entry point', () => {
    document.body.innerHTML = `
      <input id="email" aria-label="Email"><input id="password" aria-label="Password" aria-invalid="true" aria-describedby="password-error">
      <button id="submit">Sign in</button><div id="password-error" role="alert" data-for="password">Incorrect password</div>
    `
    setSequentialRects('input,button,[role="alert"]')

    expect(runtime().run('FOCUS_PRIMARY', null)).toMatchObject({
      ok: true,
      status: 'error_refocused',
      focus: { label: 'Password' },
    })
    expect(document.activeElement).toBe(document.querySelector('#password'))
  })

  it('allows error field navigation to submit and OK without forced refocus', () => {
    document.body.innerHTML = `
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

    expect(runtime().run('NAV_RIGHT', null).status).toBe('moved')
    expect(document.activeElement).toBe(submit)
    expect(runtime().run('OK', null).status).toBe('clicked')
    expect(click).toHaveBeenCalledOnce()
  })

  it('focuses editable fields without reading value', () => {
    document.body.innerHTML = '<input id="secret" aria-label="Password" data-uia="password-field" type="password">'
    const input = document.querySelector('#secret') as HTMLInputElement
    setRect(input, 20, 20)
    const valueRead = vi.fn(() => 'never-read-this')
    Object.defineProperty(input, 'value', { configurable: true, get: valueRead })

    const result = runtime().run('FOCUS_EDITABLE', null)
    expect(result).toMatchObject({
      ok: true,
      status: 'focused',
      focus: { role: 'textbox', label: 'Password', text: '' },
    })
    expect(valueRead).not.toHaveBeenCalled()
    expect(result.focus).not.toHaveProperty('value')
    expect(document.activeElement).toBe(input)
  })

  it('does not read or expose text from contenteditable and role textboxes', () => {
    const fixtures = [
      '<div id="editable" contenteditable="true" aria-label="Message">contenteditable secret</div>',
      '<div id="editable" role="textbox" aria-label="Code">role textbox secret</div>',
    ]

    for (const html of fixtures) {
      document.body.innerHTML = html
      const field = document.querySelector('#editable') as HTMLElement
      setRect(field, 20, 20)
      const textRead = vi.fn(() => 'must-not-leak')
      Object.defineProperty(field, 'textContent', { configurable: true, get: textRead })

      const result = runtime().run('FOCUS_EDITABLE', null)
      expect(result).toMatchObject({ ok: true, status: 'focused', focus: { text: '' } })
      expect(result.focus).not.toHaveProperty('value')
      expect(textRead).not.toHaveBeenCalled()
      expect(document.activeElement).toBe(field)
    }
  })

  it('clicks cards and buttons but only focuses input on OK', () => {
    document.body.innerHTML = '<button id="card" data-uia="title-card">Card</button><input id="search" aria-label="Search">'
    const card = document.querySelector('#card') as HTMLButtonElement
    const input = document.querySelector('#search') as HTMLInputElement
    setRect(card, 20, 20)
    setRect(input, 200, 20)
    const cardClick = vi.spyOn(card, 'click')
    const inputClick = vi.spyOn(input, 'click')

    card.focus()
    expect(runtime().run('OK', null).status).toBe('clicked')
    expect(cardClick).toHaveBeenCalledOnce()

    input.focus()
    expect(runtime().run('OK', null).status).toBe('focused')
    expect(inputClick).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(input)
  })

  it('closes the top dialog or detail layer before history back', () => {
    document.body.innerHTML = `
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
    const closeClick = vi.spyOn(topClose, 'click')
    const historyBack = vi.spyOn(window.history, 'back').mockImplementation(() => undefined)

    expect(runtime().run('BACK', null).status).toBe('closed')
    expect(closeClick).toHaveBeenCalledOnce()
    expect(historyBack).not.toHaveBeenCalled()

    lower.remove()
    top.remove()
    expect(runtime().run('BACK', null).status).toBe('history')
    expect(historyBack).toHaveBeenCalledOnce()
  })

  it('toggles only the visible video in the current document', () => {
    document.body.innerHTML = '<video id="hidden"></video><video id="visible"></video>'
    const hidden = document.querySelector('#hidden') as HTMLVideoElement
    const video = document.querySelector('#visible') as HTMLVideoElement
    setRect(hidden, 20, 20, 0, 0)
    setRect(video, 200, 100, 640, 360)
    let paused = true
    Object.defineProperty(video, 'paused', { configurable: true, get: () => paused })
    const play = vi.spyOn(video, 'play').mockResolvedValue(undefined)
    const pause = vi.spyOn(video, 'pause').mockImplementation(() => undefined)
    const hiddenPlay = vi.spyOn(hidden, 'play').mockResolvedValue(undefined)

    expect(runtime().run('PLAY_PAUSE', null).status).toBe('playing')
    expect(play).toHaveBeenCalledOnce()
    expect(hiddenPlay).not.toHaveBeenCalled()

    paused = false
    expect(runtime().run('PLAY_PAUSE', null).status).toBe('paused')
    expect(pause).toHaveBeenCalledOnce()
  })

  it('returns stable focus input and video error codes', () => {
    expect(runtime().run('FOCUS_PRIMARY', null)).toEqual({
      ok: false,
      status: 'error',
      code: 'netflix_focus_unavailable',
    })

    document.body.innerHTML = '<button>Only button</button>'
    setSequentialRects()
    expect(runtime().run('FOCUS_EDITABLE', null)).toEqual({
      ok: false,
      status: 'error',
      code: 'netflix_input_unavailable',
    })
    expect(runtime().run('PLAY_PAUSE', null)).toEqual({
      ok: false,
      status: 'error',
      code: 'netflix_video_unavailable',
    })
  })

  it('supports focus next without retaining stale element references', () => {
    document.body.innerHTML = '<button id="first">First</button><button id="second">Second</button>'
    setSequentialRects()
    const first = document.querySelector('#first') as HTMLButtonElement
    first.focus()
    expect(runtime().run('FOCUS_NEXT', null).status).toBe('moved')
    expect(document.activeElement).toBe(document.querySelector('#second'))

    document.querySelector('#second')?.remove()
    expect(runtime().run('FOCUS_NEXT', null).status).toBe('focused')
    expect(document.activeElement).toBe(first)
  })

  it('adds white outline red glow and center-center scrollIntoView', () => {
    document.body.innerHTML = '<button id="target">Target</button>'
    const button = document.querySelector('#target') as HTMLButtonElement
    setRect(button, 20, 20)
    const scrollIntoView = vi.fn()
    Object.defineProperty(button, 'scrollIntoView', { configurable: true, value: scrollIntoView })

    expect(runtime().run('FOCUS_PRIMARY', null).ok).toBe(true)
    expect(button.style.outline).toContain('3px solid')
    expect(button.style.outline).toMatch(/#fff|rgb\(255, 255, 255\)/)
    expect(button.style.boxShadow).toMatch(/rgba\(229,\s*9,\s*20,\s*(?:0?\.95)\)/)
    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'center', inline: 'center' })
  })
})
