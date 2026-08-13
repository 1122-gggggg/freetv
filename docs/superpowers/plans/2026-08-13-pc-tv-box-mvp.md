# PC TV Box MVP Implementation Plan

> **For agentic workers:** Implement in dependency order; each checkpoint must pass before the next group is expanded.

**Goal:** Deliver a local Windows 11 TV launcher with a paired, authenticated mobile remote and controlled browser/mpv integration.

**Architecture:** FastAPI is the only local server and serves the Vite build. A typed WebSocket protocol feeds a command bus that owns controller state; platform adapters are injectable. The React TV and remote routes subscribe to that state rather than reaching Windows integrations directly.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, Pydantic, psutil, ctypes/optional Core Audio wrapper, React, TypeScript, Vite, Vitest, ESLint.

## Global constraints

- Listen on `0.0.0.0:8765` by default; no cloud, no port-forwarding setup, and no CORS dependency.
- Restrict the TV control socket and pairing-code endpoint to loopback.
- Require a valid paired token before a remote command, pointer action, or text-input action.
- Use command, pointer-action, and text-input schemas; no shell, PowerShell, filesystem, or arbitrary key APIs are network reachable.
- Preserve browser profiles; never kill all Brave or Edge processes.
- Keep example settings/channels committed and local settings, tokens, logs, builds, and dependencies ignored.

## File map

- `backend/app/config.py`: typed JSON configuration and executable discovery.
- `backend/app/protocol.py`: wire models, command enum, acknowledgement and state models.
- `backend/app/state.py`: atomic controller state and subscriptions.
- `backend/app/security/`: pairing-code and hashed-token persistence.
- `backend/app/commands/`: dispatcher and command handlers.
- `backend/app/applications/`: launched application/window ownership.
- `backend/app/player/`: channels and mpv IPC.
- `backend/app/system/`: Windows input and volume adapters.
- `backend/app/websocket/`: client registry and WebSocket session handling.
- `backend/app/main.py`: lifespan, API, WebSocket, and static route integration.
- `frontend/src/`: shared protocol client, TV route, remote route, styles, PWA assets, and tests.
- `scripts/`: setup, start, development, and per-user autostart scripts.

## Tasks

### 1. Bootstrap repository and configuration

Create ignore rules, backend package metadata, frontend tooling configuration, settings examples, local configuration bootstrap, structured logging setup, and the health endpoint. Verify configuration validation and `GET /api/health` with pytest.

### 2. Define protocol, state, and security primitive tests

Create the version-1 JSON message models, command enum, state model, pairing-code service, hashed token store, and tests for invalid messages, token verification, and expired pairing codes. Verify with focused pytest tests before transport code exists.

### 3. Add command bus and controller state transitions

Implement a dispatcher with injected application, player, input, and volume ports. Cover launcher navigation, activation, global Home, and acknowledgement results with fakes. Verify state broadcasts are generated after every changed state.

### 4. Add Windows adapters and application ownership

Implement bounded `SendInput` adapters, sanitized Unicode text input, Core Audio volume handling with graceful unavailability, executable discovery, browser launching, tracked window minimization, and no process-wide browser termination. Verify command argument construction and ownership behavior with fakes.

### 5. Add Live TV and mpv IPC

Implement typed channels, wrap-around switching, mpv process launch, JSON IPC requests, overlay state, and graceful mpv failures. Verify channel behavior and IPC command framing with fakes; leave actual mpv validation conditional on its installation.

### 6. Add FastAPI and WebSocket integration

Wire lifespan, loopback TV socket, remote auth handshake, command acknowledgement, pairing HTTP route, client registry, state fan-out, and static SPA fallback. Verify unauthenticated socket rejection, paired command acknowledgement, and multi-client state broadcasting.

### Checkpoint: backend controller

Run the complete backend suite, start Uvicorn, and request `/api/health`. The service must remain available when browser or mpv executables are absent.

### 7. Build shared React protocol client and application shell

Create the Vite React TypeScript application, route switch for `/tv` and `/remote`, versioned WebSocket types, reconnection/backoff client, acknowledgement tracking, web manifest, and worker registration. Verify `tsc`, ESLint, Vitest, and production build.

### 8. Build TV launcher

Implement 16:9 dark TV layout, five large focusable tiles, arrow/Enter/Escape/Home handling, server-state focus synchronization, pairing display, status/error overlay, and responsive scaling. Add navigation tests and browser smoke coverage.

### 9. Build mobile remote

Implement pairing form, connection state, large command buttons, haptic feedback where available, acknowledgement feedback, touchpad gesture translation with animation-frame coalescing, and sanitized text-entry UI. Verify mobile viewport rendering and WebSocket command flow in Chromium.

### Checkpoint: end-to-end UI

Serve the production build with FastAPI, load `/tv` and `/remote`, pair through the UI, move TV focus with a remote command, execute a launcher action, and return with Home.

### 10. Add operating scripts and documentation

Create setup/start/development/autostart PowerShell scripts. Write README, architecture, protocol, and Windows setup documents covering requirements, pairing, programs, channel setup, security, troubleshooting, limitations, and extension boundaries.

### 11. Security and release verification

Review input validation, token handling, errors, subprocess arguments, static routing, logging, and LAN exposure. Run backend tests, frontend lint/typecheck/build, browser integration smoke test, and executable availability checks. Commit tested checkpoints with conventional messages.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| mpv is not installed | Setup detects it, Live TV fails gracefully, and final test reports the missing dependency. |
| Browser process forwarding breaks PID ownership | Record the particular foreground window and only minimize it; never mass-kill browser processes. |
| Phone PWA features require a secure context | Supply manifest/worker and document that full install prompts on LAN need trusted HTTPS; the responsive remote remains usable on HTTP. |
| Native Windows APIs unavailable in tests | Keep protocol ports and fakes separate from Windows adapters. |
| Untrusted LAN client controls PC | Require pairing, expire codes, hash stored tokens, and authenticate every state-changing WebSocket message. |

## Execution order and parallel contract

After tasks 1–3 define `ProtocolMessage`, `ControllerState`, `CommandDispatcher`, and the REST/WebSocket paths, independent work may proceed in parallel: TV UI, mobile remote, Windows/player adapters, and documentation/tests. All branches consume the shared version-1 protocol; no branch changes it without updating the protocol document and tests.
