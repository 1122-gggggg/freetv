import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const desktopLowHeightQuery = '(min-width: 761px) and (max-height: 820px)'

function mediaContents(styles: string, query: string): string {
  const marker = `@media ${query} {`
  const start = styles.indexOf(marker)
  if (start === -1) throw new Error(`Missing ${marker}`)

  let depth = 0
  for (let index = start + marker.length - 1; index < styles.length; index += 1) {
    if (styles[index] === '{') depth += 1
    if (styles[index] !== '}') continue
    depth -= 1
    if (depth === 0) return styles.slice(start, index + 1)
  }

  throw new Error(`Unclosed ${marker}`)
}

function ruleContents(styles: string, selector: string): string {
  const marker = `${selector} {`
  const start = styles.indexOf(marker)
  if (start === -1) throw new Error(`Missing ${selector} rule`)
  const end = styles.indexOf('}', start)
  if (end === -1) throw new Error(`Unclosed ${selector} rule`)
  return styles.slice(start, end + 1)
}

describe('TV launcher low-height layout constraints', () => {
  it('reserves an explicit row for every shell section and clips tile details', () => {
    const styles = readFileSync('src/styles.css', 'utf8')
    const shell = ruleContents(styles, '.tv-shell')
    const lowHeightStyles = mediaContents(styles, desktopLowHeightQuery)
    const tileDetail = ruleContents(lowHeightStyles, '.tile-detail')
    const footer = ruleContents(lowHeightStyles, '.tv-footer')
    const launcherGrid = ruleContents(styles, '.tv-grid')

    expect(shell).toContain('grid-template-rows: auto minmax(0, 1fr) auto auto;')
    expect(ruleContents(lowHeightStyles, '.tv-shell')).toContain('gap: 0.75rem;')
    expect(footer).toContain('display: grid;')
    expect(footer).toContain('grid-template-columns: minmax(0, 1fr) auto;')
    expect(launcherGrid).toContain('grid-template-columns: repeat(3, minmax(0, 1fr));')
    expect(tileDetail).toContain('max-height: 2.5em;')
    expect(tileDetail).toContain('overflow: hidden;')
    expect(tileDetail).toContain('-webkit-line-clamp: 2;')
  })

  it('compacts the pairing card without applying the rule to mobile widths', () => {
    const styles = readFileSync('src/remote-enhancements.css', 'utf8')
    const lowHeightStyles = mediaContents(styles, desktopLowHeightQuery)
    const pairingCard = ruleContents(lowHeightStyles, '.pairing-card')
    const pairingQr = ruleContents(lowHeightStyles, '.pairing-qr-wrapper svg')

    expect(pairingCard).toContain('min-width: 0;')
    expect(pairingQr).toContain('width: 92px;')
    expect(pairingQr).toContain('height: 92px;')
  })
})
