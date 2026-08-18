# Cloudflare Tunnel Remote Access Design

## Objective

A phone off the PC's LAN can scan the TV QR and control the box. Reachability is a Cloudflare quick tunnel to local `http://127.0.0.1:8765`. No router port-forward, no public bind of 8765, no native phone app.

## Decisions

1. Transport remains the existing HTTP LAN controller. The tunnel terminates TLS at Cloudflare and forwards to loopback HTTP.
2. `start.ps1` starts `cloudflared tunnel --url http://127.0.0.1:8765` after the controller is healthy, unless `-NoTunnel` is passed.
3. The printed `https://<id>.trycloudflare.com` URL is the public origin. Pairing `remote_url` becomes `https://<id>.trycloudflare.com/remote`. The TV QR uses that value.
4. Backend accepts Host/Origin equal to that public hostname **or** the existing LAN-IP rules. Peer check stays: Cloudflare arrives via local `cloudflared`, so the TCP peer is loopback (already trusted).
5. Quick tunnels are ephemeral. Each `start.ps1` may mint a new hostname; users rescan the QR. Named Cloudflare accounts / custom domains are out of scope.
6. Pairing code, token, 10s auth timeout, and rate limits stay. The public URL is not a secret; the pairing code is.
7. `/ws/tv` and `/api/pairing` stay loopback-only. Phones never use the TV socket.

## Architecture

```text
Phone ─ HTTPS ─ Cloudflare ─ cloudflared on PC ─ 127.0.0.1:8765 /remote + /ws/remote
HDMI TV ─ Edge kiosk ─ http://127.0.0.1:8765/tv
```

`start.ps1` flow:

1. Start uvicorn as today (HTTP default).
2. Wait for `/api/health`.
3. Spawn `cloudflared` if present; parse the first `https://*.trycloudflare.com` from stdout.
4. Write the origin to `config/tunnel-origin.txt` (gitignored) and pass it into the process environment `PC_TV_PUBLIC_ORIGIN`.
5. Restart is not required if the backend reads the origin file on each pairing request; prefer that over a uvicorn restart.

Backend:

- New helper `_is_public_tunnel_host(host) -> bool` matching the current origin hostname from `PC_TV_PUBLIC_ORIGIN` or `config/tunnel-origin.txt`.
- `_is_controller_host` returns true for that hostname as well as LAN/loopback.
- `_pairing_remote_url` prefers the public HTTPS origin when set; otherwise existing LAN `http://<ip>:port/remote`.
- Origin/Host port: trycloudflare uses 443; compare hostname only for the public origin (ignore missing port).

## Setup

`setup.ps1` checks for `cloudflared` on PATH. If missing, print install hint (`winget install Cloudflare.cloudflared`) and continue; LAN remote still works. Do not fail setup.

## Error handling

| condition | behavior |
|---|---|
| cloudflared missing | start.ps1 warns; QR stays LAN URL |
| tunnel URL not printed in 30s | warn; LAN URL |
| origin file stale/empty | LAN URL only; public Host rejected |
| phone uses old QR after restart | pairing/origin 403 or wrong host; rescan |

## Testing

- With `PC_TV_PUBLIC_ORIGIN=https://abc.trycloudflare.com`, pairing `remote_url` is that origin + `/remote`.
- `POST /api/pair` with Host/Origin `https://abc.trycloudflare.com` from a loopback client succeeds (existing pairing code).
- Same request with Host `evil.example` still 403.
- Without public origin, LAN IP behavior unchanged.
- Do not call the live Cloudflare network in CI. Parse a fixture log line for `trycloudflare.com`.

## Out of scope

- Named tunnels, Cloudflare Zero Trust login, custom domains.
- Exposing `/tv` as the phone UI.
- Changing pairing/token crypto.
- Opening Windows firewall for public 8765.
