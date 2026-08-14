import React from 'react'
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native'
import * as Haptics from 'expo-haptics'
import type { Command } from '../types/protocol'

interface MediaControlsProps {
  onCommand: (command: Command) => void
  disabled?: boolean
  muted?: boolean
  volume?: number
}

export function MediaControls({ onCommand, disabled, muted }: MediaControlsProps): React.ReactElement {
  const trigger = (command: Command) => {
    if (disabled) return
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
    onCommand(command)
  }

  return (
    <View style={styles.container}>
      {/* Top Nav Row */}
      <View style={styles.row}>
        <TouchableOpacity
          style={[styles.btn, styles.backBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('BACK')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="Back"
          accessibilityHint="Returns to the previous screen on the TV."
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.btnText}>◀ BACK</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.btn, styles.homeBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('HOME')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="Home"
          accessibilityHint="Opens the TV home screen."
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={[styles.btnText, styles.homeText]}>⌂ HOME</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.btn, styles.playBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('PLAY_PAUSE')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="Play or pause media"
          accessibilityHint="Toggles media playback on the TV."
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.btnText}>⏯ PLAY</Text>
        </TouchableOpacity>
      </View>

      {/* Volume & Channel Row */}
      <View style={styles.row}>
        <TouchableOpacity
          style={[styles.btn, styles.volBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('VOLUME_DOWN')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="Volume down"
          accessibilityHint="Lowers the TV volume."
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.btnText}>VOL −</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[
            styles.btn,
            muted ? styles.mutedBtn : styles.volBtn,
            disabled && styles.disabledControl,
          ]}
          onPress={() => trigger('MUTE')}
          disabled={disabled}
          accessibilityRole="togglebutton"
          accessibilityLabel={muted ? 'Unmute TV' : 'Mute TV'}
          accessibilityHint={muted ? 'Turns TV sound back on.' : 'Turns TV sound off.'}
          accessibilityState={{ disabled: Boolean(disabled), checked: Boolean(muted) }}
        >
          <Text style={[styles.btnText, muted && styles.mutedText]}>
            {muted ? '🔇 MUTED' : '🔊 MUTE'}
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.btn, styles.volBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('VOLUME_UP')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="Volume up"
          accessibilityHint="Raises the TV volume."
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.btnText}>VOL ＋</Text>
        </TouchableOpacity>
      </View>

      {/* Channel Switch Row */}
      <View style={styles.row}>
        <TouchableOpacity
          style={[styles.btn, styles.chBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('CHANNEL_DOWN')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="Previous channel"
          accessibilityHint="Changes to the previous TV channel."
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.btnText}>CH ▼</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.btn, styles.powerBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('POWER_SLEEP')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="Put TV to sleep"
          accessibilityHint="Puts the TV Box into sleep mode."
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.powerText}>⏻ SLEEP</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.btn, styles.chBtn, disabled && styles.disabledControl]}
          onPress={() => trigger('CHANNEL_UP')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="Next channel"
          accessibilityHint="Changes to the next TV channel."
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.btnText}>CH ▲</Text>
        </TouchableOpacity>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    marginVertical: 6,
    gap: 8,
  },
  row: {
    flexDirection: 'row',
    gap: 8,
  },
  btn: {
    flex: 1,
    height: 48,
    backgroundColor: '#1b2535',
    borderColor: '#36435a',
    borderWidth: 1,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  disabledControl: {
    opacity: 0.5,
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
  volBtn: {
    backgroundColor: '#182230',
  },
  mutedBtn: {
    backgroundColor: '#3d2525',
    borderColor: '#733c3c',
  },
  chBtn: {
    backgroundColor: '#182230',
  },
  powerBtn: {
    backgroundColor: '#351e22',
    borderColor: '#6b333a',
  },
  btnText: {
    color: '#e2e8f0',
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  homeText: {
    color: '#f7d488',
    fontWeight: 'bold',
  },
  mutedText: {
    color: '#ff8a8a',
  },
  powerText: {
    color: '#ff9b9b',
    fontSize: 12,
    fontWeight: '700',
  },
})
