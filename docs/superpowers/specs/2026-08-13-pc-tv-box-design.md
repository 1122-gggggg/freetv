# PC TV Box MVP Design

## Objective

Turn a Windows 11 laptop connected through HDMI into a local TV box. The owner opens the launcher after sign-in, pairs a phone on the same LAN, and controls a launcher, Brave YouTube, Edge Netflix, a configurable browser, and mpv Live TV without exposing arbitrary PC control.

The supplied task specification is the approved product design. Implementation proceeds without an additional approval gate.

## Assumptions decided for the MVP

1. The React application is built once and served by the FastAPI process, so `/tv` and `/remote` share one origin and no cloud service is needed.
2. TV Launcher is opened at `http://127.0.0.1:8765/tv`; its WebSocket is accepted only from loopback. Phones use the detected LAN IPv4 address.
3. Pairing codes are six digits, expire after ten minutes, and are exposed only through the loopback TV endpoint. Long-lived remote credentials are random opaque tokens, persisted only as hashes.
4. Pointer control uses bounded relative deltas and a fixed action whitelist. Text input accepts at most 256 sanitized printable Unicode characters and uses Windows Unicode input events, never a shell or arbitrary key-sequence API.
5. Browsers use their existing profiles. The controller tracks the process it started and the specific foreground window it launched; Home minimizes only that window and never kills all browser processes.
6. The installed computer has Edge at the standard Program Files path and Brave at the standard Program Files path. mpv was not found during discovery, so Live TV runtime verification must report the external dependency as missing until installed.

## Evaluated architectures

### A. Native-shell launcher with an embedded web remote

A Tauri/Electron shell could hide Windows more completely, but it introduces a second runtime, packaging, native update work, and a separate web service for phones. It is disproportionate for the first executable MVP.

### B. FastAPI controller plus React static UI — selected

FastAPI owns pairing, WebSockets, Windows integration, process lifecycle, and static UI hosting. React supplies `/tv` and `/remote`; all controls go through a versioned WebSocket protocol and a typed backend command bus. This matches the required stack, has one local server, and remains testable without external software.

### C. Separate frontend development server and Windows controller

This is convenient in development but creates CORS, port, lifecycle, and deployment complexity. It is not used in production; Vite is development/build tooling only.

## Component design

```text
TV keyboard ─┐
Phone remote ├─ versioned WebSocket ─ CommandBus ─ ApplicationManager ─ Windows / browsers / mpv
Future input ┘                            │
                                           └─ ControllerState ─ broadcast ─ TV and paired remotes
```

- `protocol`: typed Pydantic messages and the command enum.
- `security`: pairing-code lifecycle and hashed-token store.
- `commands`: command validation and dispatch only.
- `applications`: browser/window ownership and Home behavior.
- `player`: channel selection and mpv JSON IPC.
- `system`: Windows input and Core Audio volume adapters behind protocols.
- `websocket`: authenticated connection registry, acknowledgements, and state broadcasts.
- `frontend`: two route components over one reconnecting client.

## Failure handling

Missing programs produce a stable user-facing state error, a structured log event, and a failed command acknowledgement; the backend stays alive. mpv connection failures do not take down the controller. WebSocket disconnects clean up their connection and clients reconnect using exponential backoff.

## Testing strategy

Backend unit/integration tests cover command validation, pairing expiry, token verification, unauthenticated WebSocket rejection, channel wrapping, state transitions, config loading, and application ownership behavior using fakes. Frontend tests cover launcher navigation and protocol client acknowledgement handling. The final smoke test starts FastAPI, loads `/tv` and `/remote` in Chromium, pairs a remote, sends navigation and app commands, and confirms Home returns launcher. Missing Brave, Edge, or mpv are reported separately rather than hidden.

## Boundaries

Always validate message shapes, authenticate remote state changes, use subprocess argument arrays, avoid secret logging, and test observable behavior. Never add arbitrary command execution, route filesystem paths from the network, bypass DRM, manipulate Netflix credentials, or ship unlicensed streams.
