import React from 'react'
import { View } from 'react-native'
import ReactTestRenderer, { act } from 'react-test-renderer'
import { Trackpad } from './Trackpad'
import * as Haptics from 'expo-haptics'
import type { PointerAction } from '../types/protocol'

jest.mock('expo-haptics', () => ({
  impactAsync: jest.fn().mockResolvedValue(undefined),
  notificationAsync: jest.fn().mockResolvedValue(undefined),
  ImpactFeedbackStyle: {
    Light: 'light',
    Medium: 'medium',
    Heavy: 'heavy',
  },
  NotificationFeedbackType: {
    Success: 'success',
    Warning: 'warning',
    Error: 'error',
  },
}))

function getTrackpadView(root: ReactTestRenderer.ReactTestInstance): ReactTestRenderer.ReactTestInstance {
  const views = root.findAllByType(View)
  const trackpad = views.find(
    (v) =>
      v.props.accessibilityRole === 'adjustable' &&
      (v.props.accessibilityLabel === 'Trackpad' || v.props.accessibilityLabel === 'Touchpad'),
  )
  if (!trackpad) throw new Error('Trackpad view not found')
  return trackpad
}

describe('Trackpad', () => {
  let mockOnPointer: jest.Mock<void, [PointerAction, number, number]>
  let renderer: ReactTestRenderer.ReactTestRenderer | null = null

  beforeEach(() => {
    jest.clearAllMocks()
    jest.useFakeTimers()
    mockOnPointer = jest.fn()
    renderer = null
  })

  afterEach(() => {
    if (renderer) {
      try {
        act(() => {
          renderer?.unmount()
        })
      } catch {
        // already unmounted
      }
      renderer = null
    }
    act(() => {
      jest.clearAllTimers()
    })
    jest.useRealTimers()
  })

  describe('Accessibility actions', () => {
    it('maps "activate" action to tap and light haptic impact', () => {
      act(() => {
        renderer = ReactTestRenderer.create(
          <Trackpad onPointer={mockOnPointer} />,
        )
      })
      const trackpadView = getTrackpadView(renderer!.root)

      act(() => {
        trackpadView.props.onAccessibilityAction({
          nativeEvent: { actionName: 'activate' },
        })
      })

      expect(mockOnPointer).toHaveBeenCalledWith('tap', 0, 0)
      expect(Haptics.impactAsync).toHaveBeenCalledWith(Haptics.ImpactFeedbackStyle.Light)
    })

    it('maps "increment" action to scroll up and light haptic impact', () => {
      act(() => {
        renderer = ReactTestRenderer.create(
          <Trackpad onPointer={mockOnPointer} />,
        )
      })
      const trackpadView = getTrackpadView(renderer!.root)

      act(() => {
        trackpadView.props.onAccessibilityAction({
          nativeEvent: { actionName: 'increment' },
        })
      })

      expect(mockOnPointer).toHaveBeenCalledWith('scroll', 0, 100)
      expect(Haptics.impactAsync).toHaveBeenCalledWith(Haptics.ImpactFeedbackStyle.Light)
    })

    it('maps "decrement" action to scroll down and light haptic impact', () => {
      act(() => {
        renderer = ReactTestRenderer.create(
          <Trackpad onPointer={mockOnPointer} />,
        )
      })
      const trackpadView = getTrackpadView(renderer!.root)

      act(() => {
        trackpadView.props.onAccessibilityAction({
          nativeEvent: { actionName: 'decrement' },
        })
      })

      expect(mockOnPointer).toHaveBeenCalledWith('scroll', 0, -100)
      expect(Haptics.impactAsync).toHaveBeenCalledWith(Haptics.ImpactFeedbackStyle.Light)
    })

    it('ignores accessibility actions when disabled', () => {
      act(() => {
        renderer = ReactTestRenderer.create(
          <Trackpad onPointer={mockOnPointer} disabled={true} />,
        )
      })
      const trackpadView = getTrackpadView(renderer!.root)

      act(() => {
        trackpadView.props.onAccessibilityAction({
          nativeEvent: { actionName: 'activate' },
        })
        trackpadView.props.onAccessibilityAction({
          nativeEvent: { actionName: 'increment' },
        })
        trackpadView.props.onAccessibilityAction({
          nativeEvent: { actionName: 'decrement' },
        })
      })

      expect(mockOnPointer).not.toHaveBeenCalled()
      expect(Haptics.impactAsync).not.toHaveBeenCalled()
    })
  })

  describe('Tap timing behavior (deterministic fake timers)', () => {
    it('delays single tap emission by 250ms', () => {
      act(() => {
        renderer = ReactTestRenderer.create(
          <Trackpad onPointer={mockOnPointer} />,
        )
      })
      const trackpadView = getTrackpadView(renderer!.root)

      // Touch down
      act(() => {
        trackpadView.props.onResponderGrant({
          nativeEvent: { touches: [{ identifier: 1, pageX: 150, pageY: 200 }] },
        })
      })

      // Touch up (release)
      act(() => {
        trackpadView.props.onResponderRelease({
          nativeEvent: { touches: [] },
        })
      })

      // Immediately after release, tap has not been emitted yet
      expect(mockOnPointer).not.toHaveBeenCalled()
      expect(Haptics.impactAsync).not.toHaveBeenCalled()

      // Advance by 249ms
      act(() => {
        jest.advanceTimersByTime(249)
      })
      expect(mockOnPointer).not.toHaveBeenCalled()

      // Advance by 1ms (reaching 250ms threshold)
      act(() => {
        jest.advanceTimersByTime(1)
      })
      expect(mockOnPointer).toHaveBeenCalledTimes(1)
      expect(mockOnPointer).toHaveBeenCalledWith('tap', 0, 0)
      expect(Haptics.impactAsync).toHaveBeenCalledWith(Haptics.ImpactFeedbackStyle.Light)
    })

    it('emits double tap and cancels pending single tap when second tap occurs within 250ms', () => {
      act(() => {
        renderer = ReactTestRenderer.create(
          <Trackpad onPointer={mockOnPointer} />,
        )
      })
      const trackpadView = getTrackpadView(renderer!.root)

      // Tap 1
      act(() => {
        trackpadView.props.onResponderGrant({
          nativeEvent: { touches: [{ identifier: 1, pageX: 100, pageY: 100 }] },
        })
      })
      act(() => {
        trackpadView.props.onResponderRelease({
          nativeEvent: { touches: [] },
        })
      })

      // Wait 100ms (< 250ms)
      act(() => {
        jest.advanceTimersByTime(100)
      })
      expect(mockOnPointer).not.toHaveBeenCalled()

      // Tap 2
      act(() => {
        trackpadView.props.onResponderGrant({
          nativeEvent: { touches: [{ identifier: 1, pageX: 100, pageY: 100 }] },
        })
      })
      act(() => {
        trackpadView.props.onResponderRelease({
          nativeEvent: { touches: [] },
        })
      })

      // Double tap emitted immediately on second release
      expect(mockOnPointer).toHaveBeenCalledTimes(1)
      expect(mockOnPointer).toHaveBeenCalledWith('double_tap', 0, 0)
      expect(Haptics.impactAsync).toHaveBeenCalledWith(Haptics.ImpactFeedbackStyle.Medium)

      // Further time passing should NOT emit any stray single tap
      act(() => {
        jest.advanceTimersByTime(500)
      })
      expect(mockOnPointer).toHaveBeenCalledTimes(1)
    })

    it('treats taps separated by more than 250ms as distinct single taps', () => {
      act(() => {
        renderer = ReactTestRenderer.create(
          <Trackpad onPointer={mockOnPointer} />,
        )
      })
      const trackpadView = getTrackpadView(renderer!.root)

      // Tap 1
      act(() => {
        trackpadView.props.onResponderGrant({
          nativeEvent: { touches: [{ identifier: 1, pageX: 100, pageY: 100 }] },
        })
      })
      act(() => {
        trackpadView.props.onResponderRelease({
          nativeEvent: { touches: [] },
        })
      })

      // Wait 250ms -> Tap 1 resolves
      act(() => {
        jest.advanceTimersByTime(250)
      })
      expect(mockOnPointer).toHaveBeenCalledTimes(1)
      expect(mockOnPointer).toHaveBeenLastCalledWith('tap', 0, 0)

      // Tap 2
      act(() => {
        trackpadView.props.onResponderGrant({
          nativeEvent: { touches: [{ identifier: 1, pageX: 100, pageY: 100 }] },
        })
      })
      act(() => {
        trackpadView.props.onResponderRelease({
          nativeEvent: { touches: [] },
        })
      })

      // Wait 250ms -> Tap 2 resolves as single tap
      act(() => {
        jest.advanceTimersByTime(250)
      })
      expect(mockOnPointer).toHaveBeenCalledTimes(2)
      expect(mockOnPointer).toHaveBeenLastCalledWith('tap', 0, 0)
    })

    it('does not emit tap when touch duration exceeds MAX_TAP_DURATION_MS (300ms)', () => {
      act(() => {
        renderer = ReactTestRenderer.create(
          <Trackpad onPointer={mockOnPointer} />,
        )
      })
      const trackpadView = getTrackpadView(renderer!.root)

      const realNow = Date.now
      let currentTime = 1000
      jest.spyOn(Date, 'now').mockImplementation(() => currentTime)

      try {
        // Touch down at t = 1000
        act(() => {
          trackpadView.props.onResponderGrant({
            nativeEvent: { touches: [{ identifier: 1, pageX: 100, pageY: 100 }] },
          })
        })

        // Hold touch for 350ms (t = 1350)
        currentTime = 1350

        // Release
        act(() => {
          trackpadView.props.onResponderRelease({
            nativeEvent: { touches: [] },
          })
        })

        // Advance debounce window
        act(() => {
          jest.advanceTimersByTime(500)
        })

        expect(mockOnPointer).not.toHaveBeenCalled()
      } finally {
        Date.now = realNow
      }
    })
  })

  describe('Pointer movement and two-finger scrolling', () => {
    it('emits coalesced move events on finger drag and suppresses tap on release', () => {
      act(() => {
        renderer = ReactTestRenderer.create(
          <Trackpad onPointer={mockOnPointer} />,
        )
      })
      const trackpadView = getTrackpadView(renderer!.root)

      // Touch down
      act(() => {
        trackpadView.props.onResponderGrant({
          nativeEvent: { touches: [{ identifier: 1, pageX: 100, pageY: 100 }] },
        })
      })

      // Move dx = 20, dy = 10 (MOVE_SENSITIVITY = 1.35 -> dx = 27, dy = 14)
      act(() => {
        trackpadView.props.onResponderMove({
          nativeEvent: { touches: [{ identifier: 1, pageX: 120, pageY: 110 }] },
        })
      })

      // Coalescing frame (16ms)
      act(() => {
        jest.advanceTimersByTime(16)
      })

      expect(mockOnPointer).toHaveBeenCalledWith('move', 27, 14)

      // Release after movement
      act(() => {
        trackpadView.props.onResponderRelease({
          nativeEvent: { touches: [] },
        })
      })

      act(() => {
        jest.advanceTimersByTime(500)
      })

      // Movement must prevent tap from firing
      expect(mockOnPointer).toHaveBeenCalledTimes(1)
    })

    it('emits coalesced scroll events on two-finger drag', () => {
      act(() => {
        renderer = ReactTestRenderer.create(
          <Trackpad onPointer={mockOnPointer} />,
        )
      })
      const trackpadView = getTrackpadView(renderer!.root)

      // Touch down with 2 fingers (centroid y = 100)
      act(() => {
        trackpadView.props.onResponderGrant({
          nativeEvent: {
            touches: [
              { identifier: 1, pageX: 100, pageY: 100 },
              { identifier: 2, pageX: 140, pageY: 100 },
            ],
          },
        })
      })

      // Move 2 fingers down: dy = +20 (SCROLL_SENSITIVITY = 1.5 -> dy = 30)
      act(() => {
        trackpadView.props.onResponderMove({
          nativeEvent: {
            touches: [
              { identifier: 1, pageX: 100, pageY: 120 },
              { identifier: 2, pageX: 140, pageY: 120 },
            ],
          },
        })
      })

      // Advance frame (16ms)
      act(() => {
        jest.advanceTimersByTime(16)
      })

      expect(mockOnPointer).toHaveBeenCalledWith('scroll', 0, 30)

      // Release
      act(() => {
        trackpadView.props.onResponderRelease({
          nativeEvent: { touches: [] },
        })
      })

      act(() => {
        jest.advanceTimersByTime(500)
      })

      expect(mockOnPointer).toHaveBeenCalledTimes(1)
    })

    it('cancels pending gestures on responder terminate', () => {
      act(() => {
        renderer = ReactTestRenderer.create(
          <Trackpad onPointer={mockOnPointer} />,
        )
      })
      const trackpadView = getTrackpadView(renderer!.root)

      act(() => {
        trackpadView.props.onResponderGrant({
          nativeEvent: { touches: [{ identifier: 1, pageX: 100, pageY: 100 }] },
        })
      })

      act(() => {
        trackpadView.props.onResponderTerminate()
      })

      act(() => {
        jest.advanceTimersByTime(500)
      })

      expect(mockOnPointer).not.toHaveBeenCalled()
    })
  })

  describe('Disabled state and unmount cleanup', () => {
    it('refuses responder role and ignores gesture inputs when disabled', () => {
      act(() => {
        renderer = ReactTestRenderer.create(
          <Trackpad onPointer={mockOnPointer} disabled={true} />,
        )
      })
      const trackpadView = getTrackpadView(renderer!.root)

      expect(trackpadView.props.onStartShouldSetResponder()).toBe(false)
      expect(trackpadView.props.onMoveShouldSetResponder()).toBe(false)

      act(() => {
        trackpadView.props.onResponderGrant({
          nativeEvent: { touches: [{ identifier: 1, pageX: 100, pageY: 100 }] },
        })
        trackpadView.props.onResponderMove({
          nativeEvent: { touches: [{ identifier: 1, pageX: 150, pageY: 150 }] },
        })
        trackpadView.props.onResponderRelease({
          nativeEvent: { touches: [] },
        })
      })

      act(() => {
        jest.advanceTimersByTime(500)
      })

      expect(mockOnPointer).not.toHaveBeenCalled()
    })

    it('cleans up handlers on unmount', () => {
      act(() => {
        renderer = ReactTestRenderer.create(
          <Trackpad onPointer={mockOnPointer} />,
        )
      })
      act(() => {
        renderer!.unmount()
      })
      renderer = null

      expect(() => {
        jest.advanceTimersByTime(1000)
      }).not.toThrow()
    })
  })
})
