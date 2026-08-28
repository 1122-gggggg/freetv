export const PROTOCOL_VERSION = 1 as const

export type Command =
  | 'NAV_UP'
  | 'NAV_DOWN'
  | 'NAV_LEFT'
  | 'NAV_RIGHT'
  | 'OK'
  | 'BACK'
  | 'TAB'
  | 'HOME'
  | 'PLAY_PAUSE'
  | 'FULLSCREEN'
  | 'SPEED_UP'
  | 'SPEED_DOWN'
  | 'SEEK_FORWARD_5'
  | 'SEEK_BACKWARD_5'
  | 'NEXT'
  | 'PREVIOUS'
  | 'VOLUME_UP'
  | 'VOLUME_DOWN'
  | 'MUTE'
  | 'CHANNEL_UP'
  | 'CHANNEL_DOWN'
  | 'OPEN_YOUTUBE'
  | 'OPEN_NETFLIX'
  | 'OPEN_LIVE_TV'
  | 'OPEN_BROWSER'
  | 'OPEN_NEWS'
  | 'POWER_SLEEP'

export type PointerAction = 'move' | 'tap' | 'double_tap' | 'scroll'

export type NetflixStage = 'login' | 'verification' | 'browse' | 'details' | 'watch' | 'unknown'

export type NetflixInputKind = 'email' | 'password' | 'code' | 'search' | 'none'

export interface NetflixContext {
  stage: NetflixStage
  input_kind: NetflixInputKind
  has_error: boolean
  can_submit: boolean
  focused_title: string | null
}

export interface ControllerState {
  version: 1
  type: 'state'
  active_app: 'launcher' | 'youtube' | 'netflix' | 'live_tv' | 'browser' | 'news'
  focused_tile: 'youtube' | 'netflix' | 'live_tv' | 'browser' | 'news' | 'settings'
  volume: number
  muted: boolean
  channel_number: number | null
  channel_name: string | null
  status_message: string | null
  error_message: string | null
  netflix_context?: NetflixContext | null
}

export interface Acknowledgement {
  version: 1
  type: 'ack'
  request_id: string
  success: boolean
  error_code: string | null
  message: string | null
}

export interface ProtocolError {
  version: 1
  type: 'error'
  code: string
  message: string
}

export type ServerMessage = ControllerState | Acknowledgement | ProtocolError

export interface CommandMessage {
  version: 1
  type: 'command'
  request_id: string
  command: Command
}

export interface AuthenticationMessage {
  version: 1
  type: 'authenticate'
  request_id: string
  token: string
}

export interface PointerMessage {
  version: 1
  type: 'pointer'
  request_id: string
  action: PointerAction
  dx: number
  dy: number
}

export interface TextInputMessage {
  version: 1
  type: 'text_input'
  request_id: string
  text: string
  submit?: boolean
}

export interface SearchVideoMessage {
  version: 1
  type: 'search_video'
  request_id: string
  query: string
}

export type ClientMessage = CommandMessage | AuthenticationMessage | PointerMessage | TextInputMessage | SearchVideoMessage
