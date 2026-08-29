import type { Command } from '../types/protocol'

export type TileId = 'youtube' | 'netflix' | 'news'

const TRANSITIONS: Record<TileId, Partial<Record<Command, TileId>>> = {
  youtube: { NAV_RIGHT: 'netflix', NAV_DOWN: 'news' },
  netflix: { NAV_LEFT: 'youtube', NAV_DOWN: 'news' },
  news: { NAV_UP: 'youtube', NAV_LEFT: 'youtube', NAV_RIGHT: 'netflix' },
}

const TILE_COMMANDS: Record<TileId, Command> = {
  youtube: 'OPEN_YOUTUBE',
  netflix: 'OPEN_NETFLIX',
  news: 'OPEN_NEWS',
}

export function moveFocus(current: TileId, command: Command): TileId {
  return TRANSITIONS[current][command] ?? current
}

export function tileCommand(tile: TileId): Command | null {
  return TILE_COMMANDS[tile] ?? null
}
