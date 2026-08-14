const {
  NETWORK_SECURITY_CONFIG,
  setNetworkSecurityConfig,
} = require('./withLocalCaTrust')

describe('withLocalCaTrust', () => {
  it('configures Android to trust the installed controller CA', () => {
    const manifest = { manifest: { application: [{ $: {} }] } }

    setNetworkSecurityConfig(manifest)

    expect(manifest.manifest.application[0].$['android:networkSecurityConfig']).toBe(
      '@xml/network_security_config',
    )
    expect(NETWORK_SECURITY_CONFIG).toContain('<certificates src="system" />')
    expect(NETWORK_SECURITY_CONFIG).toContain('<certificates src="user" />')
  })
})
