import React from 'react'
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native'
import * as Haptics from 'expo-haptics'
import type { Command } from '../types/protocol'

interface AppLaunchersProps {
  onCommand: (command: Command) => void
  activeApp?: string
  disabled?: boolean
}

export function AppLaunchers({ onCommand, activeApp, disabled }: AppLaunchersProps): React.ReactElement {
  const launch = (command: Command) => {
    if (disabled) return
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium)
    onCommand(command)
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title} accessibilityRole="header">快速啟動</Text>
      <View style={styles.grid}>
        <TouchableOpacity
          style={[
            styles.tile,
            activeApp === 'youtube' && styles.activeTile,
            disabled && styles.disabledControl,
          ]}
          onPress={() => launch('OPEN_YOUTUBE')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="開啟 YouTube"
          accessibilityHint="在電視上啟動 YouTube。"
          accessibilityState={{
            disabled: Boolean(disabled),
            selected: activeApp === 'youtube',
          }}
        >
          <View style={[styles.badge, styles.ytBadge]}>
            <Text style={styles.badgeText}>YT</Text>
          </View>
          <Text style={styles.label}>YouTube</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[
            styles.tile,
            activeApp === 'netflix' && styles.activeTile,
            disabled && styles.disabledControl,
          ]}
          onPress={() => launch('OPEN_NETFLIX')}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="開啟 Netflix"
          accessibilityHint="在電視上啟動 Netflix。"
          accessibilityState={{
            disabled: Boolean(disabled),
            selected: activeApp === 'netflix',
          }}
        >
          <View style={[styles.badge, styles.nfBadge]}>
            <Text style={styles.badgeText}>N</Text>
          </View>
          <Text style={styles.label}>Netflix</Text>
        </TouchableOpacity>

      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 12,
    marginVertical: 8,
  },
  title: {
    color: '#94a3b8',
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1,
    marginBottom: 8,
    marginLeft: 4,
  },
  grid: {
    flexDirection: 'row',
    gap: 10,
  },
  tile: {
    flex: 1,
    backgroundColor: '#0f172a',
    borderColor: '#1e293b',
    borderWidth: 1,
    borderRadius: 16,
    padding: 12,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.2,
    shadowRadius: 4,
    elevation: 2,
  },
  disabledControl: {
    opacity: 0.4,
  },
  activeTile: {
    borderColor: '#f7d488',
    backgroundColor: '#1e293b',
    shadowColor: '#f7d488',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
  },
  badge: {
    width: 40,
    height: 40,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 6,
  },
  ytBadge: {
    backgroundColor: '#dc2626',
  },
  nfBadge: {
    backgroundColor: '#e50914',
  },
  badgeText: {
    color: '#ffffff',
    fontWeight: '900',
    fontSize: 15,
  },
  label: {
    color: '#f1f5f9',
    fontSize: 13,
    fontWeight: '700',
  },
})
