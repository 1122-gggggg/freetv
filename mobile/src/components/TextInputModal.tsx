import React, { useState } from 'react'
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import * as Haptics from 'expo-haptics'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

interface TextInputModalProps {
  visible: boolean
  onClose: () => void
  onSend: (text: string) => Promise<void>
}

export function TextInputModal({ visible, onClose, onSend }: TextInputModalProps): React.ReactElement {
  const insets = useSafeAreaInsets()
  const [text, setText] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const handleSend = async () => {
    if (!text.trim() || isSending) return
    setIsSending(true)
    setErrorMessage(null)
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
    try {
      await onSend(text)
      setText('')
      setErrorMessage(null)
      onClose()
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to send text'
      setErrorMessage(message)
    } finally {
      setIsSending(false)
    }
  }

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={[styles.overlay, { paddingTop: insets.top }]}
      >
        <View style={[styles.card, { paddingBottom: insets.bottom + 24 }]}>
          <Text style={styles.title}>SEND TEXT TO TV</Text>
          <Text style={styles.subtitle}>
            Type search queries, URLs, or text to send into the focused app on PC.
          </Text>

          <TextInput
            style={styles.input}
            placeholder="Type text here..."
            placeholderTextColor="#64748b"
            value={text}
            onChangeText={(val) => {
              setText(val)
              if (errorMessage) setErrorMessage(null)
            }}
            maxLength={256}
            autoFocus
            returnKeyType="send"
            onSubmitEditing={handleSend}
          />

          {errorMessage ? (
            <Text style={styles.errorText}>{errorMessage}</Text>
          ) : null}
          <View style={styles.actions}>
            <TouchableOpacity style={[styles.btn, styles.cancelBtn]} onPress={onClose}>
              <Text style={styles.cancelText}>CANCEL</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.btn, styles.sendBtn, !text.trim() && styles.disabledBtn]}
              onPress={handleSend}
              disabled={!text.trim() || isSending}
            >
              <Text style={styles.sendText}>{isSending ? 'SENDING...' : 'SEND'}</Text>
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  )
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.75)',
    justifyContent: 'flex-end',
  },
  card: {
    backgroundColor: '#1b2535',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    borderColor: '#36435a',
    borderWidth: 1,
    padding: 24,
  },
  title: {
    color: '#f7d488',
    fontSize: 16,
    fontWeight: '800',
    letterSpacing: 1,
  },
  subtitle: {
    color: '#94a3b8',
    fontSize: 13,
    marginTop: 4,
    marginBottom: 16,
  },
  input: {
    backgroundColor: '#0f172a',
    borderColor: '#334155',
    borderWidth: 1,
    borderRadius: 12,
    color: '#f8fafc',
    fontSize: 16,
    padding: 14,
    marginBottom: 16,
  },
  actions: {
    flexDirection: 'row',
    gap: 12,
  },
  btn: {
    flex: 1,
    minHeight: 48,
    minWidth: 48,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  cancelBtn: {
    backgroundColor: '#273449',
  },
  sendBtn: {
    backgroundColor: '#f7d488',
  },
  disabledBtn: {
    opacity: 0.5,
  },
  cancelText: {
    color: '#cbd5e1',
    fontWeight: '700',
  },
  sendText: {
    color: '#141820',
    fontWeight: '800',
  },
  errorText: {
    color: '#ef4444',
    fontSize: 13,
    marginTop: -6,
    marginBottom: 14,
  },
})
