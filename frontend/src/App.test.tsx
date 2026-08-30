import '@testing-library/jest-dom/vitest'

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const loadedRoutes = vi.hoisted((): string[] => [])

vi.mock('./remote/RemotePage', () => {
  loadedRoutes.push('remote')
  return { RemotePage: () => <div>Remote route</div> }
})

vi.mock('./tv/TVLauncher', () => {
  loadedRoutes.push('tv')
  return { TVLauncher: () => <div>TV route</div> }
})

describe('App route loading', () => {
  beforeEach(() => {
    loadedRoutes.length = 0
    vi.resetModules()
  })

  afterEach(() => {
    cleanup()
    window.history.replaceState({}, '', '/')
  })

  it('loads only the TV route module outside /remote', async () => {
    window.history.replaceState({}, '', '/tv')
    const { App } = await import('./App')

    render(<App />)

    expect(await screen.findByText('TV route')).toBeInTheDocument()
    expect(loadedRoutes).toEqual(['tv'])
  })

})
