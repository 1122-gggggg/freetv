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
      <Text style={styles.title}>QUICK LAUNCH</Text>
      <View style={styles.grid}>
        <TouchableOpacity
          style={[styles.tile, activeApp === 'youtube' && styles.activeTile]}
          onPress={() => launch('OPEN_YOUTUBE')}
          disabled={disabled}
        >
          <View style={[styles.badge, styles.ytBadge]}>
            <Text style={styles.badgeText}>YT</Text>
          </View>
          <Text style={styles.label}>YouTube</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.tile, activeApp === 'netflix' && styles.activeTile]}
          onPress={() => launch('OPEN_NETFLIX')}
          disabled={disabled}
        >
          <View style={[styles.badge, styles.nfBadge]}>
            <Text style={styles.badgeText}>N</Text>
          </View>
          <Text style={styles.label}>Netflix</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.tile, activeApp === 'live_tv' && styles.activeTile]}
          onPress={() => launch('OPEN_LIVE_TV')}
          disabled={disabled}
        >
          <View style={[styles.badge, styles.tvBadge]}>
            <Text style={styles.badgeText}>TV</Text>
          </View>
          <Text style={styles.label}>Live TV</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.tile, activeApp === 'browser' && styles.activeTile]}
          onPress={() => launch('OPEN_BROWSER')}
          disabled={disabled}
        >
          <View style={[styles.badge, styles.webBadge]}>
            <Text style={styles.badgeText}>WEB</Text>
          </View>
          <Text style={styles.label}>Browser</Text>
        </TouchableOpacity>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    marginVertical: 8,
  },
  title: {
    color: '#8da0b8',
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.5,
    marginBottom: 8,
  },
  grid: {
    flexDirection: 'row',
    gap: 8,
  },
  tile: {
    flex: 1,
    backgroundColor: '#1b2535',
    borderColor: '#36435a',
    borderWidth: 1,
    borderRadius: 14,
    padding: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  activeTile: {
    borderColor: '#f7d488',
    backgroundColor: '#27354a',
  },
  badge: {
    width: 36,
    height: 36,
    borderRadius: 8,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 4,
  },
  ytBadge: {
    backgroundColor: '#ff0000',
  },
  nfBadge: {
    backgroundColor: '#e50914',
  },
  tvBadge: {
    backgroundColor: '#3b82f6',
  },
  webBadge: {
    backgroundColor: '#f59e0b',
  },
  badgeText: {
    color: '#ffffff',
    fontWeight: '900',
    fontSize: 14,
  },
  label: {
    color: '#f8fafc',
    fontSize: 12,
    fontWeight: '600',
  },
})
