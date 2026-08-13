# PC TV Box Engineering Guide

## Product boundary

This repository builds a per-user Windows 11 TV controller. It runs locally on the HDMI-connected PC and accepts paired remotes only over the LAN. It does not implement DRM bypass, ad blocking, IPTV discovery/scraping, arbitrary shell execution, or unrestricted remote keyboard control.

## Architecture invariants

- Every control source emits a typed `Command`; only `CommandBus` dispatches it.
- Network clients never call Windows APIs, `subprocess`, mpv, or application launchers directly.
- Remote WebSocket traffic is authenticated after pairing. The TV WebSocket is loopback-only.
- All remote input is a whitelist: commands, bounded relative pointer actions, and sanitized text input. Never add a raw command or arbitrary key-sequence API.
- `ApplicationManager` owns applications launched by this project. Never terminate all Brave, Edge, or mpv processes; minimize a specific launched window or terminate tracked children only.
- Windows-dependent code belongs behind small protocols with fake implementations for tests.
- Configuration is typed and loaded from `config/settings.json`; example files are committed and local files, tokens, and logs are ignored.

## Python conventions

- Target Python 3.11+; use `from __future__ import annotations` and fully typed public interfaces.
- Keep `app/` modules focused: protocol/models, command dispatch, application control, player control, security, system integration, and API transport.
- Use argument arrays with `subprocess.Popen`; never build shell command strings from remote data.
- Log structured event fields without secrets, tokens, cookies, passwords, or pairing codes.
- Validate all external input at the transport boundary with Pydantic models.
- Prefer explicit errors returned to UI state over traceback-driven user experiences.

## Frontend conventions

- `/tv` and `/remote` share protocol types and a reconnecting WebSocket client, but remain separate route components.
- TV UI is keyboard-first and 10-foot readable; mobile UI is touch-first with safe-area spacing.
- UI state follows server state. Do not duplicate application-control logic in React.
- Do not use unbounded retry loops or per-pointer-event renders; coalesce touchpad movement.
- Use semantic buttons, visible focus indicators, and `aria-live` status for connection and errors.

## Verification and commits

- Add a behavior test for every observable backend contract and critical navigation rule.
- Run targeted tests after each vertical slice, then the backend suite, frontend lint/typecheck/build, and browser smoke test before completion.
- Commit logical, tested checkpoints. Never commit `.venv`, `node_modules`, `dist`, `config/settings.json`, paired tokens, or logs.
