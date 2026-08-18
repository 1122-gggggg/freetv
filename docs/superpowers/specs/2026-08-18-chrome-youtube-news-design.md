# Chrome YouTube, Store AdBlock, Official News, HDMI Kiosk, Phone Remote

## Objective

The PC on HDMI is the TV. YouTube and News open fullscreen in an isolated TV Chrome profile with Chrome Web Store AdBlock (`gighmmpiobklfepjocnamgkkbiglidom`). Daily control: scan the TV QR; `/remote` is a handset with YouTube / Netflix / 新聞, D-pad, voice, and video search. Netflix stays on Edge. News is official YouTube Live URLs switched with `CHANNEL_UP` / `CHANNEL_DOWN`. No IPTV scraping, no extra extensions, no daily-Chrome mutation.

## Decisions

1. YouTube and News use Google Chrome, not Brave.
2. Chrome uses `--user-data-dir` under ignored `config/chrome-tv-profile`. Daily Chrome is never launched with these flags.
3. Ad blocking is only [AdBlock — block ads across the web](https://chromewebstore.google.com/detail/adblock-%E2%80%94-block-ads-acros/gighmmpiobklfepjocnamgkkbiglidom), ID `gighmmpiobklfepjocnamgkkbiglidom`. `setup.ps1` downloads that ID from Chrome's official update endpoint into `vendor/adblock`.
4. News sources are official YouTube `/live` URLs in `config/news.example.json`. First setup copies to ignored `config/news.json`.
5. Live TV / mpv remains a separate HLS path. News never goes through mpv.
6. Netflix stays Edge-only and never loads AdBlock.
7. Product-boundary docs: no IPTV discovery/scraping, no extra extensions, no DRM bypass. Ad blocking is only this store AdBlock ID in the TV Chrome profile.
8. HDMI is the only TV display. Launcher, YouTube, and News are exclusive fullscreen kiosk.
9. `/remote` is a physical-remote layout: three app keys (YouTube, Netflix, 新聞), D-pad, Back/Home/Ch+/Ch−, one voice button, one search field.

## Architecture

```text
Phone camera ─ scan TV QR ─ /remote handset ─ WebSocket
HDMI TV ─ Edge kiosk /tv
OPEN_YOUTUBE / OPEN_NEWS / search_video ─ chrome.exe --kiosk + TV profile + AdBlock
OPEN_NETFLIX ─ msedge.exe
OPEN_LIVE_TV ─ mpv --fullscreen
```

New protocol values:

- `Command.OPEN_NEWS`
- `ActiveApp.NEWS = "news"`
- `LauncherTile.NEWS = "news"`
- Wire message `search_video` with `query` (1–128 sanitized characters)

TV launcher grid:

```text
YouTube    Netflix
News       Live TV
Browser    Settings
```

Focus: YouTube right Netflix, down News; Netflix left YouTube, down Live TV; News up YouTube, right Live TV, down Browser; Live TV up Netflix, left News, down Settings; Browser up News, right Settings; Settings up Live TV, left Browser. `OK` on News dispatches `OPEN_NEWS`.

## Components

### Chrome resolution

`ApplicationSettings.chrome_path` (default empty). Resolve `chrome.exe` at standard Windows paths. Health exposes `chrome_available`. Missing Chrome fails YouTube/News/search only.

### Isolated profile, AdBlock, kiosk

YouTube, News, and search launch:

```
chrome.exe
  --user-data-dir=<repo>/config/chrome-tv-profile
  --disable-extensions-except=<repo>/vendor/adblock
  --load-extension=<repo>/vendor/adblock
  --kiosk
  --no-first-run
  --no-default-browser-check
  --autoplay-policy=no-user-gesture-required
  <url>
```

No `--new-window` / `--start-maximized` on these launches. Refuse YouTube/News/search if `vendor/adblock/manifest.json` is missing (`adblock_not_installed`). Setup must verify the unpacked extension ID is `gighmmpiobklfepjocnamgkkbiglidom` before success.

`start.ps1` already opens `/tv` with Edge `--kiosk --edge-kiosk-type=fullscreen`. Keep that. Do not change Windows display topology.

Netflix and the generic Browser tile do not use the TV Chrome profile or AdBlock. Live TV / mpv already uses `--fullscreen`.

### News channels

`config/news.example.json`:

| number | id | name | url |
|---:|---|---|---|
| 1 | dw-news | DW News | `https://www.youtube.com/@dwnews/live` |
| 2 | aljazeera-english | Al Jazeera English | `https://www.youtube.com/@aljazeeraenglish/live` |
| 3 | pbs-newshour | PBS NewsHour | `https://www.youtube.com/@pbsnewshour/live` |
| 4 | france24-english | France 24 English | `https://www.youtube.com/@FRANCE24English/live` |

Same `Channel` fields. URLs must be `https` on `youtube.com` / `www.youtube.com`. `NewsChannelManager` is separate from mpv `ChannelManager`, loaded from `config/news.json` (fallback example).

`OPEN_NEWS` opens kiosk Chrome at the current news URL and sets `active_app=news` plus channel fields.

`CHANNEL_UP` / `CHANNEL_DOWN`:

- `news`: next official `/live` URL in the tracked kiosk Chrome window
- `live_tv`: existing mpv behavior
- otherwise: `channel_source_not_active` ("Open News or Live TV before changing channels.")

An offline official `/live` page still opens.

### Phone QR remote (handset)

TV shows pairing QR (`remote_url?code=`). Phone scan opens `/remote`. No native app required.

Handset, top to bottom:

1. App row: **YouTube**, **Netflix**, **新聞**.
2. D-pad: up/down/left/right/OK.
3. Transport: Back, Home, Ch+, Ch−. Volume up/down if they already fit this row.
4. Voice: hold-to-talk, phone Web Speech API (`zh-TW`, then `en-US`). Transcript fills search and may auto-submit.
5. Search: one field + 搜片. Sends `search_video`. Backend switches to YouTube if News/Live TV is active, then opens kiosk Chrome at `https://www.youtube.com/results?search_query=<urlencoded>`. Query is never a shell, file path, or raw URL command.

Remove from the default handset: Browser tile, Live TV tile, touchpad, free-text-to-active-app, power.

### Ownership

Home minimizes only the tracked Chrome/Edge/mpv window. News channel changes replace only that tracked Chrome window.

## Setup and packaging

`setup.ps1`:

1. Resolve Chrome like Edge/Brave.
2. If `vendor/adblock/manifest.json` is absent, download `https://clients2.google.com/service/update2/crx?response=redirect&prodversion=120.0&acceptformat=crx3&x=id%3Dgighmmpiobklfepjocnamgkkbiglidom%26uc`, unpack to `vendor/adblock`, verify ID. Do not scrape Web Store HTML.
3. Copy `config/news.example.json` → `config/news.json` when missing.

`.gitignore`: `config/chrome-tv-profile/`, `vendor/adblock/`. Do not commit the CRX. First YouTube/News/search may require Google sign-in in the TV Chrome profile.

## Error handling

| condition | code | user-visible |
|---|---|---|
| Chrome missing | `chrome_not_found` | Install Chrome or set `applications.chrome_path`. |
| AdBlock missing or wrong ID | `adblock_not_installed` | Re-run `setup.ps1`. |
| news.json empty/invalid | `news_not_configured` | News tile fails; other tiles work. |
| empty/invalid search query | `invalid_search_query` | Handset shows the error; no launch. |
| setup download fail | setup throws | Do not leave a partial extension dir as success. |

## Testing

- YouTube argv includes `--kiosk`, TV profile, both extension flags, YouTube URL; no `--start-maximized`.
- News argv uses the current official `/live` URL and the same kiosk flags.
- `CHANNEL_UP` from news 1 opens news 2; wrap last→first.
- `CHANNEL_UP` on YouTube/Netflix returns `channel_source_not_active`.
- `search_video` `cat videos` launches the YouTube results URL in kiosk Chrome.
- Voice is phone-side only; backend tests cover `search_video` validation, not SpeechRecognition.
- Missing Chrome / missing AdBlock / empty news list return the codes above.
- Netflix argv has no `--load-extension` and no TV Chrome profile.
- Remote UI: YouTube / Netflix / 新聞 / voice / search present; Browser / Live TV / touchpad absent.
- QR still encodes `remote_url?code=`. Do not assert ads are blocked. Do not require a live broadcast. Do not change Windows display mode.

## Out of scope

- Installing AdBlock into daily Chrome.
- Extra extensions, sponsor skippers, unofficial YouTube clients.
- IPTV playlist scraping.
- Netflix DRM/credentials.
- Native app redesign beyond `news` and `search_video` if types are shared.
- Changing Windows HDMI topology.
- Server-side speech recognition.
