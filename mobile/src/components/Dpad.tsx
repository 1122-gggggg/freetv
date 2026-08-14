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
          style={[styles.button, styles.topButton]}
          activeOpacity={0.7}
          onPress={() => handlePress('NAV_UP')}
          disabled={disabled}
        >
          <Text style={styles.arrow}>▲</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.middleRow}>
        <TouchableOpacity
          style={[styles.button, styles.leftButton]}
          activeOpacity={0.7}
          onPress={() => handlePress('NAV_LEFT')}
          disabled={disabled}
        >
          <Text style={styles.arrow}>◀</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.button, styles.centerButton]}
          activeOpacity={0.7}
          onPress={() => handlePress('OK')}
          disabled={disabled}
        >
          <Text style={styles.okText}>OK</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.button, styles.rightButton]}
          activeOpacity={0.7}
          onPress={() => handlePress('NAV_RIGHT')}
          disabled={disabled}
        >
          <Text style={styles.arrow}>▶</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.row}>
        <TouchableOpacity
          style={[styles.button, styles.bottomButton]}
          activeOpacity={0.7}
          onPress={() => handlePress('NAV_DOWN')}
          disabled={disabled}
        >
          <Text style={styles.arrow}>▼</Text>
        </TouchableOpacity>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    width: 220,
    height: 220,
    alignSelf: 'center',
    justifyContent: 'center',
    alignItems: 'center',
    marginVertical: 12,
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
    backgroundColor: '#1b2535',
    borderColor: '#36435a',
    borderWidth: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  topButton: {
    width: 68,
    height: 64,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    borderBottomWidth: 0,
  },
  bottomButton: {
    width: 68,
    height: 64,
    borderBottomLeftRadius: 20,
    borderBottomRightRadius: 20,
    borderTopWidth: 0,
  },
  leftButton: {
    width: 64,
    height: 68,
    borderTopLeftRadius: 20,
    borderBottomLeftRadius: 20,
    borderRightWidth: 0,
  },
  rightButton: {
    width: 64,
    height: 68,
    borderTopRightRadius: 20,
    borderBottomRightRadius: 20,
    borderLeftWidth: 0,
  },
  centerButton: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: '#273449',
    borderColor: '#4d5d77',
    borderWidth: 1.5,
    zIndex: 2,
  },
  arrow: {
    color: '#f8fafc',
    fontSize: 18,
  },
  okText: {
    color: '#f7d488',
    fontSize: 18,
    fontWeight: 'bold',
  },
})
