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
import type { NetflixInputKind } from '../types/protocol'

interface TextInputModalProps {
  visible: boolean
  inputKind: NetflixInputKind
  submit: boolean
  canSubmit: boolean
  onClose: () => void
  onSend: (text: string, submit: boolean) => Promise<void>
  onLiveSync?: (text: string) => void
}

export function TextInputModal({
  visible,
  inputKind,
  canSubmit,
  submit,
  onClose,
  onSend,
  onLiveSync,
}: TextInputModalProps): React.ReactElement {
  const insets = useSafeAreaInsets()
  const [text, setText] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const handleClose = () => {
    setText('')
    setErrorMessage(null)
    setIsSending(false)
    onClose()
  }

  const handleSend = async () => {
    if (!text.trim() || isSending || (submit && !canSubmit)) return
    const value = text
    setText('')
    setIsSending(true)
    setErrorMessage(null)
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
    try {
      await onSend(value, submit)
      handleClose()
    } catch {
      if (submit) {
        handleClose()
      } else {
        setErrorMessage('無法送出，請重試')
        setIsSending(false)
      }
    }
  }

  const keyboardType =
    inputKind === 'email'
      ? 'email-address'
      : inputKind === 'code'
        ? 'number-pad'
        : 'default'
  const textContentType =
    inputKind === 'email'
      ? 'username'
      : inputKind === 'password'
        ? 'password'
        : inputKind === 'code'
          ? 'oneTimeCode'
          : 'none'

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={handleClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={[styles.overlay, { paddingTop: insets.top }]}
      >
        <View style={[styles.card, { paddingBottom: insets.bottom + 24 }]}>
          <Text style={styles.title}>傳送文字到電視</Text>
          <Text style={styles.subtitle}>
            輸入搜尋關鍵字、網址或文字，傳送到電腦上目前焦點的應用程式。
          </Text>

          <TextInput
            style={styles.input}
            accessibilityLabel={submit ? 'Netflix 情境輸入' : '文字輸入'}
            placeholder={
              inputKind === 'email'
                ? '請輸入 Netflix 電子郵件或手機號碼'
                : inputKind === 'password'
                  ? '請輸入 Netflix 密碼'
                  : inputKind === 'code'
                    ? '請輸入驗證碼 (OTP)'
                    : '在此輸入文字…'
            }
            placeholderTextColor="#64748b"
            value={text}
            onChangeText={(value) => {
              setText(value)
              if (errorMessage) setErrorMessage(null)
              onLiveSync?.(value)
            }}
            maxLength={256}
            autoFocus
            keyboardType={keyboardType}
            autoCapitalize="none"
            autoCorrect={false}
            textContentType={textContentType}
            secureTextEntry={inputKind === 'password'}
            returnKeyType="send"
            onSubmitEditing={handleSend}
          />

          {errorMessage ? (
            <Text style={styles.errorText}>{errorMessage}</Text>
          ) : null}
          <View style={styles.actions}>
            <TouchableOpacity style={[styles.btn, styles.cancelBtn]} onPress={handleClose}>
              <Text style={styles.cancelText}>取消</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[
                styles.btn,
                styles.sendBtn,
                (!text.trim() || isSending || (submit && !canSubmit)) &&
                  styles.disabledBtn,
              ]}
              onPress={handleSend}
              disabled={!text.trim() || isSending || (submit && !canSubmit)}
              accessibilityLabel={submit ? '送出 Netflix 輸入' : '送出文字'}
            >
              <Text style={styles.sendText}>{isSending ? '送出中…' : '送出'}</Text>
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
