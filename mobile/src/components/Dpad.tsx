import React from 'react'
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native'
import * as Haptics from 'expo-haptics'
import type { Command } from '../types/protocol'

interface DpadProps {
  onCommand: (command: Command) => void
  disabled?: boolean
}

export function Dpad({ onCommand, disabled }: DpadProps): React.ReactElement {
  const handlePress = (command: Command) => {
    if (disabled) return
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
    onCommand(command)
  }

  return (
    <View style={styles.container}>
      <View style={styles.row}>
        <TouchableOpacity
          style={[styles.button, styles.topButton, disabled && styles.disabledControl]}
          activeOpacity={0.7}
          onPress={() => handlePress('NAV_UP')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="上"
          accessibilityHint="將電視焦點往上移動。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.arrow}>▲</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.middleRow}>
        <TouchableOpacity
          style={[styles.button, styles.leftButton, disabled && styles.disabledControl]}
          activeOpacity={0.7}
          onPress={() => handlePress('NAV_LEFT')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="左"
          accessibilityHint="將電視焦點往左移動。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.arrow}>◀</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.button, styles.centerButton, disabled && styles.disabledControl]}
          activeOpacity={0.7}
          onPress={() => handlePress('OK')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="確定"
          accessibilityHint="啟動電視上目前焦點項目。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.okText}>確定</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.button, styles.rightButton, disabled && styles.disabledControl]}
          activeOpacity={0.7}
          onPress={() => handlePress('NAV_RIGHT')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="右"
          accessibilityHint="將電視焦點往右移動。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.arrow}>▶</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.row}>
        <TouchableOpacity
          style={[styles.button, styles.bottomButton, disabled && styles.disabledControl]}
          activeOpacity={0.7}
          onPress={() => handlePress('NAV_DOWN')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="下"
          accessibilityHint="將電視焦點往下移動。"
          accessibilityState={{ disabled: Boolean(disabled) }}
        >
          <Text style={styles.arrow}>▼</Text>
        </TouchableOpacity>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    width: 236,
    height: 236,
    alignSelf: 'center',
    justifyContent: 'center',
    alignItems: 'center',
    marginVertical: 14,
    backgroundColor: '#0f172a',
    borderRadius: 118,
    padding: 8,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.45,
    shadowRadius: 16,
    elevation: 8,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'center',
  },
  middleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  button: {
    backgroundColor: '#1e293b',
    borderColor: '#334155',
    borderWidth: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  disabledControl: {
    opacity: 0.4,
  },
  topButton: {
    width: 72,
    height: 66,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    borderBottomWidth: 0,
    marginBottom: -2,
  },
  bottomButton: {
    width: 72,
    height: 66,
    borderBottomLeftRadius: 24,
    borderBottomRightRadius: 24,
    borderTopWidth: 0,
    marginTop: -2,
  },
  leftButton: {
    width: 66,
    height: 72,
    borderTopLeftRadius: 24,
    borderBottomLeftRadius: 24,
    borderRightWidth: 0,
    marginRight: -2,
  },
  rightButton: {
    width: 66,
    height: 72,
    borderTopRightRadius: 24,
    borderBottomRightRadius: 24,
    borderLeftWidth: 0,
    marginLeft: -2,
  },
  centerButton: {
    width: 76,
    height: 76,
    borderRadius: 38,
    backgroundColor: '#0f172a',
    borderColor: '#475569',
    borderWidth: 2,
    zIndex: 2,
    shadowColor: '#f7d488',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.25,
    shadowRadius: 10,
  },
  arrow: {
    color: '#cbd5e1',
    fontSize: 18,
    fontWeight: '700',
  },
  okText: {
    color: '#f7d488',
    fontSize: 17,
    fontWeight: '800',
    letterSpacing: 1,
  },
})
