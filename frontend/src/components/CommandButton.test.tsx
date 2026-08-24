import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CommandButton } from './CommandButton'

describe('CommandButton', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('sends one command for a normal tap', () => {
    const onCommand = vi.fn()
    render(<CommandButton command="VOLUME_UP" label="音量 +" onCommand={onCommand} repeatOnHold />)
    const button = screen.getByRole('button', { name: '音量 +' })

    fireEvent.pointerDown(button, { button: 0, pointerId: 1 })
    act(() => vi.advanceTimersByTime(200))
    fireEvent.pointerUp(button, { button: 0, pointerId: 1 })
    fireEvent.click(button)

    expect(onCommand).toHaveBeenCalledTimes(1)
    expect(onCommand).toHaveBeenLastCalledWith('VOLUME_UP')
  })

  it('repeats while held without sending an extra release click', () => {
    const onCommand = vi.fn()
    render(<CommandButton command="VOLUME_UP" label="音量 +" onCommand={onCommand} repeatOnHold />)
    const button = screen.getByRole('button', { name: '音量 +' })

    fireEvent.pointerDown(button, { button: 0, pointerId: 1 })
    act(() => vi.advanceTimersByTime(580))
    fireEvent.pointerUp(button, { button: 0, pointerId: 1 })
    fireEvent.click(button)

    expect(onCommand).toHaveBeenCalledTimes(3)
    expect(onCommand).toHaveBeenLastCalledWith('VOLUME_UP')
  })

  it('does not dispatch while disabled', () => {
    const onCommand = vi.fn()
    render(<CommandButton command="VOLUME_UP" label="音量 +" onCommand={onCommand} disabled repeatOnHold />)
    const button = screen.getByRole('button', { name: '音量 +' })

    fireEvent.click(button)
    act(() => vi.advanceTimersByTime(1_000))

    expect(onCommand).not.toHaveBeenCalled()
  })
})
