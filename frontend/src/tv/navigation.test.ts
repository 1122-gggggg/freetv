import { describe, expect, it } from 'vitest'

import { moveFocus, tileCommand } from './navigation'

describe('TV grid navigation', () => {
  it('moves through adjacent launcher tiles according to the 2x2 focus graph', () => {
    expect(moveFocus('youtube', 'NAV_RIGHT')).toBe('netflix')
    expect(moveFocus('youtube', 'NAV_DOWN')).toBe('news')
    expect(moveFocus('netflix', 'NAV_LEFT')).toBe('youtube')
    expect(moveFocus('netflix', 'NAV_DOWN')).toBe('settings')

    expect(moveFocus('news', 'NAV_UP')).toBe('youtube')
    expect(moveFocus('news', 'NAV_RIGHT')).toBe('settings')
    expect(moveFocus('settings', 'NAV_UP')).toBe('netflix')
    expect(moveFocus('settings', 'NAV_LEFT')).toBe('news')
  })

  it('retains focus when navigating into outer boundaries', () => {
    expect(moveFocus('youtube', 'NAV_LEFT')).toBe('youtube')
    expect(moveFocus('youtube', 'NAV_UP')).toBe('youtube')
    expect(moveFocus('netflix', 'NAV_UP')).toBe('netflix')
    expect(moveFocus('netflix', 'NAV_RIGHT')).toBe('netflix')
    expect(moveFocus('news', 'NAV_LEFT')).toBe('news')
    expect(moveFocus('news', 'NAV_DOWN')).toBe('news')
    expect(moveFocus('settings', 'NAV_RIGHT')).toBe('settings')
    expect(moveFocus('settings', 'NAV_DOWN')).toBe('settings')
  })

  it('maps application tiles to typed open commands only', () => {
    expect(tileCommand('youtube')).toBe('OPEN_YOUTUBE')
    expect(tileCommand('netflix')).toBe('OPEN_NETFLIX')
    expect(tileCommand('news')).toBe('OPEN_NEWS')
    expect(tileCommand('settings')).toBeNull()
  })
})
