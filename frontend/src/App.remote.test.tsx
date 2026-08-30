import '@testing-library/jest-dom/vitest'

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

const loadedRoutes = vi.hoisted((): string[] => [])

vi.mock('./remote/RemotePage', () => {
  loadedRoutes.push('remote')
  return { RemotePage: () => <div>Remote route</div> }
})

vi.mock('./tv/TVLauncher', () => {
  loadedRoutes.push('tv')
  return { TVLauncher: () => <div>TV route</div> }
})

afterEach(() => {
  cleanup()
  window.history.replaceState({}, '', '/')
})

it('loads only the remote route module on /remote', async () => {
  window.history.replaceState({}, '', '/remote')
  const { App } = await import('./App')

  render(<App />)

  expect(await screen.findByText('Remote route')).toBeInTheDocument()
  expect(loadedRoutes).toEqual(['remote'])
})
