const { withAndroidManifest, withDangerousMod } = require('expo/config-plugins')
const fs = require('node:fs/promises')
const path = require('node:path')

const NETWORK_SECURITY_CONFIG = `<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <base-config cleartextTrafficPermitted="false">
    <trust-anchors>
      <certificates src="system" />
      <certificates src="user" />
    </trust-anchors>
  </base-config>
</network-security-config>
`

function setNetworkSecurityConfig(androidManifest) {
  const application = androidManifest.manifest.application?.[0]
  if (!application) {
    throw new Error('AndroidManifest.xml is missing its application element.')
  }

  application.$ ??= {}
  application.$['android:networkSecurityConfig'] = '@xml/network_security_config'
  return androidManifest
}

function withLocalCaTrust(config) {
  const withManifest = withAndroidManifest(config, (manifestConfig) => {
    manifestConfig.modResults = setNetworkSecurityConfig(manifestConfig.modResults)
    return manifestConfig
  })

  return withDangerousMod(withManifest, [
    'android',
    async (nativeConfig) => {
      const resourceDirectory = path.join(
        nativeConfig.modRequest.platformProjectRoot,
        'app',
        'src',
        'main',
        'res',
        'xml',
      )
      await fs.mkdir(resourceDirectory, { recursive: true })
      await fs.writeFile(
        path.join(resourceDirectory, 'network_security_config.xml'),
        NETWORK_SECURITY_CONFIG,
        'utf8',
      )
      return nativeConfig
    },
  ])
}

module.exports = withLocalCaTrust
module.exports.NETWORK_SECURITY_CONFIG = NETWORK_SECURITY_CONFIG
module.exports.setNetworkSecurityConfig = setNetworkSecurityConfig
