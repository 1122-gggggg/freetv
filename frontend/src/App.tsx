import { lazy, Suspense, type ReactElement, useEffect, useState } from 'react'

import { forgetStoredRemoteToken, revokeRemoteToken, storedRemoteToken } from './remote/tokenStorage'

const RemotePage = lazy(async () => {
  const route = await import('./remote/RemotePage')
  return { default: route.RemotePage }
})

const TVLauncher = lazy(async () => {
  const route = await import('./tv/TVLauncher')
  return { default: route.TVLauncher }
})

function RouteFallback(): ReactElement {
  return <div aria-live="polite">載入中…</div>
}

export function App(): ReactElement {
  const [token, setToken] = useState<string | null>(() => storedRemoteToken())
  const remoteRoute = window.location.pathname === '/remote'

  useEffect(() => {
    if ('serviceWorker' in navigator && window.isSecureContext) {
      void navigator.serviceWorker.register('/service-worker.js').catch(() => undefined)
    }
  }, [])

  if (!remoteRoute) {
    return (
      <Suspense fallback={<RouteFallback />}>
        <TVLauncher />
      </Suspense>
    )
  }
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
    <Suspense fallback={<RouteFallback />}>
      <RemotePage
        token={token}
        onPaired={setToken}
        onForget={unpairRemote}
        onAuthenticationFailed={discardRemoteToken}
      />
    </Suspense>
  )
}
