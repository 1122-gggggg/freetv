# Chrome YouTube News HDMI Remote Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HDMI kiosk TV plus phone QR handset: YouTube/News in isolated Chrome with store AdBlock, Netflix on Edge, official YouTube Live channel-up, voice+search on the phone.

**Architecture:** Keep FastAPI `CommandBus` as the only dispatcher. Add `OPEN_NEWS`, `ActiveApp.NEWS`, `search_video`, and a `NewsChannelManager` loaded from `config/news.json`. `ApplicationManager` launches YouTube/News/search as Chrome `--kiosk` with `--user-data-dir=config/chrome-tv-profile` and unpacked AdBlock `gighmmpiobklfepjocnamgkkbiglidom`. `/remote` becomes a three-app handset; `/tv` stays Edge kiosk from `start.ps1`.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, React/TypeScript, Vite/Vitest, PowerShell setup.

## Global Constraints

- YouTube/News/search use Chrome only; never Brave for those three paths.
- Ad blocking is only unpacked store AdBlock ID `gighmmpiobklfepjocnamgkkbiglidom` under `vendor/adblock`.
- TV Chrome profile is ignored `config/chrome-tv-profile`. Daily Chrome is never launched with TV flags.
- News URLs must be `https` on `youtube.com` or `www.youtube.com`. No IPTV scraping.
- Netflix argv never includes `--load-extension` or the TV Chrome profile.
- YouTube/News/search argv use `--kiosk` and never `--start-maximized` / `--new-window`.
- `search_video.query` is 1–128 sanitized visible characters; never a shell, path, or raw URL command.
- Do not change Windows HDMI topology.
- Do not commit `vendor/adblock/`, `config/chrome-tv-profile/`, or `config/news.json`.
- Native app: only widen shared protocol types if they already mirror frontend types; no handset redesign.

## File map

- `backend/app/protocol.py`: `OPEN_NEWS`, `SearchVideoMessage`, client union.
- `backend/app/state.py`: `ActiveApp.NEWS`, `LauncherTile.NEWS`.
- `backend/app/config.py`: `chrome_path`, Chrome discovery, `chrome_available`.
- `backend/app/applications/news.py`: official YouTube news list + move.
- `backend/app/applications/adblock.py`: download/unpack/verify store AdBlock CRX.
- `backend/app/applications/manager.py`: Chrome kiosk launch + news URL + search URL.
- `backend/app/commands/ports.py`: `open_news`, `search_youtube`.
- `backend/app/commands/bus.py`: news open, channel routing, `dispatch_search`.
- `backend/app/controller.py`: load news manager, pass into bus/manager.
- `backend/app/main.py`: dispatch `search_video`; health `chrome_available`.
- `config/news.example.json`, `config/settings.example.json`.
- `frontend/src/types/protocol.ts`, `tv/navigation.ts`, `tv/TVLauncher.tsx`, `remote/RemotePage.tsx`, `api/controllerSocket.ts`.
- `scripts/setup.ps1`, `.gitignore`, `AGENTS.md`, `docs/PROTOCOL.md`, `README.md`.

---

### Task 1: Protocol, state, and news list

**Files:**
- Modify: `backend/app/protocol.py`
- Modify: `backend/app/state.py`
- Create: `backend/app/applications/news.py`
- Create: `config/news.example.json`
- Test: `backend/tests/test_protocol_security.py` (extend) or `backend/tests/test_news.py`

**Interfaces:**
- Consumes: existing `sanitize_text`, `Channel`-like fields
- Produces: `Command.OPEN_NEWS`; `SearchVideoMessage(type="search_video", query: str)`; `ActiveApp.NEWS`; `LauncherTile.NEWS`; `NewsChannelManager.current/move(direction: int) -> Channel`; `load_news_channels(path: Path) -> list[Channel]`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_news.py
from pathlib import Path
import json
import pytest
from pydantic import ValidationError
from app.applications.news import NewsChannelManager, load_news_channels
from app.protocol import Command, parse_client_message
from app.state import ActiveApp, LauncherTile

def test_open_news_command_exists() -> None:
    assert Command.OPEN_NEWS == "OPEN_NEWS"
    assert ActiveApp.NEWS == "news"
    assert LauncherTile.NEWS == "news"

def test_search_video_message_sanitizes_and_bounds_query() -> None:
    message = parse_client_message(
        {"version": 1, "type": "search_video", "request_id": "s1", "query": "  cat videos\n"}
    )
    assert message.query == "cat videos"

def test_search_video_rejects_empty_or_oversized_query() -> None:
    with pytest.raises(ValidationError):
        parse_client_message({"version": 1, "type": "search_video", "request_id": "s1", "query": "   "})
    with pytest.raises(ValidationError):
        parse_client_message({"version": 1, "type": "search_video", "request_id": "s1", "query": "x" * 129})

def test_news_loader_rejects_non_youtube_https(tmp_path: Path) -> None:
    path = tmp_path / "news.json"
    path.write_text(json.dumps([
        {"id": "bad", "number": 1, "name": "Bad", "url": "https://example.com/live", "enabled": True}
    ]), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_news_channels(path)

def test_news_manager_wraps_channels(tmp_path: Path) -> None:
    path = tmp_path / "news.json"
    path.write_text(json.dumps([
        {"id": "dw-news", "number": 1, "name": "DW News", "url": "https://www.youtube.com/@dwnews/live", "enabled": True},
        {"id": "pbs-newshour", "number": 2, "name": "PBS NewsHour", "url": "https://www.youtube.com/@pbsnewshour/live", "enabled": True},
    ]), encoding="utf-8")
    manager = NewsChannelManager(load_news_channels(path))
    assert manager.current.id == "dw-news"
    assert manager.move(1).id == "pbs-newshour"
    assert manager.move(1).id == "dw-news"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_news.py`
Expected: FAIL (`OPEN_NEWS` / `search_video` / `news` module missing)

- [ ] **Step 3: Implement protocol, state, news module, example file**

Add `OPEN_NEWS` to `Command`. Add:

```python
class SearchVideoMessage(WireModel):
    version: Literal[PROTOCOL_VERSION]
    type: Literal["search_video"]
    request_id: str = Field(min_length=1, max_length=64, pattern=REQUEST_ID_PATTERN)
    query: str = Field(min_length=1, max_length=128)

    @field_validator("query", mode="before")
    @classmethod
    def sanitize_query(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("Search query must be a string.")
        sanitized = sanitize_text(value).strip()
        if not sanitized:
            raise ValueError("Search query must include visible characters.")
        return sanitized
```

Include it in `ClientMessage`. Add `NEWS` to both state enums.

`NewsChannel` / `load_news_channels`: reuse `Channel` from `app.player.channels` but extra validator: `parsed.scheme == "https"` and hostname in `{"youtube.com", "www.youtube.com"}`. `NewsChannelManager` copies `ChannelManager.move` / `current`.

Write `config/news.example.json` with the four official `/live` URLs from the spec.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_news.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/protocol.py backend/app/state.py backend/app/applications/news.py backend/tests/test_news.py config/news.example.json
git commit -m "feat: add news protocol and official YouTube news list"
```

---

### Task 2: Chrome discovery and kiosk ApplicationManager

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/applications/manager.py`
- Modify: `backend/app/commands/ports.py`
- Modify: `config/settings.example.json`
- Test: `backend/tests/test_applications.py`
- Test: `backend/tests/test_config.py` if health/discovery covered there

**Interfaces:**
- Consumes: `ActiveApp.NEWS`
- Produces: `resolve_application_paths()["chrome"]`; `detect_capabilities()["chrome_available"]`; `ApplicationManager.open(app)`; `ApplicationManager.open_news(url: str)`; `ApplicationManager.search_youtube(query: str)`; Chrome argv helper

- [ ] **Step 1: Rewrite YouTube launch tests to Chrome kiosk + AdBlock**

In `backend/tests/test_applications.py` change `make_manager` to take `chrome` and `adblock_dir: Path`. Create a temp dir with `manifest.json` in tests.

```python
def make_manager(*, chrome: Path | None = Path("C:/Apps/chrome.exe"), adblock_dir: Path | None = None):
    ...
    executable_paths={"chrome": chrome, "edge": Path("C:/Apps/msedge.exe"), "brave": None, "browser": None}

def test_youtube_uses_isolated_chrome_kiosk_and_adblock(tmp_path: Path) -> None:
    adblock = tmp_path / "adblock"
    adblock.mkdir()
    (adblock / "manifest.json").write_text("{}", encoding="utf-8")
    manager, launcher, windows, _ = make_manager(adblock_dir=adblock)
    asyncio.run(manager.open(ActiveApp.YOUTUBE))
    argv = launcher.calls[0]
    assert argv[0].endswith("chrome.exe")
    assert "--kiosk" in argv
    assert any(part.startswith("--user-data-dir=") and "chrome-tv-profile" in part for part in argv)
    assert any(part.startswith("--load-extension=") and str(adblock) in part.replace("\\", "/") for part in argv)
    assert "--start-maximized" not in argv
    assert argv[-1] == "https://www.youtube.com/"

def test_netflix_stays_on_edge_without_adblock() -> None:
    ...
    assert "--load-extension" not in " ".join(launcher.calls[0])
    assert "chrome-tv-profile" not in " ".join(launcher.calls[0])

def test_missing_chrome_returns_chrome_not_found(tmp_path: Path) -> None:
    with pytest.raises(CommandExecutionError) as error:
        asyncio.run(make_manager(chrome=None, adblock_dir=tmp_path)[0].open(ActiveApp.YOUTUBE))
    assert error.value.code == "chrome_not_found"

def test_missing_adblock_returns_adblock_not_installed() -> None:
    with pytest.raises(CommandExecutionError) as error:
        asyncio.run(make_manager(adblock_dir=Path("C:/missing-adblock"))[0].open(ActiveApp.YOUTUBE))
    assert error.value.code == "adblock_not_installed"

def test_search_youtube_opens_results_url(tmp_path: Path) -> None:
    ...
    asyncio.run(manager.search_youtube("cat videos"))
    assert launcher.calls[0][-1] == "https://www.youtube.com/results?search_query=cat+videos"
```

- [ ] **Step 2: Run focused tests; expect FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_applications.py`
Expected: FAIL on Brave argv / missing methods

- [ ] **Step 3: Implement Chrome path + manager**

`ApplicationSettings.chrome_path: str = ""`. In `resolve_application_paths` add chrome candidates:

- `Program Files/Google/Chrome/Application/chrome.exe`
- `Program Files (x86)/Google/Chrome/Application/chrome.exe`
- `LOCALAPPDATA/Google/Chrome/Application/chrome.exe`

Health: `chrome_available`.

`ApplicationManager.__init__` takes `adblock_dir: Path` default `project_root() / "vendor" / "adblock"` and profile `project_root() / "config" / "chrome-tv-profile"`.

```python
def _chrome_kiosk_args(self, url: str) -> list[str]:
    chrome = self._executables.get("chrome")
    if chrome is None:
        raise CommandExecutionError("chrome_not_found", "Chrome is not installed or configured. Install Chrome or set applications.chrome_path.")
    if not (self._adblock_dir / "manifest.json").is_file():
        raise CommandExecutionError("adblock_not_installed", "AdBlock is not installed. Re-run setup.ps1.")
    return [
        chrome.as_posix(),
        f"--user-data-dir={self._profile_dir}",
        f"--disable-extensions-except={self._adblock_dir}",
        f"--load-extension={self._adblock_dir}",
        "--kiosk",
        "--no-first-run",
        "--no-default-browser-check",
        "--autoplay-policy=no-user-gesture-required",
        url,
    ]
```

`open(YOUTUBE)` uses `settings.urls.youtube`. `open_news(url)` sets `ActiveApp.NEWS`. `search_youtube` uses `quote_plus` and `ActiveApp.YOUTUBE`. `open(NETFLIX)` stays Edge `--new-window --start-maximized`. `require_input_target` includes `NEWS`.

- [ ] **Step 4: Run tests; expect PASS**

Run: `.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_applications.py backend\tests\test_config.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/applications/manager.py backend/app/commands/ports.py backend/tests/test_applications.py config/settings.example.json
git commit -m "feat: launch YouTube and news in kiosk Chrome with AdBlock"
```

---

### Task 3: CommandBus news channels and search

**Files:**
- Modify: `backend/app/commands/bus.py`
- Modify: `backend/app/controller.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_command_bus.py`
- Modify: `backend/tests/test_websocket.py` fakes if they construct `CommandBus`

**Interfaces:**
- Consumes: `NewsChannelManager`, `ApplicationPort.open_news`, `ApplicationPort.search_youtube`
- Produces: `CommandBus(..., news: NewsChannelManager)`; `dispatch_search(message: SearchVideoMessage)`; `CHANNEL_*` on `NEWS`

- [ ] **Step 1: Write failing bus tests**

Extend `FakeApplications` with `opened_news: list[str]`, `searches: list[str]`, `async def open_news(self, url: str)`, `async def search_youtube(self, query: str)`.

```python
def test_open_news_sets_channel_and_active_app(tmp_path) -> None:
    news = NewsChannelManager(load_news_channels(example_or_tmp))
    bus = CommandBus(..., news=news)
    outcome = asyncio.run(bus.dispatch_command(Command.OPEN_NEWS))
    assert outcome.success
    assert outcome.state.active_app is ActiveApp.NEWS
    assert outcome.state.channel_name == "DW News"
    assert applications.opened_news[0].endswith("/@dwnews/live")

def test_channel_up_on_news_opens_next_official_url() -> None:
    asyncio.run(bus.dispatch_command(Command.OPEN_NEWS))
    outcome = asyncio.run(bus.dispatch_command(Command.CHANNEL_UP))
    assert outcome.state.channel_name == "Al Jazeera English"

def test_channel_up_on_youtube_is_rejected() -> None:
    asyncio.run(bus.dispatch_command(Command.OPEN_YOUTUBE))
    outcome = asyncio.run(bus.dispatch_command(Command.CHANNEL_UP))
    assert outcome.success is False
    assert outcome.error_code == "channel_source_not_active"

def test_search_video_opens_youtube_results() -> None:
    outcome = asyncio.run(bus.dispatch_search(SearchVideoMessage(version=1, type="search_video", request_id="s1", query="cat videos")))
    assert outcome.success
    assert outcome.state.active_app is ActiveApp.YOUTUBE
    assert applications.searches == ["cat videos"]
```

- [ ] **Step 2: Run; expect FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_command_bus.py`
Expected: FAIL on new methods / `channel_source_not_active`

- [ ] **Step 3: Implement bus + wiring**

`CommandBus.__init__(..., news: NewsChannelManager)`. `_LAUNCH_TARGETS[OPEN_NEWS]` is not enough because news needs URL + channel fields. Handle `OPEN_NEWS` like `OPEN_LIVE_TV`: close mpv if needed, `await self._applications.open_news(self._news.current.url)`, update state `active_app=NEWS`, channel number/name.

`CHANNEL_UP/DOWN`: if `NEWS`, `channel = self._news.move(direction)`, `open_news(channel.url)`, update channel fields; if `LIVE_TV`, existing player path; else `channel_source_not_active`.

`dispatch_search`: if active is LIVE_TV close player; `await self._applications.search_youtube(message.query)`; state `active_app=YOUTUBE`, clear channel fields.

`controller.build_runtime`: load `config/news.json` else example; on invalid news, construct a tiny `UnavailableNews` that raises `news_not_configured` from `OPEN_NEWS` (mirror `UnavailablePlayer`). Pass `adblock_dir` into `ApplicationManager`.

`main._dispatch_and_broadcast`: if `SearchVideoMessage`, `dispatch_search`. Health includes `chrome_available`.

Update every test fake `CommandBus` / `FakeApplications` to the new methods.

- [ ] **Step 4: Run backend suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/commands/bus.py backend/app/controller.py backend/app/main.py backend/tests
git commit -m "feat: dispatch news channels and YouTube search"
```

---

### Task 4: TV launcher News tile

**Files:**
- Modify: `frontend/src/types/protocol.ts`
- Modify: `frontend/src/tv/navigation.ts`
- Modify: `frontend/src/tv/navigation.test.ts`
- Modify: `frontend/src/tv/TVLauncher.tsx`
- Modify: `frontend/src/tv/TVLauncher.test.tsx` if tile labels asserted
- Modify: `mobile/src/types/protocol.ts` (`OPEN_NEWS`, `news` in unions only)

**Interfaces:**
- Consumes: `OPEN_NEWS`, tile `news`
- Produces: focus graph from spec; `tileCommand('news') === 'OPEN_NEWS'`

- [ ] **Step 1: Write failing navigation tests**

```ts
expect(moveFocus('youtube', 'NAV_DOWN')).toBe('news')
expect(tileCommand('news')).toBe('OPEN_NEWS')
```

- [ ] **Step 2: Run**

Run: `npm test -- src/tv/navigation.test.ts` in `frontend`
Expected: FAIL

- [ ] **Step 3: Update tiles and protocol unions**

`TileId` includes `'news'`. Transitions exactly as spec. TV tile label `新聞` / `News`. State unions add `'news'`.

- [ ] **Step 4: Run frontend tests**

Run: `npm test` in `frontend`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src mobile/src/types/protocol.ts
git commit -m "feat: add News tile to TV launcher"
```

---

### Task 5: Phone handset remote (QR)

**Files:**
- Modify: `frontend/src/types/protocol.ts` (`SearchVideoMessage`, `ClientMessage`)
- Modify: `frontend/src/api/controllerSocket.ts` (`sendSearch(query: string)`)
- Modify: `frontend/src/api/useControllerSocket.ts`
- Modify: `frontend/src/remote/RemotePage.tsx`
- Modify: `frontend/src/remote/RemotePage.test.tsx`
- Modify: `frontend/src/styles.css` as needed for app-row / voice

**Interfaces:**
- Consumes: `OPEN_NEWS`, `sendSearch`
- Produces: handset layout; voice fills search via `webkitSpeechRecognition`

- [ ] **Step 1: Write failing remote tests**

```ts
it('is a handset with YouTube, Netflix, news, voice, and search', () => {
  render(<RemotePage token="paired-token-value-that-is-long-enough" ... />)
  expect(screen.getByRole('button', { name: 'YouTube' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Netflix' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '新聞' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '語音' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '搜片' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Live TV' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Browser' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Sleep PC' })).toBeNull()
  expect(screen.queryByLabelText(/Touchpad/i)).toBeNull()
})

it('sends search_video for 搜片', () => {
  fireEvent.change(screen.getByLabelText('搜片'), { target: { value: 'cat videos' } })
  fireEvent.click(screen.getByRole('button', { name: '搜片' }))
  expect(socketMock.sendSearch).toHaveBeenCalledWith('cat videos')
})
```

Remove or rewrite the Previous/Next visibility test if those buttons leave the handset. Keep QR prefill test.

- [ ] **Step 2: Run**

Run: `npm test -- src/remote/RemotePage.test.tsx` in `frontend`
Expected: FAIL

- [ ] **Step 3: Implement handset**

Order: app row (YouTube / Netflix / 新聞) → D-pad → Back Home Ch+ Ch− Volume+/− → voice button → search form.

`sendSearch` sends `{ version: 1, type: 'search_video', request_id, query }`.

Voice: `window.SpeechRecognition || window.webkitSpeechRecognition`, `lang = 'zh-TW'`, onresult set query and call `sendSearch`. If API missing, disable 語音 and leave search usable.

Delete touchpad handlers and free-text `sendText` UI from `RemoteControl`. Keep pairing/Forget.

- [ ] **Step 4: Run frontend lint/tests**

Run: `npm run lint && npm test` in `frontend`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: make phone remote a YouTube Netflix news handset"
```

---

### Task 6: Setup AdBlock install, ignore rules, docs

**Files:**
- Create: `backend/app/applications/adblock.py`
- Test: `backend/tests/test_adblock.py`
- Modify: `scripts/setup.ps1`
- Modify: `.gitignore`
- Modify: `AGENTS.md`, `docs/PROTOCOL.md`, `README.md`, `scripts/package.ps1` if it copies `config/*.example.json`

**Interfaces:**
- Consumes: Chrome update URL from spec
- Produces: `ensure_adblock(directory: Path) -> Path` writing `vendor/adblock/manifest.json`

- [ ] **Step 1: Write failing unpack/id tests**

Use a tiny zip-as-CRX fixture: CRX3 magic `Cr24` + version/header lengths + zip payload containing `manifest.json` with a known key, **or** unit-test header strip + zip extract separately and stub ID check.

```python
def test_ensure_adblock_rejects_wrong_extension_id(tmp_path: Path) -> None:
    ...
    with pytest.raises(ValueError, match="gighmmpiobklfepjocnamgkkbiglidom"):
        ensure_adblock(tmp_path / "adblock", crx_bytes=wrong_id_crx)
```

Also test missing `manifest.json` after unpack raises.

- [ ] **Step 2: Run; expect FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_adblock.py`

- [ ] **Step 3: Implement downloader and setup hook**

`ensure_adblock(directory: Path) -> Path`: if `directory/manifest.json` exists and computed ID matches, return. Else download spec URL with `httpx`, strip CRX3 header (`Cr24`, little-endian version + header size), unzip, compute Chrome ID from manifest `key` (SHA-256 of DER, first 16 bytes mapped to `a-p`). Mismatch → delete directory, raise. CLI: `python -m app.applications.adblock --directory ..\vendor\adblock` from `backend/`.

`setup.ps1`: after Python deps, run that module; copy `news.example.json` like channels; report Chrome path. `.gitignore` add `config/chrome-tv-profile/` and `vendor/adblock/`.

Docs: HDMI kiosk + scan QR handset; YouTube ads via store AdBlock in TV profile; news list; product boundary no IPTV scrape.

- [ ] **Step 4: Verify**

Run: backend `test_adblock.py` + `scripts/setup.ps1` AdBlock step only if network allowed. Frontend already green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/applications/adblock.py backend/tests/test_adblock.py scripts/setup.ps1 .gitignore AGENTS.md docs/PROTOCOL.md README.md
git commit -m "feat: install store AdBlock into the TV Chrome profile"
```

---

## Spec coverage

| Spec item | Task |
|---|---|
| Chrome + isolated profile + store AdBlock ID | 2, 6 |
| `--kiosk` HDMI fullscreen YouTube/News | 2 |
| Official YouTube `/live` list + CHANNEL_* | 1, 3 |
| Netflix Edge, no extension | 2 |
| `search_video` + 搜片 | 1, 3, 5 |
| Phone Web Speech | 5 |
| QR `remote_url?code=` unchanged | 5 (keep existing test) |
| Edge `/tv` kiosk already in `start.ps1` | no change |
| Ignore vendor/profile/news.json | 6 |
| No IPTV scrape / no daily Chrome | 6 docs |
| Native types only | 4 |

## Placeholder scan

No TBD/later steps. Command names, paths, argv, error codes, and test bodies are explicit.
