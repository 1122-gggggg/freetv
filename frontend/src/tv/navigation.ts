import type { Command } from '../types/protocol'

export type TileId = 'youtube' | 'netflix' | 'news' | 'live_tv' | 'browser' | 'settings'

const TRANSITIONS: Record<TileId, Partial<Record<Command, TileId>>> = {
  youtube: { NAV_RIGHT: 'netflix', NAV_DOWN: 'news' },
  netflix: { NAV_LEFT: 'youtube', NAV_DOWN: 'live_tv' },
  news: { NAV_UP: 'youtube', NAV_RIGHT: 'live_tv', NAV_DOWN: 'browser' },
  live_tv: { NAV_UP: 'netflix', NAV_LEFT: 'news', NAV_DOWN: 'settings' },
  browser: { NAV_UP: 'news', NAV_RIGHT: 'settings' },
  settings: { NAV_UP: 'live_tv', NAV_LEFT: 'browser' },
}

const TILE_COMMANDS: Partial<Record<TileId, Command>> = {
  youtube: 'OPEN_YOUTUBE',
  netflix: 'OPEN_NETFLIX',
  news: 'OPEN_NEWS',
  live_tv: 'OPEN_LIVE_TV',
  browser: 'OPEN_BROWSER',
}

export function moveFocus(current: TileId, command: Command): TileId {
  return TRANSITIONS[current][command] ?? current
}

export function tileCommand(tile: TileId): Command | null {
  return TILE_COMMANDS[tile] ?? null
}
