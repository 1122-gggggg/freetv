import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { RemotePage } from './RemotePage'

vi.mock('../api/useControllerSocket', () => ({
  useControllerSocket: () => ({
    status: 'connected',
    state: null,
    lastAcknowledgement: null,
    lastError: null,
    sendCommand: () => true,
    sendPointer: () => true,
    sendText: () => true,
  }),
}))

describe('RemotePage unpairing', () => {
  it('keeps the paired remote visible and reports a failed server-side revocation', async () => {
    const onForget = vi.fn().mockRejectedValue(new Error('Could not unpair this remote.'))

    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={onForget}
        onAuthenticationFailed={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Forget' }))

    await waitFor(() => expect(onForget).toHaveBeenCalledOnce())
    expect(await screen.findByText('Could not unpair this remote.')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Forget' }) as HTMLButtonElement).disabled).toBe(false)
  })


  it('exposes previous and next media controls', () => {
    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={vi.fn()}
        onAuthenticationFailed={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: 'Previous' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Next' })).toBeTruthy()
  })
})
