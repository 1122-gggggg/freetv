import React from 'react'
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native'
import * as Haptics from 'expo-haptics'
import type { Command } from '../types/protocol'

interface MediaControlsProps {
  onCommand: (command: Command) => void
  disabled?: boolean
  muted?: boolean
  volume?: number
  brightness?: number
}

export function MediaControls({
  onCommand,
  disabled,
  muted,
  volume = 50,
  brightness = 100,
}: MediaControlsProps): React.ReactElement {
  const trigger = (command: Command) => {
    if (disabled) return
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
    onCommand(command)
  }

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

      {/* Dashboard Body: Vertical Volume Rocker | Center Controls | Vertical Brightness Rocker */}
      <View style={styles.dashboardRow}>
        {/* Left Column: Vertical Volume Rocker */}
        <View style={styles.rockerCard}>
          <Text style={styles.rockerHeader}>音量</Text>
          <TouchableOpacity
            style={[styles.rockerBtn, disabled && styles.disabledControl]}
            onPress={() => trigger('VOLUME_UP')}
            disabled={disabled}
            accessibilityRole="button"
            accessibilityLabel="音量提高"
            accessibilityHint="提高電視音量。"
            accessibilityState={{ disabled: Boolean(disabled) }}
          >
            <Text style={styles.rockerBtnText}>＋</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[styles.rockerLevelPill, muted && styles.rockerMutedPill, disabled && styles.disabledControl]}
            onPress={() => trigger('MUTE')}
            disabled={disabled}
            accessibilityRole="togglebutton"
            accessibilityLabel={muted ? '取消靜音' : '靜音'}
            accessibilityHint={muted ? '恢復電視聲音。' : '關閉電視聲音。'}
            accessibilityState={{ disabled: Boolean(disabled), checked: Boolean(muted) }}
          >
            <Text style={[styles.rockerLevelText, muted && styles.mutedText]}>
              {muted ? '🔇' : `${volume}%`}
            </Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[styles.rockerBtn, disabled && styles.disabledControl]}
            onPress={() => trigger('VOLUME_DOWN')}
            disabled={disabled}
            accessibilityRole="button"
            accessibilityLabel="音量降低"
            accessibilityHint="降低電視音量。"
            accessibilityState={{ disabled: Boolean(disabled) }}
          >
            <Text style={styles.rockerBtnText}>−</Text>
          </TouchableOpacity>
        </View>

        {/* Center Column: Speed, Seek, Channels */}
        <View style={styles.centerCard}>
          <View style={styles.centerSection}>
            <View style={styles.centerRow}>
              <TouchableOpacity
                style={[styles.centerBtn, disabled && styles.disabledControl]}
                onPress={() => trigger('SPEED_DOWN')}
                disabled={disabled}
                accessibilityRole="button"
                accessibilityLabel="降低倍速"
                accessibilityHint="降低目前影片的播放速度。"
                accessibilityState={{ disabled: Boolean(disabled) }}
              >
                <Text style={styles.centerBtnText}>倍速 −</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={[styles.centerBtn, disabled && styles.disabledControl]}
                onPress={() => trigger('SPEED_UP')}
                disabled={disabled}
                accessibilityRole="button"
                accessibilityLabel="提高倍速"
                accessibilityHint="提高目前影片的播放速度。"
                accessibilityState={{ disabled: Boolean(disabled) }}
              >
                <Text style={styles.centerBtnText}>倍速 ＋</Text>
              </TouchableOpacity>
            </View>
          </View>

          <View style={styles.centerSection}>
            <View style={styles.centerRow}>
              <TouchableOpacity
                style={[styles.centerBtn, disabled && styles.disabledControl]}
                onPress={() => trigger('SEEK_BACKWARD_5')}
                disabled={disabled}
                accessibilityRole="button"
                accessibilityLabel="倒退五秒"
                accessibilityHint="將目前影片倒退五秒。"
                accessibilityState={{ disabled: Boolean(disabled) }}
              >
                <Text style={styles.centerBtnText}>−5 秒</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={[styles.centerBtn, disabled && styles.disabledControl]}
                onPress={() => trigger('SEEK_FORWARD_5')}
                disabled={disabled}
                accessibilityRole="button"
                accessibilityLabel="快轉五秒"
                accessibilityHint="將目前影片快轉五秒。"
                accessibilityState={{ disabled: Boolean(disabled) }}
              >
                <Text style={styles.centerBtnText}>＋5 秒</Text>
              </TouchableOpacity>
            </View>
          </View>

          <View style={styles.centerRow}>
            <TouchableOpacity
              style={[styles.channelBtn, disabled && styles.disabledControl]}
              onPress={() => trigger('CHANNEL_DOWN')}
              disabled={disabled}
              accessibilityRole="button"
              accessibilityLabel="上一台"
              accessibilityHint="切換到上一台頻道。"
              accessibilityState={{ disabled: Boolean(disabled) }}
            >
              <Text style={styles.centerBtnText}>頻道 ▼</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.powerBtn, disabled && styles.disabledControl]}
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
              style={[styles.channelBtn, disabled && styles.disabledControl]}
              onPress={() => trigger('CHANNEL_UP')}
              disabled={disabled}
              accessibilityRole="button"
              accessibilityLabel="下一台"
              accessibilityHint="切換到下一台頻道。"
              accessibilityState={{ disabled: Boolean(disabled) }}
            >
              <Text style={styles.centerBtnText}>頻道 ▲</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Right Column: Vertical Brightness Rocker */}
        <View style={styles.rockerCard}>
          <Text style={styles.rockerHeader}>亮度</Text>
          <TouchableOpacity
            style={[styles.rockerBtn, disabled && styles.disabledControl]}
            onPress={() => trigger('BRIGHTNESS_UP')}
            disabled={disabled}
            accessibilityRole="button"
            accessibilityLabel="提高亮度"
            accessibilityHint="提高電視螢幕亮度。"
            accessibilityState={{ disabled: Boolean(disabled) }}
          >
            <Text style={styles.rockerBtnText}>＋</Text>
          </TouchableOpacity>

          <View style={[styles.rockerLevelPill, styles.brightnessPill, disabled && styles.disabledControl]}>
            <Text style={styles.rockerLevelText}>{`${brightness}%`}</Text>
          </View>

          <TouchableOpacity
            style={[styles.rockerBtn, disabled && styles.disabledControl]}
            onPress={() => trigger('BRIGHTNESS_DOWN')}
            disabled={disabled}
            accessibilityRole="button"
            accessibilityLabel="降低亮度"
            accessibilityHint="降低電視螢幕亮度。"
            accessibilityState={{ disabled: Boolean(disabled) }}
          >
            <Text style={styles.rockerBtnText}>−</Text>
          </TouchableOpacity>
        </View>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 14,
    marginVertical: 4,
    gap: 8,
  },
  topRow: {
    flexDirection: 'row',
    gap: 6,
  },
  navBtn: {
    flex: 1,
    height: 44,
    backgroundColor: '#1b2535',
    borderColor: '#36435a',
    borderWidth: 1,
    borderRadius: 10,
    justifyContent: 'center',
    alignItems: 'center',
  },
  backBtn: {
    backgroundColor: '#202a3c',
  },
  homeBtn: {
    backgroundColor: '#2a3b56',
    borderColor: '#4d6994',
  },
  playBtn: {
    backgroundColor: '#202a3c',
  },
  fullscreenBtn: {
    backgroundColor: '#202a3c',
  },
  dashboardRow: {
    flexDirection: 'row',
    gap: 8,
    alignItems: 'stretch',
  },
  rockerCard: {
    width: 68,
    backgroundColor: '#131c2b',
    borderColor: '#263449',
    borderWidth: 1,
    borderRadius: 16,
    paddingVertical: 8,
    paddingHorizontal: 4,
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  rockerHeader: {
    color: '#94a3b8',
    fontSize: 11,
    fontWeight: '700',
    marginBottom: 4,
  },
  rockerBtn: {
    width: 56,
    height: 44,
    backgroundColor: '#1e2c42',
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  rockerBtnText: {
    color: '#f8fafc',
    fontSize: 22,
    fontWeight: '700',
  },
  rockerLevelPill: {
    width: 56,
    height: 36,
    backgroundColor: '#182438',
    borderRadius: 8,
    justifyContent: 'center',
    alignItems: 'center',
    marginVertical: 4,
  },
  rockerMutedPill: {
    backgroundColor: '#3d2525',
    borderColor: '#733c3c',
    borderWidth: 1,
  },
  brightnessPill: {
    backgroundColor: '#1b293e',
  },
  rockerLevelText: {
    color: '#f7d488',
    fontSize: 12,
    fontWeight: '700',
  },
  centerCard: {
    flex: 1,
    backgroundColor: '#131c2b',
    borderColor: '#263449',
    borderWidth: 1,
    borderRadius: 16,
    padding: 8,
    justifyContent: 'space-between',
    gap: 6,
  },
  centerSection: {
    gap: 4,
  },
  centerHeader: {
    color: '#94a3b8',
    fontSize: 11,
    fontWeight: '700',
    marginLeft: 2,
  },
  centerRow: {
    flexDirection: 'row',
    gap: 6,
  },
  centerBtn: {
    flex: 1,
    height: 40,
    backgroundColor: '#1e2c42',
    borderColor: '#344663',
    borderWidth: 1,
    borderRadius: 10,
    justifyContent: 'center',
    alignItems: 'center',
  },
  channelBtn: {
    flex: 1,
    height: 40,
    backgroundColor: '#1a273b',
    borderRadius: 10,
    justifyContent: 'center',
    alignItems: 'center',
  },
  powerBtn: {
    flex: 1,
    height: 40,
    backgroundColor: '#351e22',
    borderColor: '#6b333a',
    borderWidth: 1,
    borderRadius: 10,
    justifyContent: 'center',
    alignItems: 'center',
  },
  disabledControl: {
    opacity: 0.5,
  },
  btnText: {
    color: '#e2e8f0',
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  centerBtnText: {
    color: '#e2e8f0',
    fontSize: 12,
    fontWeight: '700',
  },
  homeText: {
    color: '#f7d488',
    fontWeight: 'bold',
  },
  mutedText: {
    color: '#ff8a8a',
    fontSize: 14,
  },
  powerText: {
    color: '#ff9b9b',
    fontSize: 12,
    fontWeight: '700',
  },
})
