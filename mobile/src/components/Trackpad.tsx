import React, { useRef } from 'react'
import {
  GestureResponderEvent,
  StyleSheet,
  Text,
  View,
} from 'react-native'
import * as Haptics from 'expo-haptics'
import type { PointerAction } from '../types/protocol'

interface TrackpadProps {
  onPointer: (action: PointerAction, dx: number, dy: number) => void
  disabled?: boolean
}

const TAP_DELAY_MS = 250

export function Trackpad({ onPointer, disabled }: TrackpadProps): React.ReactElement {
  const lastTouchRef = useRef<{ x: number; y: number; time: number } | null>(null)
  const lastTapTimeRef = useRef<number>(0)
  const isMovingRef = useRef(false)

  const handleTouchStart = (event: GestureResponderEvent) => {
    if (disabled) return
    const touch = event.nativeEvent.touches[0]
    if (touch) {
      lastTouchRef.current = {
        x: touch.pageX,
        y: touch.pageY,
        time: Date.now(),
      }
      isMovingRef.current = false
    }
  }

  const handleTouchMove = (event: GestureResponderEvent) => {
    if (disabled || !lastTouchRef.current) return
    const touches = event.nativeEvent.touches

    if (touches.length === 1) {
      const touch = touches[0]
      const dx = touch.pageX - lastTouchRef.current.x
      const dy = touch.pageY - lastTouchRef.current.y

      if (Math.abs(dx) > 1.5 || Math.abs(dy) > 1.5) {
        isMovingRef.current = true
        // Apply smooth sensitivity multiplier
        const sensitivity = 1.35
        onPointer('move', Math.round(dx * sensitivity), Math.round(dy * sensitivity))
        lastTouchRef.current.x = touch.pageX
        lastTouchRef.current.y = touch.pageY
      }
    } else if (touches.length === 2) {
      // 2-finger vertical scrolling
      const touch = touches[0]
      const dy = touch.pageY - lastTouchRef.current.y
      if (Math.abs(dy) > 2) {
        isMovingRef.current = true
        onPointer('scroll', 0, Math.round(dy * 1.5))
        lastTouchRef.current.y = touch.pageY
      }
    }
  }

  const handleTouchEnd = () => {
    if (disabled || !lastTouchRef.current) return
    const now = Date.now()
    const touchDuration = now - lastTouchRef.current.time

    if (!isMovingRef.current && touchDuration < 300) {
      const timeSinceLastTap = now - lastTapTimeRef.current
      if (timeSinceLastTap < TAP_DELAY_MS) {
        // Double tap
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium)
        onPointer('double_tap', 0, 0)
        lastTapTimeRef.current = 0
      } else {
        // Single tap
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
        onPointer('tap', 0, 0)
        lastTapTimeRef.current = now
      }
    }

    lastTouchRef.current = null
    isMovingRef.current = false
  }

  return (
    <View
      style={styles.container}
      onStartShouldSetResponder={() => !disabled}
      onMoveShouldSetResponder={() => !disabled}
      onResponderGrant={handleTouchStart}
      onResponderMove={handleTouchMove}
      onResponderRelease={handleTouchEnd}
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
