from app.applications.chrome_page import select_debugger_url


def test_select_debugger_url_prefers_netflix_page() -> None:
    chosen = select_debugger_url(
        [
            {"type": "page", "url": "chrome://newtab", "webSocketDebuggerUrl": "ws://127.0.0.1/newtab"},
            {"type": "page", "url": "https://www.netflix.com/login", "webSocketDebuggerUrl": "ws://127.0.0.1/netflix"},
        ]
    )
    assert chosen == "ws://127.0.0.1/netflix"


def test_select_debugger_url_falls_back_to_first_page() -> None:
    chosen = select_debugger_url(
        [{"type": "page", "url": "https://example.test/", "webSocketDebuggerUrl": "ws://127.0.0.1/example"}]
    )
    assert chosen == "ws://127.0.0.1/example"
