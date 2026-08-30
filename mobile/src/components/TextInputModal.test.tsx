jest.mock('expo-haptics', () => ({ impactAsync: jest.fn(), ImpactFeedbackStyle: { Light: 'light' } }))
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) }))

import React from 'react'
import renderer, { act } from 'react-test-renderer'
import { TextInputModal } from './TextInputModal'

describe('TextInputModal live sync', () => {
  beforeEach(() => jest.useFakeTimers())
  afterEach(() => {
    jest.clearAllTimers()
    jest.useRealTimers()
  })

  const renderModal = (onLiveSync: (text: string) => void, onSend = jest.fn(async () => {})) => {
    let tree!: renderer.ReactTestRenderer
    act(() => {
      tree = renderer.create(
        <TextInputModal visible inputKind="search" submit={false} canSubmit onClose={jest.fn()} onSend={onSend} onLiveSync={onLiveSync} />,
      )
    })
    return tree
  }

  it('coalesces rapid edits into one delayed live update', () => {
    const sync = jest.fn()
    const root = renderModal(sync).root
    const input = root.findByType('TextInput' as never)

    act(() => {
      input.props.onChangeText('a')
      input.props.onChangeText('ab')
      jest.advanceTimersByTime(119)
    })
    expect(sync).not.toHaveBeenCalled()
    act(() => jest.advanceTimersByTime(1))
    expect(sync).toHaveBeenCalledTimes(1)
    expect(sync).toHaveBeenCalledWith('ab')
  })

  it('cancels pending live update before final send and on close', async () => {
    const sync = jest.fn()
    const send = jest.fn(async () => {})
    const close = jest.fn()
    let tree!: renderer.ReactTestRenderer
    act(() => {
      tree = renderer.create(
        <TextInputModal visible inputKind="search" submit={false} canSubmit onClose={close} onSend={send} onLiveSync={sync} />,
      )
    })
    const root = tree.root
    const input = root.findByType('TextInput' as never)
    act(() => input.props.onChangeText('stale'))
    await act(async () => input.props.onSubmitEditing())
    act(() => jest.runOnlyPendingTimers())
    expect(send).toHaveBeenCalledWith('stale', false)
    expect(sync).not.toHaveBeenCalled()

    act(() => input.props.onChangeText('discarded'))
    act(() => root.findByType('Modal' as never).props.onRequestClose())
    act(() => jest.runOnlyPendingTimers())
    expect(sync).not.toHaveBeenCalled()
  })

  it('delivers a pending update only through the latest callback', () => {
    const staleSync = jest.fn()
    const latestSync = jest.fn()
    const tree = renderModal(staleSync)
    const input = tree.root.findByType('TextInput' as never)

    act(() => input.props.onChangeText('current'))
    act(() => {
      tree.update(
        <TextInputModal
          visible
          inputKind="search"
          submit={false}
          canSubmit
          onClose={jest.fn()}
          onSend={jest.fn(async () => {})}
          onLiveSync={latestSync}
        />,
      )
    })
    act(() => jest.advanceTimersByTime(120))

    expect(staleSync).not.toHaveBeenCalled()
    expect(latestSync).toHaveBeenCalledWith('current')
  })
})
