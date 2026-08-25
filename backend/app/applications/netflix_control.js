(() => {
  'use strict'

  const VERSION = '1'
  const ACTIONS = new Set([
    'FOCUS_PRIMARY',
    'FOCUS_EDITABLE',
    'FOCUS_NEXT',
    'NAV_UP',
    'NAV_DOWN',
    'NAV_LEFT',
    'NAV_RIGHT',
    'OK',
    'BACK',
    'PLAY_PAUSE',
  ])
  const EXPLICIT_INTERACTIVE_SELECTOR = [
    'a[href]',
    'button',
    'input:not([type="hidden"])',
    'textarea',
    'select',
    '[contenteditable="true"]',
    '[tabindex]:not([tabindex="-1"])',
    '[role="button"]',
    '[role="link"]',
    '[role="textbox"]',
    '[role="searchbox"]',
    '[role="tab"]',
    '[role="option"]',
    '[role="menuitem"]',
  ].join(',')
  const CANDIDATE_SELECTOR = `${EXPLICIT_INTERACTIVE_SELECTOR},[data-uia]`
  const ACTIONABLE_UIA_FRAGMENTS = [
    'title-card',
    'slider-item',
    'search-result',
    'profile',
    'play',
    'button',
    'link',
    'navigation',
    'menu',
    'tab',
    'search',
    'next',
    'submit',
    'close',
    'continue',
    'control',
    'action',
    'watch',
    'select',
  ]
  const CONTROL_UIA_FRAGMENTS = [
    'play',
    'button',
    'link',
    'menu',
    'tab',
    'search',
    'next',
    'submit',
    'close',
    'continue',
    'control',
    'action',
    'watch',
    'select',
  ]
  const STRUCTURAL_UIA_FRAGMENTS = [
    'modal',
    'dialog',
    'row',
    'rail',
    'container',
    'wrapper',
    'label',
    'heading',
  ]
  const OVERLAY_SELECTOR = [
    'dialog[open]',
    '[role="dialog"]',
    '[aria-modal="true"]',
    '[data-uia*="modal" i]',
    '[data-uia*="dialog" i]',
    '[data-uia*="detail" i]',
  ].join(',')

  const normalizeText = (value) => String(value || '').replace(/\s+/g, ' ').trim()

  const rectCenter = (rect) => ({
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
  })

  const isDisabled = (element) =>
    element.matches(':disabled') ||
    element.getAttribute('aria-disabled') === 'true' ||
    element.getAttribute('inert') !== null

  const visible = (element) => {
    if (!(element instanceof HTMLElement) || !element.isConnected) return false
    if (
      element.hidden ||
      element.getAttribute('aria-hidden') === 'true' ||
      element.matches('input[type="hidden"]') ||
      isDisabled(element)
    ) {
      return false
    }

    const style = globalThis.getComputedStyle(element)
    if (
      style.display === 'none' ||
      style.visibility === 'hidden' ||
      style.visibility === 'collapse' ||
      style.opacity === '0' ||
      style.pointerEvents === 'none'
    ) {
      return false
    }

    const rect = element.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) return false
    const center = rectCenter(rect)
    if (
      rect.right <= 0 ||
      rect.bottom <= 0 ||
      rect.left >= globalThis.innerWidth ||
      rect.top >= globalThis.innerHeight ||
      center.x < 0 ||
      center.y < 0 ||
      center.x >= globalThis.innerWidth ||
      center.y >= globalThis.innerHeight
    ) {
      return false
    }

    if (typeof document.elementFromPoint !== 'function') return true
    const hit = document.elementFromPoint(center.x, center.y)
    return hit === element || (hit instanceof Node && element.contains(hit))
  }

  const actionableUia = (element) => {
    const uia = normalizeText(element.getAttribute('data-uia')).toLowerCase()
    if (!uia) return false
    const actionable = ACTIONABLE_UIA_FRAGMENTS.some((fragment) => uia.includes(fragment))
    if (!actionable) return false
    const structural = STRUCTURAL_UIA_FRAGMENTS.some((fragment) => uia.includes(fragment))
    return !structural || CONTROL_UIA_FRAGMENTS.some((fragment) => uia.includes(fragment))
  }

  const interactiveCandidate = (element) =>
    element.matches(EXPLICIT_INTERACTIVE_SELECTOR) || actionableUia(element)

  const interactiveElements = () =>
    [...document.querySelectorAll(CANDIDATE_SELECTOR)].filter(
      (element) =>
        element instanceof HTMLElement && interactiveCandidate(element) && visible(element),
    )

  const editable = (element) => {
    if (!(element instanceof HTMLElement) || isDisabled(element)) return false
    if (element instanceof HTMLTextAreaElement) return true
    if (element instanceof HTMLInputElement) {
      return !new Set(['button', 'checkbox', 'file', 'hidden', 'image', 'radio', 'range', 'reset', 'submit']).has(
        element.type.toLowerCase(),
      )
    }
    return (
      element.isContentEditable ||
      element.getAttribute('contenteditable') === 'true' ||
      element.getAttribute('role') === 'textbox' ||
      element.getAttribute('role') === 'searchbox'
    )
  }

  const roleOf = (element) => {
    const explicit = normalizeText(element.getAttribute('role')).toLowerCase()
    if (explicit) return explicit
    if (element instanceof HTMLAnchorElement) return 'link'
    if (element instanceof HTMLButtonElement) return 'button'
    if (editable(element)) return 'textbox'
    if (element instanceof HTMLSelectElement) return 'combobox'
    return normalizeText(element.tagName).toLowerCase()
  }

  const labelledText = (element) => {
    const labelledBy = normalizeText(element.getAttribute('aria-labelledby'))
    if (!labelledBy) return ''
    return normalizeText(
      labelledBy
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.textContent || '')
        .join(' '),
    )
  }

  const labelOf = (element) =>
    normalizeText(
      element.getAttribute('aria-label') ||
        labelledText(element) ||
        element.getAttribute('alt') ||
        element.getAttribute('title') ||
        element.getAttribute('placeholder') ||
        (editable(element) ? '' : element.textContent),
    )

  const visibleTextOf = (element) =>
    editable(element) ? '' : normalizeText(element.textContent)

  const pathKindOf = (element) => {
    const declared = normalizeText(element.getAttribute('data-path-kind')).toLowerCase()
    if (declared) return declared

    const href = element.getAttribute('href')
    if (href) {
      try {
        const segment = new URL(href, document.baseURI).pathname.split('/').filter(Boolean)[0]
        if (segment) return segment.toLowerCase()
      } catch {
        return ''
      }
    }

    const uia = normalizeText(element.getAttribute('data-uia')).toLowerCase()
    for (const kind of ['title', 'watch', 'search', 'login', 'verify', 'profile', 'play']) {
      if (uia.includes(kind)) return kind
    }
    return ''
  }

  const railContainer = (element) =>
    element.closest('[data-rail-title],[data-rail],[role="row"],[data-uia*="row" i],section')

  const railOf = (element) => {
    const rail = railContainer(element)
    if (!(rail instanceof HTMLElement)) return ''
    return normalizeText(
      rail.getAttribute('data-rail-title') ||
        rail.getAttribute('data-rail') ||
        rail.getAttribute('aria-label') ||
        rail.querySelector('h1,h2,h3,h4,h5,h6,[role="heading"]')?.textContent,
    )
  }

  const fingerprint = (element, elements) => {
    const rail = railContainer(element)
    const peers = rail ? elements.filter((candidate) => railContainer(candidate) === rail) : elements
    return {
      role: roleOf(element),
      label: labelOf(element),
      uia: normalizeText(element.getAttribute('data-uia')),
      text: visibleTextOf(element),
      pathKind: pathKindOf(element),
      rail: railOf(element),
      index: Math.max(0, peers.indexOf(element)),
    }
  }

  const semanticScore = (candidate, previous) => {
    const current = candidate.fingerprint
    let score = 0
    if (previous.role && current.role === previous.role) score += 8
    if (previous.label && current.label === previous.label) score += 8
    if (previous.uia && current.uia === previous.uia) score += 7
    if (previous.text && current.text === previous.text) score += 5
    if (previous.pathKind && current.pathKind === previous.pathKind) score += 4
    if (previous.rail && current.rail === previous.rail) score += 3
    if (Number.isInteger(previous.index)) {
      if (current.index === previous.index) score += 2
      else if (Math.abs(current.index - previous.index) === 1) score += 1
    }
    return score
  }

  const restoreTarget = (elements, previous) => {
    if (!previous || typeof previous !== 'object') return null
    const ranked = elements
      .map((element, index) => ({
        element,
        fingerprint: fingerprint(element, elements),
        index,
      }))
      .map((candidate) => ({ ...candidate, score: semanticScore(candidate, previous) }))
      .sort((left, right) => right.score - left.score || left.index - right.index)
    return ranked[0] && ranked[0].score >= 12 ? ranked[0].element : null
  }

  const focusResult = (target, status, elements) => {
    for (const oldTarget of document.querySelectorAll('[data-freetv-netflix-focus="true"]')) {
      if (oldTarget instanceof HTMLElement && oldTarget !== target) {
        oldTarget.style.outline = ''
        oldTarget.style.boxShadow = ''
        oldTarget.removeAttribute('data-freetv-netflix-focus')
      }
    }

    if (target.tabIndex < 0) target.tabIndex = -1
    target.focus({ preventScroll: true })
    target.setAttribute('data-freetv-netflix-focus', 'true')
    target.style.outline = '3px solid #fff'
    target.style.boxShadow = '0 0 0 3px #fff, 0 0 18px 6px rgba(229,9,20,.95)'
    if (typeof target.scrollIntoView === 'function') {
      target.scrollIntoView({ block: 'center', inline: 'center' })
    }
    return { ok: true, status, focus: fingerprint(target, elements) }
  }

  const error = (code) => ({ ok: false, status: 'error', code })

  const visibleOverlays = () =>
    [...document.querySelectorAll(OVERLAY_SELECTOR)].filter(
      (element) => element instanceof HTMLElement && visible(element),
    )

  const loginErrorTarget = (elements) => {
    const invalid = elements.find(
      (element) => editable(element) && element.getAttribute('aria-invalid') === 'true',
    )
    if (invalid) return invalid

    const messages = [...document.querySelectorAll(
      '[role="alert"],[aria-live="assertive"],[data-uia*="error" i],.error-message',
    )].filter((element) => element instanceof HTMLElement && visible(element))
    for (const message of messages) {
      const targetId =
        message.getAttribute('data-for') ||
        message.getAttribute('for') ||
        message.getAttribute('aria-controls')
      if (targetId) {
        const target = document.getElementById(targetId)
        if (target instanceof HTMLElement && editable(target) && visible(target)) return target
      }
      if (message.id) {
        const described = elements.find(
          (element) =>
            editable(element) &&
            normalizeText(element.getAttribute('aria-describedby')).split(/\s+/).includes(message.id),
        )
        if (described) return described
      }
      const form = message.closest('form')
      const related = elements.find((element) => editable(element) && form && form.contains(element))
      if (related) return related
    }
    return null
  }

  const uiaIncludes = (element, fragments) => {
    const uia = normalizeText(element.getAttribute('data-uia')).toLowerCase()
    return fragments.some((fragment) => uia.includes(fragment))
  }

  const primaryTarget = (elements) => {
    const overlays = visibleOverlays()
    const topOverlay = overlays.at(-1)
    if (topOverlay) {
      const play = elements.find(
        (element) => topOverlay.contains(element) && uiaIncludes(element, ['play', 'resume']),
      )
      if (play) return play
      const firstInOverlay = elements.find((element) => topOverlay.contains(element))
      if (firstInOverlay) return firstInOverlay
    }

    const profile = elements.find((element) => uiaIncludes(element, ['profile-link', 'profile-gate']))
    if (profile) return profile

    const visibleVideo = [...document.querySelectorAll('video')].some(
      (element) => element instanceof HTMLVideoElement && visible(element),
    )
    if (visibleVideo) {
      const playerControl = elements.find((element) =>
        uiaIncludes(element, ['control-play', 'play-pause', 'player-control']),
      )
      if (playerControl) return playerControl
    }

    const loginPage = elements.some(
      (element) =>
        editable(element) &&
        (element instanceof HTMLInputElement && ['email', 'password'].includes(element.type.toLowerCase()) ||
          uiaIncludes(element, ['login', 'password', 'email', 'verify', 'otp', 'code'])),
    )
    if (loginPage) {
      const field = elements.find((element) => editable(element))
      if (field) return field
    }

    const navigation = elements.find((element) =>
      uiaIncludes(element, ['navigation', 'main-nav', 'menu-home', 'nav-']),
    )
    if (navigation) return navigation

    const card = elements.find((element) =>
      uiaIncludes(element, ['title-card', 'slider-item', 'search-result']),
    )
    if (card) return card

    return elements.find((element) => editable(element)) || elements[0] || null
  }

  const recoverFocus = (elements, previous) => {
    const restored = restoreTarget(elements, previous)
    if (restored) return focusResult(restored, 'restored', elements)
    const primary = primaryTarget(elements)
    return primary ? focusResult(primary, 'focused', elements) : error('netflix_focus_unavailable')
  }

  const axisOverlaps = (source, candidate, horizontal) => {
    if (horizontal) {
      return Math.min(source.bottom, candidate.bottom) - Math.max(source.top, candidate.top) > 0
    }
    return Math.min(source.right, candidate.right) - Math.max(source.left, candidate.left) > 0
  }

  const directionalTarget = (elements, current, action) => {
    const sourceRect = current.getBoundingClientRect()
    const sourceCenter = rectCenter(sourceRect)
    const horizontal = action === 'NAV_LEFT' || action === 'NAV_RIGHT'
    const positive = action === 'NAV_RIGHT' || action === 'NAV_DOWN'

    return elements
      .filter((element) => element !== current)
      .map((element, index) => {
        const rect = element.getBoundingClientRect()
        const center = rectCenter(rect)
        const primaryDelta = horizontal ? center.x - sourceCenter.x : center.y - sourceCenter.y
        return {
          element,
          index,
          inDirection: positive ? primaryDelta > 0 : primaryDelta < 0,
          overlap: axisOverlaps(sourceRect, rect, horizontal),
          primary: Math.abs(primaryDelta),
          perpendicular: horizontal
            ? Math.abs(center.y - sourceCenter.y)
            : Math.abs(center.x - sourceCenter.x),
        }
      })
      .filter((candidate) => candidate.inDirection)
      .sort(
        (left, right) =>
          Number(right.overlap) - Number(left.overlap) ||
          left.primary - right.primary ||
          left.perpendicular - right.perpendicular ||
          left.index - right.index,
      )[0]?.element || null
  }

  const closeTopOverlay = () => {
    const overlay = visibleOverlays().at(-1)
    if (!overlay) return false
    const closeSelectors = [
      '[data-uia*="close" i]',
      'button[aria-label*="close" i]',
      'button[aria-label*="關閉"]',
      '[role="button"][aria-label*="close" i]',
      '[role="button"][aria-label*="關閉"]',
    ].join(',')
    const close = [...overlay.querySelectorAll(closeSelectors)].find(
      (element) => element instanceof HTMLElement && visible(element),
    )
    if (close instanceof HTMLElement) close.click()
    else if (overlay instanceof HTMLDialogElement && typeof overlay.close === 'function') overlay.close()
    else overlay.click()
    return true
  }

  const run = (action, previousFocus = null) => {
    if (!ACTIONS.has(action)) return error('netflix_focus_unavailable')

    if (action === 'BACK') {
      if (closeTopOverlay()) return { ok: true, status: 'closed' }
      globalThis.history.back()
      return { ok: true, status: 'history' }
    }

    if (action === 'PLAY_PAUSE') {
      const video = [...document.querySelectorAll('video')].find(
        (element) => element instanceof HTMLVideoElement && visible(element),
      )
      if (!(video instanceof HTMLVideoElement)) return error('netflix_video_unavailable')
      if (!video.paused && !video.ended) {
        video.pause()
        return { ok: true, status: 'paused' }
      }
      const playResult = video.play()
      if (playResult && typeof playResult.catch === 'function') playResult.catch(() => undefined)
      return { ok: true, status: 'playing' }
    }

    const elements = interactiveElements()
    const errorField = loginErrorTarget(elements)
    const active = document.activeElement
    const current = active instanceof HTMLElement && elements.includes(active) ? active : null
    if (
      errorField &&
      (!current || action === 'FOCUS_PRIMARY' || action === 'FOCUS_EDITABLE')
    ) {
      return focusResult(errorField, 'error_refocused', elements)
    }

    if (action === 'FOCUS_PRIMARY') {
      const restored = restoreTarget(elements, previousFocus)
      if (restored) return focusResult(restored, 'restored', elements)
      const primary = primaryTarget(elements)
      return primary ? focusResult(primary, 'focused', elements) : error('netflix_focus_unavailable')
    }

    if (action === 'FOCUS_EDITABLE') {
      const target = errorField || elements.find((element) => editable(element))
      return target ? focusResult(target, 'focused', elements) : error('netflix_input_unavailable')
    }

    if (action === 'FOCUS_NEXT') {
      if (!current) return recoverFocus(elements, previousFocus)
      const next = elements[elements.indexOf(current) + 1]
      return next
        ? focusResult(next, 'moved', elements)
        : { ok: true, status: 'boundary', focus: fingerprint(current, elements) }
    }

    if (action === 'OK') {
      if (!current) return recoverFocus(elements, previousFocus)
      if (editable(current)) return focusResult(current, 'focused', elements)
      const currentFocus = fingerprint(current, elements)
      current.click()
      return { ok: true, status: 'clicked', focus: currentFocus }
    }

    if (!current) return recoverFocus(elements, previousFocus)
    const target = directionalTarget(elements, current, action)
    return target
      ? focusResult(target, 'moved', elements)
      : { ok: true, status: 'boundary', focus: fingerprint(current, elements) }
  }

  globalThis.__freeTvNetflixControl = { version: VERSION, run }
})()
