import React, { useRef } from 'react'
import {
  PanResponder,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native'
import * as Haptics from 'expo-haptics'
import type { Command } from '../types/protocol'

interface MediaControlsProps {
  onCommand: (command: Command) => void
  disabled?: boolean
  muted?: boolean
  volume?: number
  brightness?: number
}

const DRAG_THRESHOLD = 20

export function MediaControls({
  onCommand,
  disabled,
  muted,
  volume = 50,
  brightness = 100,
}: MediaControlsProps): React.ReactElement {
  const trigger = (command: Command) => {
    if (disabled) return
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
    onCommand(command)
  }

  // Create drag responders for Volume, Speed, and Brightness
  const createVerticalDragResponder = (upCommand: Command, downCommand: Command) => {
    let accumulatedDy = 0
    return PanResponder.create({
      onStartShouldSetPanResponder: () => !disabled,
      onMoveShouldSetPanResponder: (_, gestureState) =>
        !disabled && Math.abs(gestureState.dy) > 6,
      onPanResponderGrant: () => {
        accumulatedDy = 0
      },
      onPanResponderMove: (_, gestureState) => {
        if (disabled) return
        const delta = gestureState.dy - accumulatedDy
        if (delta <= -DRAG_THRESHOLD) {
          accumulatedDy = gestureState.dy
          trigger(upCommand)
        } else if (delta >= DRAG_THRESHOLD) {
          accumulatedDy = gestureState.dy
          trigger(downCommand)
        }
      },
      onPanResponderRelease: () => {
        accumulatedDy = 0
      },
    })
  }

  const volPanResponder = useRef(createVerticalDragResponder('VOLUME_UP', 'VOLUME_DOWN')).current
  const speedPanResponder = useRef(createVerticalDragResponder('SPEED_UP', 'SPEED_DOWN')).current
  const brightnessPanResponder = useRef(createVerticalDragResponder('BRIGHTNESS_UP', 'BRIGHTNESS_DOWN')).current

  const volumeFillPercent = Math.max(0, Math.min(100, volume))
  const brightnessFillPercent = Math.max(0, Math.min(100, brightness))

  return (
    <View style={styles.container}>
      {/* Top Nav Bar */}
      <View style={styles.topRow}>
        <TouchableOpacity
          style={[styles.navBtn, styles.backBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('BACK')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="返回"
          accessibilityHint="返回電視上一個畫面。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.btnText}>◀ 返回</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.navBtn, styles.homeBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('HOME')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="主畫面"
          accessibilityHint="開啟電視主畫面。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={[styles.btnText, styles.homeText]}>⌂ 主畫面</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.navBtn, styles.playBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('PLAY_PAUSE')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="播放或暫停"
          accessibilityHint="切換電視媒體播放或暫停。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.btnText}>⏯ 播放</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.navBtn, styles.fullscreenBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('FULLSCREEN')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="全螢幕"
          accessibilityHint="將目前影片或瀏覽器切換為全螢幕。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.btnText}>⛶ 全螢幕</Text>
        </TouchableOpacity>
      </View>

      {/* 3 Vertical Draggable Slider Bars: Volume | Speed | Brightness */}
      <View style={styles.slidersRow}>
        {/* Volume Vertical Slider */}
        <View style={styles.sliderColumn}>
          <Text style={styles.sliderHeader}>音量</Text>
          <View
            style={[styles.sliderTrackCard, disabled && styles.disabledControl]}
            {...volPanResponder.panHandlers}
          >
            {/* Visual Fill Background */}
            <View
              style={[
                styles.sliderFill,
                { height: `${volumeFillPercent}%` },
                muted && styles.sliderFillMuted,
              ]}
            />

            <TouchableOpacity
              style={styles.sliderStepBtn}
              onPress={() => trigger('VOLUME_UP')}
              disabled={disabled}
              accessibilityRole="button"
              accessibilityLabel="音量提高"
              accessibilityHint="提高電視音量。"
              accessibilityState={{ disabled: Boolean(disabled) }}
            >
              <Text style={styles.sliderBtnText}>＋</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[
                styles.sliderLevelPill,
                muted && styles.sliderMutedPill,
              ]}
              onPress={() => trigger('MUTE')}
              disabled={disabled}
              accessibilityRole="togglebutton"
              accessibilityLabel={muted ? '取消靜音' : '靜音'}
              accessibilityHint={muted ? '恢復電視聲音。' : '關閉電視聲音。'}
              accessibilityState={{ disabled: Boolean(disabled), checked: Boolean(muted) }}
            >
              <Text style={[styles.sliderLevelText, muted && styles.mutedText]}>
                {muted ? '🔇' : `${volume}%`}
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.sliderStepBtn}
              onPress={() => trigger('VOLUME_DOWN')}
              disabled={disabled}
              accessibilityRole="button"
              accessibilityLabel="音量降低"
              accessibilityHint="降低電視音量。"
              accessibilityState={{ disabled: Boolean(disabled) }}
            >
              <Text style={styles.sliderBtnText}>−</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Speed Vertical Slider */}
        <View style={styles.sliderColumn}>
          <Text style={styles.sliderHeader}>倍速</Text>
          <View
            style={[styles.sliderTrackCard, disabled && styles.disabledControl]}
            {...speedPanResponder.panHandlers}
          >
            <TouchableOpacity
              style={styles.sliderStepBtn}
              onPress={() => trigger('SPEED_UP')}
              disabled={disabled}
              accessibilityRole="button"
              accessibilityLabel="提高倍速"
              accessibilityHint="提高目前影片的播放速度。"
              accessibilityState={{ disabled: Boolean(disabled) }}
            >
              <Text style={styles.sliderBtnText}>＋</Text>
            </TouchableOpacity>

            <View style={[styles.sliderLevelPill, styles.speedPill]}>
              <Text style={styles.sliderSpeedText}>倍速</Text>
            </View>

            <TouchableOpacity
              style={styles.sliderStepBtn}
              onPress={() => trigger('SPEED_DOWN')}
              disabled={disabled}
              accessibilityRole="button"
              accessibilityLabel="降低倍速"
              accessibilityHint="降低目前影片的播放速度。"
              accessibilityState={{ disabled: Boolean(disabled) }}
            >
              <Text style={styles.sliderBtnText}>−</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Brightness Vertical Slider */}
        <View style={styles.sliderColumn}>
          <Text style={styles.sliderHeader}>亮度</Text>
          <View
            style={[styles.sliderTrackCard, disabled && styles.disabledControl]}
            {...brightnessPanResponder.panHandlers}
          >
            {/* Visual Fill Background */}
            <View
              style={[
                styles.sliderFill,
                styles.sliderFillBrightness,
                { height: `${brightnessFillPercent}%` },
              ]}
            />

            <TouchableOpacity
              style={styles.sliderStepBtn}
              onPress={() => trigger('BRIGHTNESS_UP')}
              disabled={disabled}
              accessibilityRole="button"
              accessibilityLabel="提高亮度"
              accessibilityHint="提高電視螢幕亮度。"
              accessibilityState={{ disabled: Boolean(disabled) }}
            >
              <Text style={styles.sliderBtnText}>＋</Text>
            </TouchableOpacity>

            <View style={[styles.sliderLevelPill, styles.brightnessPill]}>
              <Text style={styles.sliderLevelText}>{`${brightness}%`}</Text>
            </View>

            <TouchableOpacity
              style={styles.sliderStepBtn}
              onPress={() => trigger('BRIGHTNESS_DOWN')}
              disabled={disabled}
              accessibilityRole="button"
              accessibilityLabel="降低亮度"
              accessibilityHint="降低電視螢幕亮度。"
              accessibilityState={{ disabled: Boolean(disabled) }}
            >
              <Text style={styles.sliderBtnText}>−</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>

      {/* Seek, Quality & Subtitles Row */}
      <View style={styles.actionRow}>
        <TouchableOpacity
          style={[styles.actionBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('SEEK_BACKWARD_5')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="倒退五秒"
          accessibilityHint="將目前影片倒退五秒。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.actionBtnText}>−5 秒</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.actionBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('SEEK_FORWARD_5')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="快轉五秒"
          accessibilityHint="將目前影片快轉五秒。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.actionBtnText}>＋5 秒</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.actionBtn, styles.featureBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('QUALITY')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="切換畫質"
          accessibilityHint="切換目前影片播放畫質。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.actionBtnText}>⚙ 畫質</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.actionBtn, styles.featureBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('SUBTITLES')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="切換字幕"
          accessibilityHint="開啟或關閉 CC 字幕與語言。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.actionBtnText}>💬 字幕</Text>
        </TouchableOpacity>
      </View>
      {/* Channels & Power Row */}
      <View style={styles.actionRow}>
        <TouchableOpacity
          style={[styles.actionBtn, styles.channelBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('CHANNEL_DOWN')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="上一台"
          accessibilityHint="切換到上一台頻道。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.actionBtnText}>頻道 ▼</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.actionBtn, styles.powerBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('POWER_SLEEP')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="讓電視盒休眠"
          accessibilityHint="讓電視盒進入休眠。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.powerText}>⏻ 休眠</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.actionBtn, styles.channelBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('CHANNEL_UP')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="下一台"
          accessibilityHint="切換到下一台頻道。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.actionBtnText}>頻道 ▲</Text>
        </TouchableOpacity>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 12,
    marginVertical: 6,
    gap: 10,
  },
  topRow: {
    flexDirection: 'row',
    gap: 8,
  },
  navBtn: {
    flex: 1,
    height: 48,
    backgroundColor: '#1e293b',
    borderColor: '#334155',
    borderWidth: 1,
    borderRadius: 14,
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.2,
    shadowRadius: 4,
    elevation: 2,
  },
  backBtn: {
    backgroundColor: '#1e293b',
  },
  homeBtn: {
    backgroundColor: '#1e293b',
    borderColor: '#ca8a04',
  },
  playBtn: {
    backgroundColor: '#0f2b3e',
    borderColor: '#0284c7',
  },
  fullscreenBtn: {
    backgroundColor: '#241a3d',
    borderColor: '#7c3aed',
  },
  slidersRow: {
    flexDirection: 'row',
    gap: 10,
    alignItems: 'stretch',
  },
  sliderColumn: {
    flex: 1,
    alignItems: 'center',
  },
  sliderHeader: {
    color: '#94a3b8',
    fontSize: 12,
    fontWeight: '700',
    marginBottom: 6,
    letterSpacing: 0.5,
  },
  sliderTrackCard: {
    width: '100%',
    height: 156,
    backgroundColor: '#0f172a',
    borderColor: '#1e293b',
    borderWidth: 1,
    borderRadius: 22,
    paddingVertical: 6,
    paddingHorizontal: 4,
    alignItems: 'center',
    justifyContent: 'space-between',
    overflow: 'hidden',
    position: 'relative',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 4,
  },
  sliderFill: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    backgroundColor: '#0369a1',
    opacity: 0.35,
    borderBottomLeftRadius: 20,
    borderBottomRightRadius: 20,
  },
  sliderFillMuted: {
    backgroundColor: '#7f1d1d',
    opacity: 0.4,
  },
  sliderFillBrightness: {
    backgroundColor: '#854d0e',
    opacity: 0.35,
  },
  sliderStepBtn: {
    width: '100%',
    height: 42,
    backgroundColor: '#1e293b',
    borderColor: '#334155',
    borderWidth: 1,
    borderRadius: 14,
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 2,
  },
  sliderBtnText: {
    color: '#f8fafc',
    fontSize: 22,
    fontWeight: '700',
  },
  sliderLevelPill: {
    width: '90%',
    height: 38,
    backgroundColor: '#1e293b',
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
    marginVertical: 4,
    borderColor: '#334155',
    borderWidth: 1,
    zIndex: 2,
  },
  sliderMutedPill: {
    backgroundColor: '#451a1a',
    borderColor: '#991b1b',
    borderWidth: 1,
  },
  speedPill: {
    backgroundColor: '#1e293b',
    borderColor: '#f7d488',
  },
  brightnessPill: {
    backgroundColor: '#1e293b',
  },
  sliderLevelText: {
    color: '#f7d488',
    fontSize: 13,
    fontWeight: '800',
  },
  sliderSpeedText: {
    color: '#f7d488',
    fontSize: 13,
    fontWeight: '800',
  },
  actionRow: {
    flexDirection: 'row',
    gap: 8,
  },
  actionBtn: {
    flex: 1,
    height: 44,
    backgroundColor: '#0f172a',
    borderColor: '#1e293b',
    borderWidth: 1,
    borderRadius: 14,
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.2,
    shadowRadius: 4,
    elevation: 2,
  },
  channelBtn: {
    backgroundColor: '#1e293b',
    borderColor: '#334155',
  },
  featureBtn: {
    backgroundColor: '#1e293b',
    borderColor: '#334155',
  },
  powerBtn: {
    backgroundColor: '#351a1d',
    borderColor: '#881337',
  },
  disabledControl: {
    opacity: 0.4,
  },
  btnText: {
    color: '#f1f5f9',
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  actionBtnText: {
    color: '#f1f5f9',
    fontSize: 13,
    fontWeight: '700',
  },
  homeText: {
    color: '#f7d488',
    fontWeight: 'bold',
  },
  mutedText: {
    color: '#fca5a5',
    fontSize: 14,
  },
  powerText: {
    color: '#fda4af',
    fontSize: 13,
    fontWeight: '700',
  },
})
