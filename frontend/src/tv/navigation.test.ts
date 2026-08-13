import { describe, expect, it } from 'vitest'

import { moveFocus, tileCommand } from './navigation'

describe('TV grid navigation', () => {
  it('moves through adjacent launcher tiles without losing focus at a boundary', () => {
    expect(moveFocus('youtube', 'NAV_RIGHT')).toBe('netflix')
    expect(moveFocus('youtube', 'NAV_LEFT')).toBe('youtube')
    expect(moveFocus('browser', 'NAV_DOWN')).toBe('settings')
  })

  it('maps application tiles to typed open commands only', () => {
    expect(tileCommand('youtube')).toBe('OPEN_YOUTUBE')
    expect(tileCommand('settings')).toBeNull()
  })
})
