import {
  createPointerCoalescer,
  createTapHandler,
  FRAME_MS,
} from './pointerCoalescer'

describe('createPointerCoalescer', () => {
  beforeEach(() => {
    jest.useFakeTimers()
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  it('combines pointer moves into one bounded frame', () => {
    const emit = jest.fn()
    const coalescer = createPointerCoalescer(emit)

    coalescer.move(12, -3)
    coalescer.move(-2, 11)
    jest.advanceTimersByTime(FRAME_MS)

    expect(emit).toHaveBeenCalledTimes(1)
    expect(emit).toHaveBeenCalledWith('move', 10, 8)
  })

  it('emits at most one bounded move chunk per frame and reschedules leftover work', () => {
    const emit = jest.fn()
    const coalescer = createPointerCoalescer(emit)

    coalescer.move(240, -215)

    // Frame 1: emits first bounded chunk
    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenCalledTimes(1)
    expect(emit).toHaveBeenLastCalledWith('move', 100, -100)

    // Frame 2: emits second bounded chunk
    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenCalledTimes(2)
    expect(emit).toHaveBeenLastCalledWith('move', 100, -100)

    // Frame 3: emits remaining leftover chunk
    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenCalledTimes(3)
    expect(emit).toHaveBeenLastCalledWith('move', 40, -15)

    // Frame 4: all deltas consumed, no extra emits
    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenCalledTimes(3)
  })

  it('emits at most one bounded scroll chunk per frame and reschedules leftover work', () => {
    const emit = jest.fn()
    const coalescer = createPointerCoalescer(emit)

    coalescer.scroll(250)

    // Frame 1
    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenCalledTimes(1)
    expect(emit).toHaveBeenLastCalledWith('scroll', 0, 100)

    // Frame 2
    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenCalledTimes(2)
    expect(emit).toHaveBeenLastCalledWith('scroll', 0, 100)

    // Frame 3
    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenCalledTimes(3)
    expect(emit).toHaveBeenLastCalledWith('scroll', 0, 50)

    // Frame 4
    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenCalledTimes(3)
  })

  it('caps pending accumulated move deltas to prevent unbounded stale movement', () => {
    const emit = jest.fn()
    const coalescer = createPointerCoalescer(emit)

    // Move exceeds MAX_ACCUMULATED_DELTA (300)
    coalescer.move(1000, -1000)

    // Frame 1
    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenLastCalledWith('move', 100, -100)

    // Frame 2
    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenLastCalledWith('move', 100, -100)

    // Frame 3
    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenLastCalledWith('move', 100, -100)

    // Frame 4: capped at 300 so no further calls occur
    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenCalledTimes(3)
  })

  it('caps pending accumulated scroll deltas', () => {
    const emit = jest.fn()
    const coalescer = createPointerCoalescer(emit)

    coalescer.scroll(800)

    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenLastCalledWith('scroll', 0, 100)

    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenLastCalledWith('scroll', 0, 100)

    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenLastCalledWith('scroll', 0, 100)

    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenCalledTimes(3)
  })

  it('cancels queued input and leftover chunks when cancel() is called', () => {
    const emit = jest.fn()
    const coalescer = createPointerCoalescer(emit)

    coalescer.move(250, 0)
    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenCalledTimes(1)
    expect(emit).toHaveBeenLastCalledWith('move', 100, 0)

    coalescer.cancel()
    jest.advanceTimersByTime(FRAME_MS * 3)

    expect(emit).toHaveBeenCalledTimes(1)
  })

  it('flush emits one chunk immediately and schedules leftover work', () => {
    const emit = jest.fn()
    const coalescer = createPointerCoalescer(emit)

    coalescer.move(150, 0)
    coalescer.flush()

    expect(emit).toHaveBeenCalledTimes(1)
    expect(emit).toHaveBeenCalledWith('move', 100, 0)

    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).toHaveBeenCalledTimes(2)
    expect(emit).toHaveBeenLastCalledWith('move', 50, 0)
  })

  it('dispose cancels timers and ignores subsequent inputs', () => {
    const emit = jest.fn()
    const coalescer = createPointerCoalescer(emit)

    coalescer.move(100, 50)
    coalescer.dispose()

    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).not.toHaveBeenCalled()

    coalescer.move(50, 50)
    coalescer.scroll(30)
    jest.advanceTimersByTime(FRAME_MS)
    expect(emit).not.toHaveBeenCalled()
  })

  it('emits both move and scroll in the same frame when both are queued', () => {
    const emit = jest.fn()
    const coalescer = createPointerCoalescer(emit)

    coalescer.move(20, 30)
    coalescer.scroll(-40)
    jest.advanceTimersByTime(FRAME_MS)

    expect(emit).toHaveBeenCalledTimes(2)
    expect(emit).toHaveBeenCalledWith('move', 20, 30)
    expect(emit).toHaveBeenCalledWith('scroll', 0, -40)
  })

  it('safely handles non-finite delta inputs', () => {
    const emit = jest.fn()
    const coalescer = createPointerCoalescer(emit)

    coalescer.move(NaN, Infinity)
    coalescer.scroll(-Infinity)
    jest.advanceTimersByTime(FRAME_MS)

    expect(emit).not.toHaveBeenCalled()
  })
})

describe('createTapHandler', () => {
  beforeEach(() => {
    jest.useFakeTimers()
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  it('delays single tap by 250ms and emits tap once', () => {
    const onTap = jest.fn()
    const onDoubleTap = jest.fn()
    const tapHandler = createTapHandler({ onTap, onDoubleTap, tapDelayMs: 250 })

    tapHandler.registerTap()
    expect(tapHandler.hasPendingTap()).toBe(true)
    expect(onTap).not.toHaveBeenCalled()
    expect(onDoubleTap).not.toHaveBeenCalled()

    jest.advanceTimersByTime(249)
    expect(onTap).not.toHaveBeenCalled()
    expect(tapHandler.hasPendingTap()).toBe(true)

    jest.advanceTimersByTime(1)
    expect(onTap).toHaveBeenCalledTimes(1)
    expect(onDoubleTap).not.toHaveBeenCalled()
    expect(tapHandler.hasPendingTap()).toBe(false)
  })

  it('cancels pending single tap and emits double_tap when second qualifying tap arrives within 250ms', () => {
    const onTap = jest.fn()
    const onDoubleTap = jest.fn()
    const tapHandler = createTapHandler({ onTap, onDoubleTap, tapDelayMs: 250 })

    tapHandler.registerTap()
    expect(tapHandler.hasPendingTap()).toBe(true)

    // Second tap at 120ms
    jest.advanceTimersByTime(120)
    tapHandler.registerTap()

    expect(onDoubleTap).toHaveBeenCalledTimes(1)
    expect(onTap).not.toHaveBeenCalled()
    expect(tapHandler.hasPendingTap()).toBe(false)

    // After 250ms more, single tap should not fire
    jest.advanceTimersByTime(300)
    expect(onTap).not.toHaveBeenCalled()
    expect(onDoubleTap).toHaveBeenCalledTimes(1)
  })

  it('cancels pending tap when cancel() is called (movement, multi-touch, termination)', () => {
    const onTap = jest.fn()
    const onDoubleTap = jest.fn()
    const tapHandler = createTapHandler({ onTap, onDoubleTap, tapDelayMs: 250 })

    tapHandler.registerTap()
    expect(tapHandler.hasPendingTap()).toBe(true)

    jest.advanceTimersByTime(100)
    tapHandler.cancel()
    expect(tapHandler.hasPendingTap()).toBe(false)

    jest.advanceTimersByTime(300)
    expect(onTap).not.toHaveBeenCalled()
    expect(onDoubleTap).not.toHaveBeenCalled()
  })

  it('treats tap after delay expiration as a fresh single tap', () => {
    const onTap = jest.fn()
    const onDoubleTap = jest.fn()
    const tapHandler = createTapHandler({ onTap, onDoubleTap, tapDelayMs: 250 })

    tapHandler.registerTap()
    jest.advanceTimersByTime(250)
    expect(onTap).toHaveBeenCalledTimes(1)

    tapHandler.registerTap()
    jest.advanceTimersByTime(250)
    expect(onTap).toHaveBeenCalledTimes(2)
    expect(onDoubleTap).not.toHaveBeenCalled()
  })

  it('dispose cancels pending timer', () => {
    const onTap = jest.fn()
    const onDoubleTap = jest.fn()
    const tapHandler = createTapHandler({ onTap, onDoubleTap })

    tapHandler.registerTap()
    tapHandler.dispose()

    jest.advanceTimersByTime(300)
    expect(onTap).not.toHaveBeenCalled()
    expect(onDoubleTap).not.toHaveBeenCalled()
  })
})
