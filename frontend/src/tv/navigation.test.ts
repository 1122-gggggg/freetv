import { describe, expect, it } from 'vitest'

import { moveFocus, tileCommand } from './navigation'

describe('TV grid navigation', () => {
  it('moves through adjacent launcher tiles according to the 2x3 focus graph', () => {
    // Row 1: YouTube, Netflix
    expect(moveFocus('youtube', 'NAV_RIGHT')).toBe('netflix')
    expect(moveFocus('youtube', 'NAV_DOWN')).toBe('news')
    expect(moveFocus('netflix', 'NAV_LEFT')).toBe('youtube')
    expect(moveFocus('netflix', 'NAV_DOWN')).toBe('live_tv')

    // Row 2: News, Live TV
    expect(moveFocus('news', 'NAV_UP')).toBe('youtube')
    expect(moveFocus('news', 'NAV_RIGHT')).toBe('live_tv')
    expect(moveFocus('news', 'NAV_DOWN')).toBe('browser')
    expect(moveFocus('live_tv', 'NAV_UP')).toBe('netflix')
    expect(moveFocus('live_tv', 'NAV_LEFT')).toBe('news')
    expect(moveFocus('live_tv', 'NAV_DOWN')).toBe('settings')

    // Row 3: Browser, Settings
    expect(moveFocus('browser', 'NAV_UP')).toBe('news')
    expect(moveFocus('browser', 'NAV_RIGHT')).toBe('settings')
    expect(moveFocus('settings', 'NAV_UP')).toBe('live_tv')
    expect(moveFocus('settings', 'NAV_LEFT')).toBe('browser')
  })

  it('retains focus when navigating into outer boundaries', () => {
    expect(moveFocus('youtube', 'NAV_LEFT')).toBe('youtube')
    expect(moveFocus('youtube', 'NAV_UP')).toBe('youtube')
    expect(moveFocus('netflix', 'NAV_UP')).toBe('netflix')
    expect(moveFocus('netflix', 'NAV_RIGHT')).toBe('netflix')
    expect(moveFocus('news', 'NAV_LEFT')).toBe('news')
    expect(moveFocus('live_tv', 'NAV_RIGHT')).toBe('live_tv')
    expect(moveFocus('browser', 'NAV_LEFT')).toBe('browser')
    expect(moveFocus('browser', 'NAV_DOWN')).toBe('browser')
    expect(moveFocus('settings', 'NAV_RIGHT')).toBe('settings')
    expect(moveFocus('settings', 'NAV_DOWN')).toBe('settings')
  })

  it('maps application tiles to typed open commands only', () => {
    expect(tileCommand('youtube')).toBe('OPEN_YOUTUBE')
    expect(tileCommand('netflix')).toBe('OPEN_NETFLIX')
    expect(tileCommand('news')).toBe('OPEN_NEWS')
    expect(tileCommand('live_tv')).toBe('OPEN_LIVE_TV')
    expect(tileCommand('browser')).toBe('OPEN_BROWSER')
    expect(tileCommand('settings')).toBeNull()
  })
})
