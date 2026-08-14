import React, { useEffect, useState } from 'react'
import { StatusBar, StyleSheet, View } from 'react-native'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { DiscoveryScreen } from './src/screens/DiscoveryScreen'
import { RemoteScreen } from './src/screens/RemoteScreen'
import { getCurrentDevice, type SavedDevice } from './src/storage/tokenStorage'

export default function App(): React.ReactElement {
  const [currentDevice, setCurrentDevice] = useState<SavedDevice | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    bootstrap()
  }, [])

  const bootstrap = async () => {
    try {
      const device = await getCurrentDevice()
      setCurrentDevice(device)
    } finally {
      setIsLoading(false)
    }
  }

  if (isLoading) {
    return <View style={styles.loadingContainer} />
  }

  return (
    <SafeAreaProvider>
      <StatusBar barStyle="light-content" backgroundColor="#0c111d" />
      <View style={styles.container}>
        {currentDevice ? (
          <RemoteScreen
            device={currentDevice}
            onDisconnect={() => setCurrentDevice(null)}
          />
        ) : (
          <DiscoveryScreen
            onDeviceConnected={(device) => setCurrentDevice(device)}
          />
        )}
      </View>
    </SafeAreaProvider>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0c111d',
  },
  loadingContainer: {
    flex: 1,
    backgroundColor: '#0c111d',
  },
})
