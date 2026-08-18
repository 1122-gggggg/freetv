# PC TV Box Protocol v1

The controller uses JSON over WebSocket. Every client-to-server message includes `version: 1`, a `type`, and a bounded `request_id` matching `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}`. Unknown fields and unknown message types are rejected.

## Endpoints

| Endpoint | Binding | Intended client |
|---|---|---|
| `/ws/remote` | Literal controller LAN IP, matching Host/Origin for the configured `server.transport`, paired token | Paired phone Remote |
| `/ws/tv` | Loopback plus exact local TV Origin | Local TV Launcher |
| `POST /api/pair` | Literal controller LAN IP, matching browser Origin for the configured transport | One-time pairing exchange |
| `GET /api/pairing` | Loopback only | Pairing-code display on TV |
| `DELETE /api/remote-token` | Literal controller LAN IP, matching browser Origin, `Authorization: Bearer <token>` | Revoke this paired Remote |

## Authentication

A Remote must first send `authenticate`; the server accepts no command, pointer, or text-input message before successful authentication.

```json
{
  "version": 1,
  "type": "authenticate",
  "request_id": "auth-42",
  "token": "opaque-long-lived-token"
}
```

Successful authentication yields an acknowledgement, then the current `state`. Invalid or expired tokens receive an `authentication_failed` error and the socket closes with application close code `4401`; clients discard their local token only for that authentication outcome. The raw token is never sent in a state message or written to logs. The initial authentication message must arrive within 10 seconds; expired tokens are excluded from state broadcasts.

`/ws/remote`, `POST /api/pair`, `DELETE /api/remote-token`, and `GET /remote` enforce a strict LAN boundary. Peer connections must originate from loopback or a private IPv4 address on the same directly connected subnet as an eligible private IPv4 address of an operational Ethernet (802.3) or native Wi-Fi (802.11) adapter. Windows derives that adapter set with `Get-NetAdapter -Physical` filtered to those media types, then resolves the peer's best route and requires that it use the same currently operational physical adapter. Cellular, Bluetooth PAN, VPN, Hyper-V, WSL, and other virtual adapters are excluded; this route check rejects overlapping virtual subnets. Off-subnet private, global/public, link-local, non-loopback IPv6, and malformed peer addresses are rejected before authentication.

Furthermore, `/ws/remote`, `POST /api/pair`, and `DELETE /api/remote-token` require `<scheme>://<controller-literal-IP>:<configured-port>` and the matching WebSocket scheme (`ws` or `wss`) with the same Host and browser Origin, where the controller host address must be loopback or the eligible physical-LAN IPv4 address. Scheme follows `server.transport`. Plaintext LAN HTTP and `ws://` are rejected only in HTTPS mode. This prevents an arbitrary DNS name from becoming a controller origin through DNS rebinding. Use the numeric URL printed by `start.ps1`, not a device name.

`/ws/tv` has no remote token because it is a local display channel. It therefore requires both a loopback client address and an Origin exactly matching the local launcher authority. Production startup uses the configured transport at `127.0.0.1:<configured-port>` (or another loopback literal); the loopback development proxy still uses plaintext. Cross-origin webpages cannot use it to issue local TV commands.

## TLS bootstrap

HTTPS mode only: `setup.ps1` creates a private local CA and `start.ps1` regenerates its leaf certificate whenever the exact physical-LAN address set changes. The leaf has exactly `localhost`, loopback addresses, and eligible private IPv4 addresses from operational physical Wi-Fi/Ethernet interfaces as DNS/IP SANs; it never trusts hostnames, VPNs, or virtual adapters. Install `config\tls\pc-tv-box-local-ca.cer` on the TV Windows user and each phone, comparing the SHA-256 fingerprint printed by `start.ps1` before trusting it. The CA certificate is public DER; its private key remains local and ignored by Git.

## Pairing

The TV Launcher gets the currently displayed code from `GET /api/pairing` on loopback. The phone exchanges it exactly once:

```http
POST /api/pair
Content-Type: application/json

{"code":"482731"}
```

Success:

```json
{"token":"opaque-long-lived-token"}
```

Codes are numeric, expire after the configured TTL, and are invalidated after success. Failed attempts are rate limited per client address. The Remote stores the returned token locally and immediately authenticates its WebSocket from the same numeric LAN origin.


## Remote token revocation

The Remote's **Forget** action sends:

```http
DELETE /api/remote-token
Authorization: Bearer opaque-long-lived-token
```

The controller verifies and removes the token's persisted salted hash, closes any Remote WebSocket authenticated by that token, and returns `204 No Content`. The caller removes local storage only after a successful response. A `401` means the token had already expired or been revoked, so the client must discard it locally.

## Commands

```json
{
  "version": 1,
  "type": "command",
  "request_id": "cmd-43",
  "command": "NAV_RIGHT"
}
```

Allowed command values:

- `NAV_UP`, `NAV_DOWN`, `NAV_LEFT`, `NAV_RIGHT`, `OK`, `BACK`, `HOME`
- `PLAY_PAUSE`, `NEXT`, `PREVIOUS`
- `VOLUME_UP`, `VOLUME_DOWN`, `MUTE`
- `CHANNEL_UP`, `CHANNEL_DOWN`
- `OPEN_YOUTUBE`, `OPEN_NETFLIX`, `OPEN_LIVE_TV`, `OPEN_BROWSER`, `POWER_SLEEP`

There is no raw keyboard, shell, script, URL, process, path, or arbitrary command message.

## Bounded pointer action

```json
{
  "version": 1,
  "type": "pointer",
  "request_id": "pointer-44",
  "action": "move",
  "dx": 18,
  "dy": -7
}
```

- `action` is one of `move`, `tap`, `double_tap`, `scroll`.
- Movement is relative and bounded by the protocol model.
- Scroll uses bounded relative wheel delta.
- Click actions have no coordinate field.

This intentionally cannot position the pointer absolutely or inject arbitrary mouse/keyboard sequences.

## Text input

```json
{
  "version": 1,
  "type": "text_input",
  "request_id": "text-45",
  "text": "Search phrase"
}
```

Text is limited to 256 characters. Control characters are removed before dispatch and Unicode text is sent to the foreground application with Windows Unicode input events. Text is data, not a shell or command language.

## Acknowledgement and errors

Every accepted state-changing request receives an `ack`:

```json
{
  "version": 1,
  "type": "ack",
  "request_id": "cmd-43",
  "success": true
}
```

Failure:

```json
{
  "version": 1,
  "type": "ack",
  "request_id": "cmd-43",
  "success": false,
  "error_code": "application_unavailable",
  "message": "Brave is not installed or configured."
}
```

Malformed protocol data produces a non-sensitive `error` message. A client should show the error and reconnect only with backoff; it must not spin/retry a rejected request. A `1008` policy close is not evidence that a token is invalid, so clients must preserve pairing credentials for that case.

## State broadcast

```json
{
  "version": 1,
  "type": "state",
  "active_app": "live_tv",
  "focused_tile": "live_tv",
  "volume": 42,
  "muted": false,
  "channel_number": 3,
  "channel_name": "Demo News",
  "error_message": null,
  "status_message": "CH 03 Demo News"
}
```

The server broadcasts a state message to every still-valid authenticated Remote after an observable change. State is authoritative; clients do not independently implement application-control decisions.
