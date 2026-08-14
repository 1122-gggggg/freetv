import type { PointerAction } from '../types/protocol'

export const FRAME_MS = 16
export const MAX_DELTA = 100
export const MAX_ACCUMULATED_DELTA = 300

type EmitPointer = (action: PointerAction, dx: number, dy: number) => void
type TimerHandle = number

export interface PointerCoalescer {
  move(dx: number, dy: number): void
  scroll(dy: number): void
  flush(): void
  cancel(): void
  dispose(): void
}

export function createPointerCoalescer(emit: EmitPointer): PointerCoalescer {
  let pendingMoveX = 0
  let pendingMoveY = 0
  let pendingScrollY = 0
  let timer: TimerHandle | null = null
  let isDisposed = false

  const schedule = () => {
    if (timer || isDisposed) return
    timer = setTimeout(flush, FRAME_MS)
  }

  const flush = () => {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
    if (isDisposed) return

    if (pendingMoveX !== 0 || pendingMoveY !== 0) {
      const dx = boundedDelta(pendingMoveX)
      const dy = boundedDelta(pendingMoveY)
      if (dx !== 0 || dy !== 0) {
        pendingMoveX -= dx
        pendingMoveY -= dy
        emit('move', dx, dy)
      }
    }

    if (pendingScrollY !== 0) {
      const dy = boundedDelta(pendingScrollY)
      if (dy !== 0) {
        pendingScrollY -= dy
        emit('scroll', 0, dy)
      }
    }

    if (pendingMoveX !== 0 || pendingMoveY !== 0 || pendingScrollY !== 0) {
      schedule()
    }
  }

  const queueMove = (dx: number, dy: number) => {
    if (isDisposed) return
    pendingMoveX = clamp(
      pendingMoveX + integerDelta(dx),
      -MAX_ACCUMULATED_DELTA,
      MAX_ACCUMULATED_DELTA
    )
    pendingMoveY = clamp(
      pendingMoveY + integerDelta(dy),
      -MAX_ACCUMULATED_DELTA,
      MAX_ACCUMULATED_DELTA
    )
    if (pendingMoveX !== 0 || pendingMoveY !== 0) schedule()
  }

  const queueScroll = (dy: number) => {
    if (isDisposed) return
    pendingScrollY = clamp(
      pendingScrollY + integerDelta(dy),
      -MAX_ACCUMULATED_DELTA,
      MAX_ACCUMULATED_DELTA
    )
    if (pendingScrollY !== 0) schedule()
  }

  const cancel = () => {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
    pendingMoveX = 0
    pendingMoveY = 0
    pendingScrollY = 0
  }

  return {
    move: queueMove,
    scroll: queueScroll,
    flush,
    cancel,
    dispose: () => {
      cancel()
      isDisposed = true
    },
  }
}

export interface TapHandlerOptions {
  tapDelayMs?: number
  onTap: () => void
  onDoubleTap: () => void
}

export interface TapHandler {
  registerTap(): void
  cancel(): void
  hasPendingTap(): boolean
  dispose(): void
}

export function createTapHandler({
  tapDelayMs = 250,
  onTap,
  onDoubleTap,
}: TapHandlerOptions): TapHandler {
  let timer: TimerHandle | null = null

  const cancel = () => {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  const registerTap = () => {
    if (timer !== null) {
      cancel()
      onDoubleTap()
    } else {
      timer = setTimeout(() => {
        timer = null
        onTap()
      }, tapDelayMs)
    }
  }

  return {
    registerTap,
    cancel,
    hasPendingTap: () => timer !== null,
    dispose: cancel,
  }
}

function integerDelta(value: number): number {
  return Number.isFinite(value) ? Math.trunc(value) : 0
}

function boundedDelta(value: number): number {
  return Math.max(-MAX_DELTA, Math.min(MAX_DELTA, value))
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}
