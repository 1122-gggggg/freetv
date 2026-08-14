import React, { useEffect, useRef } from 'react'
import {
  type AccessibilityActionEvent,
  GestureResponderEvent,
  StyleSheet,
  Text,
  View,
} from 'react-native'
import * as Haptics from 'expo-haptics'
import type { PointerAction } from '../types/protocol'
import {
  createPointerCoalescer,
  createTapHandler,
  type PointerCoalescer,
  type TapHandler,
} from './pointerCoalescer'

interface TrackpadProps {
  onPointer: (action: PointerAction, dx: number, dy: number) => void
  disabled?: boolean
}

const TAP_DELAY_MS = 250
const MAX_TAP_DURATION_MS = 300
const MOVE_THRESHOLD = 1.5
const SCROLL_THRESHOLD = 2
const MOVE_SENSITIVITY = 1.35
const SCROLL_SENSITIVITY = 1.5
const ACCESSIBILITY_SCROLL_DELTA = 100
const TRACKPAD_ACCESSIBILITY_ACTIONS = [
  { name: 'activate', label: 'Click' },
  { name: 'increment', label: 'Scroll up' },
  { name: 'decrement', label: 'Scroll down' },
]

function areTouchIdsEqual(a: (string | number)[], b: (string | number)[]): boolean {
  if (a.length !== b.length) return false
  const set = new Set(a)
  return b.every((id) => set.has(id))
}

export function Trackpad({ onPointer, disabled }: TrackpadProps): React.ReactElement {
  const lastTouchRef = useRef<{ x: number; y: number; time: number } | null>(null)
  const lastCentroidRef = useRef<{ x: number; y: number } | null>(null)
  const lastTouchIdsRef = useRef<(string | number)[]>([])
  const isMovingRef = useRef(false)
  const hadMultiTouchRef = useRef(false)
  const onPointerRef = useRef(onPointer)
  const coalescerRef = useRef<PointerCoalescer | null>(null)
  const tapHandlerRef = useRef<TapHandler | null>(null)

  onPointerRef.current = onPointer
  if (!coalescerRef.current) {
    coalescerRef.current = createPointerCoalescer((action, dx, dy) => {
      onPointerRef.current(action, dx, dy)
    })
  }

  if (!tapHandlerRef.current) {
    tapHandlerRef.current = createTapHandler({
      tapDelayMs: TAP_DELAY_MS,
      onTap: () => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
        onPointerRef.current('tap', 0, 0)
      },
      onDoubleTap: () => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium)
        onPointerRef.current('double_tap', 0, 0)
      },
    })
  }

  const resetGestureState = () => {
    lastTouchRef.current = null
    lastCentroidRef.current = null
    lastTouchIdsRef.current = []
    isMovingRef.current = false
    hadMultiTouchRef.current = false
  }

  useEffect(() => {
    const coalescer = coalescerRef.current
    const tapHandler = tapHandlerRef.current
    return () => {
      tapHandler?.dispose()
      coalescer?.dispose()
      resetGestureState()
    }
  }, [])

  useEffect(() => {
    if (disabled) {
      tapHandlerRef.current?.cancel()
      coalescerRef.current?.cancel()
      resetGestureState()
    }
  }, [disabled])

  const handleTouchStart = (event: GestureResponderEvent) => {
    if (disabled) return
    const touches = event.nativeEvent.touches ?? []
    const currentIds = touches.map((t) => t.identifier)
    lastTouchIdsRef.current = currentIds
    isMovingRef.current = false

    if (touches.length > 1) {
      hadMultiTouchRef.current = true
      tapHandlerRef.current?.cancel()
    } else {
      hadMultiTouchRef.current = false
    }

    if (touches.length === 1) {
      lastTouchRef.current = {
        x: touches[0].pageX,
        y: touches[0].pageY,
        time: Date.now(),
      }
      lastCentroidRef.current = null
    } else if (touches.length === 2) {
      const cx = (touches[0].pageX + touches[1].pageX) / 2
      const cy = (touches[0].pageY + touches[1].pageY) / 2
      lastCentroidRef.current = { x: cx, y: cy }
      lastTouchRef.current = null
    } else {
      lastTouchRef.current = null
      lastCentroidRef.current = null
    }
  }

  const handleTouchMove = (event: GestureResponderEvent) => {
    if (disabled) return
    const touches = event.nativeEvent.touches ?? []
    const currentIds = touches.map((t) => t.identifier)
    const previousIds = lastTouchIdsRef.current

    const membershipChanged = !areTouchIdsEqual(currentIds, previousIds)

    if (membershipChanged) {
      lastTouchIdsRef.current = currentIds
      if (touches.length > 1) {
        hadMultiTouchRef.current = true
        tapHandlerRef.current?.cancel()
      }

      if (touches.length === 1) {
        lastTouchRef.current = {
          x: touches[0].pageX,
          y: touches[0].pageY,
          time: lastTouchRef.current?.time ?? Date.now(),
        }
        lastCentroidRef.current = null
      } else if (touches.length === 2) {
        const cx = (touches[0].pageX + touches[1].pageX) / 2
        const cy = (touches[0].pageY + touches[1].pageY) / 2
        lastCentroidRef.current = { x: cx, y: cy }
        lastTouchRef.current = null
      } else {
        lastTouchRef.current = null
        lastCentroidRef.current = null
      }
      return
    }

    if (touches.length === 1) {
      const touch = touches[0]
      if (!lastTouchRef.current) {
        lastTouchRef.current = {
          x: touch.pageX,
          y: touch.pageY,
          time: Date.now(),
        }
        return
      }

      const dx = touch.pageX - lastTouchRef.current.x
      const dy = touch.pageY - lastTouchRef.current.y

      if (Math.abs(dx) > MOVE_THRESHOLD || Math.abs(dy) > MOVE_THRESHOLD) {
        isMovingRef.current = true
        tapHandlerRef.current?.cancel()
        coalescerRef.current?.move(
          Math.round(dx * MOVE_SENSITIVITY),
          Math.round(dy * MOVE_SENSITIVITY)
        )
        lastTouchRef.current.x = touch.pageX
        lastTouchRef.current.y = touch.pageY
      }
    } else if (touches.length === 2) {
      hadMultiTouchRef.current = true
      tapHandlerRef.current?.cancel()

      const cx = (touches[0].pageX + touches[1].pageX) / 2
      const cy = (touches[0].pageY + touches[1].pageY) / 2

      if (!lastCentroidRef.current) {
        lastCentroidRef.current = { x: cx, y: cy }
        return
      }

      const dy = cy - lastCentroidRef.current.y

      if (Math.abs(dy) > SCROLL_THRESHOLD) {
        isMovingRef.current = true
        coalescerRef.current?.scroll(Math.round(dy * SCROLL_SENSITIVITY))
        lastCentroidRef.current.x = cx
        lastCentroidRef.current.y = cy
      }
    }
  }

  const handleTouchEnd = (event: GestureResponderEvent) => {
    if (disabled) return
    const remainingTouches = event.nativeEvent.touches ?? []

    if (remainingTouches.length > 0) {
      const currentIds = remainingTouches.map((t) => t.identifier)
      lastTouchIdsRef.current = currentIds
      if (remainingTouches.length > 1) {
        hadMultiTouchRef.current = true
        tapHandlerRef.current?.cancel()
      }

      if (remainingTouches.length === 1) {
        lastTouchRef.current = {
          x: remainingTouches[0].pageX,
          y: remainingTouches[0].pageY,
          time: lastTouchRef.current?.time ?? Date.now(),
        }
        lastCentroidRef.current = null
      } else if (remainingTouches.length === 2) {
        const cx = (remainingTouches[0].pageX + remainingTouches[1].pageX) / 2
        const cy = (remainingTouches[0].pageY + remainingTouches[1].pageY) / 2
        lastCentroidRef.current = { x: cx, y: cy }
        lastTouchRef.current = null
      } else {
        lastTouchRef.current = null
        lastCentroidRef.current = null
      }
      return
    }

    const now = Date.now()
    const touchDuration = lastTouchRef.current ? now - lastTouchRef.current.time : Infinity

    if (!hadMultiTouchRef.current && !isMovingRef.current && touchDuration < MAX_TAP_DURATION_MS) {
      coalescerRef.current?.flush()
      tapHandlerRef.current?.registerTap()
    } else {
      coalescerRef.current?.flush()
    }

    resetGestureState()
  }

  const handleTouchTerminate = () => {
    tapHandlerRef.current?.cancel()
    coalescerRef.current?.cancel()
    resetGestureState()
  }

  const handleAccessibilityAction = (event: AccessibilityActionEvent) => {
    if (disabled) return

    switch (event.nativeEvent.actionName) {
      case 'activate':
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
        onPointerRef.current('tap', 0, 0)
        break
      case 'increment':
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
        onPointerRef.current('scroll', 0, ACCESSIBILITY_SCROLL_DELTA)
        break
      case 'decrement':
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
        onPointerRef.current('scroll', 0, -ACCESSIBILITY_SCROLL_DELTA)
        break
    }
  }

  return (
    <View
      style={[styles.container, disabled && styles.disabledControl]}
      onStartShouldSetResponder={() => !disabled}
      onMoveShouldSetResponder={() => !disabled}
      onResponderGrant={handleTouchStart}
      onResponderMove={handleTouchMove}
      onResponderRelease={handleTouchEnd}
      onResponderTerminate={handleTouchTerminate}
      onResponderReject={handleTouchTerminate}
      accessible
      accessibilityRole="adjustable"
      accessibilityLabel="Touchpad"
      accessibilityHint="Double tap to click. Swipe up or down to scroll vertically."
      accessibilityState={{ disabled: Boolean(disabled) }}
      accessibilityActions={TRACKPAD_ACCESSIBILITY_ACTIONS}
      onAccessibilityAction={handleAccessibilityAction}
    >
      <Text style={styles.hintText}>TOUCHPAD</Text>
      <Text style={styles.subHintText}>Slide to move · Tap to click · 2 fingers to scroll</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    height: 180,
    backgroundColor: '#161e2b',
    borderColor: '#2b374e',
    borderWidth: 1.5,
    borderRadius: 16,
    marginHorizontal: 16,
    marginVertical: 10,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 12,
  },
  disabledControl: {
    opacity: 0.5,
  },
  hintText: {
    color: '#8da0b8',
    fontSize: 14,
    fontWeight: '700',
    letterSpacing: 2,
    marginBottom: 4,
  },
  subHintText: {
    color: '#55667e',
    fontSize: 11,
    textAlign: 'center',
  },
})
