import { type ReactElement, useEffect, useState } from 'react'

import { RemotePage } from './remote/RemotePage'
import { forgetStoredRemoteToken, revokeRemoteToken, storedRemoteToken } from './remote/tokenStorage'
import { TVLauncher } from './tv/TVLauncher'

export function App(): ReactElement {
  const [token, setToken] = useState<string | null>(() => storedRemoteToken())
  const remoteRoute = window.location.pathname === '/remote'

  useEffect(() => {
    if ('serviceWorker' in navigator && window.isSecureContext) {
      void navigator.serviceWorker.register('/service-worker.js').catch(() => undefined)
    }
  }, [])

  if (!remoteRoute) return <TVLauncher />
  const discardRemoteToken = () => {
    forgetStoredRemoteToken()
    setToken(null)
  }

  const unpairRemote = async () => {
    if (token === null) return
    await revokeRemoteToken(token)
    discardRemoteToken()
  }


  return (
    <RemotePage
      token={token}
      onPaired={setToken}
      onForget={unpairRemote}
      onAuthenticationFailed={discardRemoteToken}
    />
  )
}
