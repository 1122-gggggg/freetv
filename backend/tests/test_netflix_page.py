from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

import app.applications.netflix_page as netflix_page_module
from app.applications.netflix_page import (
    RUNTIME_VERSION,
    NetflixAction,
    NetflixPageController,
    select_netflix_target,
)
from app.commands.ports import CommandExecutionError
from app.protocol import Command, NetflixContext, NetflixInputKind, NetflixStage

RUNTIME_SOURCE = "globalThis.__fixtureNetflixRuntime = true"

VALID_FOCUS = {
    "role": "button",
    "label": "Play Alpha",
    "uia": "title-card",
    "text": "Alpha",
    "pathKind": "title",
    "rail": "Trending",
    "index": 0,
}
LOGIN_PASSWORD_CONTEXT = {
    "stage": "login",
    "input_kind": "password",
    "has_error": False,
    "can_submit": True,
    "focused_title": None,
}
BROWSE_CONTEXT = {
    "stage": "browse",
    "input_kind": "none",
    "has_error": False,
    "can_submit": False,
    "focused_title": "Alpha",
}
WATCH_CONTEXT = {
    "stage": "watch",
    "input_kind": "none",
    "has_error": False,
    "can_submit": False,
    "focused_title": None,
}
VALID_RESULT = {
    "ok": True,
    "status": "focused",
    "focus": VALID_FOCUS,
    "context": BROWSE_CONTEXT,
}
PLAYING_WATCH_RESULT = {
    "ok": True,
    "status": "playing",
    "context": WATCH_CONTEXT,
}
FULLSCREEN_WATCH_RESULT = {
    "ok": True,
    "status": "fullscreen",
    "context": WATCH_CONTEXT,
}
SPEED_WATCH_RESULT = {
    "ok": True,
    "status": "speed",
    "rate": 1.25,
    "context": WATCH_CONTEXT,
}
NETFLIX_PAGE = {
    "type": "page",
    "url": "https://www.netflix.com/browse",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/netflix",
}


class FakeSocket:
    def __init__(
        self,
        *,
        runtime_present: bool = True,
        runtime_version: str | None = None,
        runtime_result: Any = None,
        runtime_results: list[Any] | None = None,
        fail_injection: bool = False,
        fail_run: bool = False,
        fail_insert: bool = False,
        drop_version_ack: bool = False,
        drop_version_ack_at: int | None = None,
        drop_run_ack: bool = False,
        drop_run_ack_at: int | None = None,
        drop_insert_ack: bool = False,
        secret_in_error: str = "",
    ) -> None:
        self.runtime_present = runtime_present
        self.reported_version = runtime_version
        self.runtime_results = runtime_results
        self.runtime_result = VALID_RESULT if runtime_result is None else runtime_result
        self.fail_injection = fail_injection
        self.fail_run = fail_run
        self.fail_insert = fail_insert
        self.drop_version_ack = drop_version_ack
        self.drop_version_ack_at = drop_version_ack_at
        self.version_calls = 0
        self.drop_run_ack = drop_run_ack
        self.drop_run_ack_at = drop_run_ack_at
        self.run_calls = 0
        self.drop_insert_ack = drop_insert_ack
        self.secret_in_error = secret_in_error
        self.sent: list[dict[str, Any]] = []
        self._replies: list[str] = []
        self.entered = 0
        self.closed = False

    async def send(self, raw: str) -> None:
        payload = json.loads(raw)
        self.sent.append(payload)
        command_id = payload["id"]
        method = payload["method"]
        params = payload.get("params", {})

        if method == "Input.insertText":
            if self.drop_insert_ack:
                return
            if self.fail_insert:
                self._error(command_id)
            else:
                self._result(command_id, {})
            return

        assert method == "Runtime.evaluate"
        expression = params["expression"]
        if expression == RUNTIME_SOURCE:
            if self.fail_injection:
                self._error(command_id)
            else:
                self.runtime_present = True
                self.reported_version = RUNTIME_VERSION
                self._remote_value(command_id, None)
        elif ".run(" in expression:
            self.run_calls += 1
            if self.drop_run_ack or self.drop_run_ack_at == self.run_calls:
                return
            if self.fail_run:
                self._error(command_id)
            else:
                runtime_result = (
                    self.runtime_results.pop(0) if self.runtime_results else self.runtime_result
                )
                self._remote_value(command_id, runtime_result)
        else:
            self.version_calls += 1
            if self.drop_version_ack or self.drop_version_ack_at == self.version_calls:
                return
            if not self.runtime_present:
                self._remote_value(command_id, None)
            else:
                self._remote_value(
                    command_id,
                    self.reported_version if self.reported_version is not None else RUNTIME_VERSION,
                )

    async def recv(self) -> str:
        return self._replies.pop(0)

    def _result(self, command_id: int, result: dict[str, Any]) -> None:
        self._replies.append(json.dumps({"id": command_id, "result": result}))

    def _remote_value(self, command_id: int, value: Any) -> None:
        self._result(command_id, {"result": {"value": value}})

    def _error(self, command_id: int) -> None:
        self._replies.append(
            json.dumps(
                {
                    "id": command_id,
                    "error": {
                        "message": "fixture CDP failure",
                        "data": self.secret_in_error,
                    },
                }
            )
        )


class FakeConnection:
    def __init__(self, outcome: FakeSocket | BaseException) -> None:
        self._outcome = outcome

    async def __aenter__(self) -> FakeSocket:
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        self._outcome.entered += 1
        return self._outcome

    async def __aexit__(self, *_args: object) -> None:
        if isinstance(self._outcome, FakeSocket):
            self._outcome.closed = True


class FakeConnect:
    def __init__(self, outcomes: list[FakeSocket | BaseException]) -> None:
        self._outcomes = outcomes
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, **kwargs: Any) -> FakeConnection:
        self.calls.append((url, kwargs))
        return FakeConnection(self._outcomes[len(self.calls) - 1])


def make_controller(tmp_path: Path, port: int = 9222) -> NetflixPageController:
    runtime_path = tmp_path / "netflix_control.js"
    runtime_path.write_text(RUNTIME_SOURCE, encoding="utf-8")
    return NetflixPageController(port, timeout=0.2, runtime_path=runtime_path)


def install_transport(
    monkeypatch: pytest.MonkeyPatch,
    controller: NetflixPageController,
    outcomes: list[FakeSocket | BaseException],
    pages: list[dict[str, Any]] | Callable[[int, int], list[dict[str, Any]]] | None = None,
) -> tuple[FakeConnect, list[int]]:
    page_calls: list[int] = []

    async def fake_list_pages(port: int) -> list[dict[str, Any]]:
        page_calls.append(port)
        if callable(pages):
            return pages(port, len(page_calls))
        return list(pages if pages is not None else [NETFLIX_PAGE])

    monkeypatch.setattr(controller, "_list_pages", fake_list_pages)
    connect = FakeConnect(outcomes)
    monkeypatch.setattr(netflix_page_module.websockets, "connect", connect)
    return connect, page_calls


def runtime_expressions(socket: FakeSocket) -> list[str]:
    return [
        payload["params"]["expression"]
        for payload in socket.sent
        if payload["method"] == "Runtime.evaluate" and ".run(" in payload["params"]["expression"]
    ]


def test_netflix_actions_exactly_match_runtime_actions() -> None:
    assert [action.value for action in NetflixAction] == [
        "FOCUS_PRIMARY",
        "FOCUS_EDITABLE",
        "FOCUS_NEXT",
        "NAV_UP",
        "NAV_DOWN",
        "NAV_LEFT",
        "NAV_RIGHT",
        "OK",
        "BACK",
        "PLAY_PAUSE",
        "FULLSCREEN",
        "SPEED_UP",
        "SPEED_DOWN",
        "SEEK_FORWARD_5",
        "SEEK_BACKWARD_5",
        "SET_TEXT",
        "SHOW_OSD",
        "READ_CONTEXT",
        "SUBMIT_PRIMARY",
        "QUALITY",
        "SUBTITLES",
    ]

def test_select_netflix_target_requires_one_top_level_netflix_page() -> None:
    assert (
        select_netflix_target(
            [
                {
                    "type": "page",
                    "url": "chrome://newtab",
                    "webSocketDebuggerUrl": "ws://127.0.0.1/new",
                },
                NETFLIX_PAGE,
            ]
        )
        == NETFLIX_PAGE["webSocketDebuggerUrl"]
    )


@pytest.mark.parametrize(
    "pages",
    [
        [
            {
                "type": "iframe",
                "url": "https://www.netflix.com/login",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/frame",
            }
        ],
        [
            {
                "type": "page",
                "openerId": "main",
                "url": "https://www.netflix.com/verify",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/popup",
            }
        ],
        [
            NETFLIX_PAGE,
            {
                **NETFLIX_PAGE,
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/second",
            },
        ],
        [
            NETFLIX_PAGE,
            {
                "type": "iframe",
                "url": "https://assets.netflix.com/frame",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/frame",
            },
        ],
    ],
)
def test_select_netflix_target_rejects_unsupported_or_ambiguous_targets(
    pages: list[dict[str, Any]],
) -> None:
    with pytest.raises(CommandExecutionError) as caught:
        select_netflix_target(pages)
    assert caught.value.code == "netflix_target_unsupported"
    assert caught.value.message == "Netflix 目前畫面不是可控制的主要頁面。"


@pytest.mark.parametrize(
    "pages",
    [
        [],
        [
            {
                "type": "page",
                "url": "https://netflix.com.evil.test/",
                "webSocketDebuggerUrl": "ws://127.0.0.1/evil",
            }
        ],
        [{"type": "page", "url": "https://www.netflix.com/browse"}],
    ],
)
def test_select_netflix_target_reports_missing_page_separately(
    pages: list[dict[str, Any]],
) -> None:
    with pytest.raises(CommandExecutionError) as caught:
        select_netflix_target(pages)
    assert caught.value.code == "netflix_page_unavailable"
    assert caught.value.message == "無法連到 Netflix 控制頁面，請稍後再試。"


@pytest.mark.parametrize(
    "debugger_url",
    [
        "wss://127.0.0.1:9222/devtools/page/netflix",
        "ws://localhost:9222/devtools/page/netflix",
        "ws://192.168.1.44:9222/devtools/page/netflix",
        "ws://0.0.0.0:9222/devtools/page/netflix",
        "ws://203.0.113.10:9222/devtools/page/netflix",
        "ws://127.0.0.1/devtools/page/netflix",
        "ws://127.0.0.1:0/devtools/page/netflix",
        "ws://127.0.0.1:65536/devtools/page/netflix",
    ],
)
def test_select_netflix_target_rejects_non_loopback_debugger_urls(
    debugger_url: str,
) -> None:
    with pytest.raises(CommandExecutionError) as caught:
        select_netflix_target([{**NETFLIX_PAGE, "webSocketDebuggerUrl": debugger_url}])
    assert caught.value.code == "netflix_target_unsupported"


def test_invalid_debugger_url_is_deterministic_and_does_not_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    pages = [
        {
            **NETFLIX_PAGE,
            "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/netflix",
        }
    ]
    connect, page_calls = install_transport(monkeypatch, controller, [], pages)

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.execute(Command.OK))

    assert caught.value.code == "netflix_target_unsupported"
    assert page_calls == [9222]
    assert connect.calls == []


def test_list_pages_uses_fresh_local_http_client_and_preserves_target_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clients: list[FakeHttpClient] = []
    payload = [NETFLIX_PAGE, {"type": "iframe", "url": "https://www.netflix.com/frame"}, "bad"]

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[Any]:
            return payload

    class FakeHttpClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout
            self.urls: list[str] = []
            self.closed = False
            clients.append(self)

        async def __aenter__(self) -> FakeHttpClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            self.closed = True

        async def get(self, url: str) -> FakeResponse:
            self.urls.append(url)
            return FakeResponse()

    monkeypatch.setattr(netflix_page_module.httpx, "AsyncClient", FakeHttpClient)
    controller = make_controller(tmp_path)

    first = asyncio.run(controller._list_pages(9222))
    second = asyncio.run(controller._list_pages(9222))

    assert first == [NETFLIX_PAGE, payload[1]]
    assert second == first
    assert len(clients) == 2
    assert all(client.urls == ["http://127.0.0.1:9222/json/list"] for client in clients)
    assert all(client.closed for client in clients)


def test_execute_opens_one_socket_checks_version_runs_action_and_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket()
    connect, page_calls = install_transport(monkeypatch, controller, [socket])

    assert asyncio.run(controller.execute(Command.NAV_RIGHT)) == NetflixContext(
        stage=NetflixStage.BROWSE,
        input_kind=NetflixInputKind.NONE,
        focused_title="Alpha",
    )

    assert page_calls == [9222]
    assert len(connect.calls) == 1
    assert connect.calls[0][0] == NETFLIX_PAGE["webSocketDebuggerUrl"]
    assert connect.calls[0][1] == {"open_timeout": 0.2, "max_size": 2**22}
    assert socket.entered == 1
    assert socket.closed
    expressions = [payload["params"]["expression"] for payload in socket.sent]
    assert len(expressions) == 2
    assert ".version" in expressions[0]
    assert '"NAV_RIGHT"' in expressions[1]
    assert expressions[1].endswith(", null)")
    assert not any(isinstance(value, FakeSocket) for value in controller.__dict__.values())


def test_execute_injects_runtime_only_when_version_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket(runtime_present=False)
    install_transport(monkeypatch, controller, [socket])

    asyncio.run(controller.initialize())

    expressions = [payload["params"]["expression"] for payload in socket.sent]
    assert expressions == [
        NetflixPageController.VERSION_EXPRESSION,
        RUNTIME_SOURCE,
        NetflixPageController.VERSION_EXPRESSION,
        runtime_expressions(socket)[0],
    ]
    assert socket.closed


def test_stale_v1_runtime_is_replaced_with_current_source_before_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket(runtime_version="1")
    install_transport(monkeypatch, controller, [socket])

    asyncio.run(controller.initialize())

    expressions = [payload["params"]["expression"] for payload in socket.sent]
    assert RUNTIME_VERSION != "1"
    assert expressions == [
        NetflixPageController.VERSION_EXPRESSION,
        RUNTIME_SOURCE,
        NetflixPageController.VERSION_EXPRESSION,
        runtime_expressions(socket)[0],
    ]
    assert socket.closed


def test_current_runtime_version_is_not_reinjected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket(runtime_version=RUNTIME_VERSION)
    install_transport(monkeypatch, controller, [socket])

    asyncio.run(controller.initialize())

    expressions = [payload["params"]["expression"] for payload in socket.sent]
    assert expressions == [
        NetflixPageController.VERSION_EXPRESSION,
        runtime_expressions(socket)[0],
    ]
    assert RUNTIME_SOURCE not in expressions
    assert socket.closed


def test_http_failure_retries_with_fresh_page_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket()
    calls = 0

    async def fake_list_pages(port: int) -> list[dict[str, Any]]:
        nonlocal calls
        assert port == 9222
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("fixture")
        return [NETFLIX_PAGE]

    monkeypatch.setattr(controller, "_list_pages", fake_list_pages)
    connect = FakeConnect([socket])
    monkeypatch.setattr(netflix_page_module.websockets, "connect", connect)

    asyncio.run(controller.execute(Command.OK))

    assert calls == 2
    assert len(connect.calls) == 1
    assert socket.closed


def test_socket_connection_failure_retries_once_then_returns_page_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    connect, page_calls = install_transport(
        monkeypatch,
        controller,
        [OSError("first"), OSError("second")],
    )

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.execute(Command.OK))

    assert caught.value.code == "netflix_page_unavailable"
    assert caught.value.message == "無法連到 Netflix 控制頁面，請稍後再試。"
    assert page_calls == [9222, 9222]
    assert len(connect.calls) == 2


def test_version_ack_loss_retries_before_any_action_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    first = FakeSocket(drop_version_ack=True)
    second = FakeSocket()
    connect, page_calls = install_transport(monkeypatch, controller, [first, second])

    asyncio.run(controller.execute(Command.OK))

    assert page_calls == [9222, 9222]
    assert len(connect.calls) == 2
    assert runtime_expressions(first) == []
    assert len(runtime_expressions(second)) == 1
    assert first.closed and second.closed


def test_idempotent_action_cdp_failure_retries_with_a_new_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    first = FakeSocket(fail_run=True)
    second = FakeSocket()
    connect, page_calls = install_transport(monkeypatch, controller, [first, second])

    asyncio.run(controller.initialize())

    assert page_calls == [9222, 9222]
    assert len(connect.calls) == 2
    assert first.closed and second.closed


@pytest.mark.parametrize(
    "command",
    [
        Command.TAB,
        Command.NAV_UP,
        Command.NAV_DOWN,
        Command.NAV_LEFT,
        Command.NAV_RIGHT,
        Command.OK,
        Command.BACK,
        Command.PLAY_PAUSE,
        Command.FULLSCREEN,
        Command.SPEED_UP,
        Command.SPEED_DOWN,
    ],
)
def test_non_idempotent_action_ack_loss_is_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: Command,
) -> None:
    controller = make_controller(tmp_path)
    first = FakeSocket(drop_run_ack=True)
    second = FakeSocket()
    connect, page_calls = install_transport(monkeypatch, controller, [first, second])

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.execute(command))

    assert caught.value.code == "netflix_controller_unavailable"
    assert page_calls == [9222]
    assert len(connect.calls) == 1
    assert len(runtime_expressions(first)) == 1
    assert runtime_expressions(second) == []
    assert first.closed
    assert not second.closed


def test_injection_failure_retries_once_then_returns_controller_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    first = FakeSocket(runtime_present=False, fail_injection=True)
    second = FakeSocket(runtime_present=False, fail_injection=True)
    _, page_calls = install_transport(monkeypatch, controller, [first, second])

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.initialize())

    assert caught.value.code == "netflix_controller_unavailable"
    assert caught.value.message == "無法載入 Netflix 遙控控制，請稍後再試。"
    assert page_calls == [9222, 9222]
    assert first.closed and second.closed


def test_deterministic_target_errors_do_not_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    pages = [
        NETFLIX_PAGE,
        {
            **NETFLIX_PAGE,
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/other",
        },
    ]
    connect, page_calls = install_transport(monkeypatch, controller, [], pages)

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.execute(Command.OK))

    assert caught.value.code == "netflix_target_unsupported"
    assert page_calls == [9222]
    assert connect.calls == []


def test_missing_target_does_not_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller = make_controller(tmp_path)
    connect, page_calls = install_transport(monkeypatch, controller, [], [])

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.execute(Command.OK))

    assert caught.value.code == "netflix_page_unavailable"
    assert page_calls == [9222]
    assert connect.calls == []


def test_next_command_reinjects_after_execution_context_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    first = FakeSocket()
    replacement = FakeSocket(runtime_present=False)
    _, page_calls = install_transport(monkeypatch, controller, [first, replacement])

    asyncio.run(controller.execute(Command.NAV_LEFT))
    asyncio.run(controller.execute(Command.NAV_RIGHT))

    assert page_calls == [9222, 9222]
    assert RUNTIME_SOURCE not in [payload["params"]["expression"] for payload in first.sent]
    assert RUNTIME_SOURCE in [payload["params"]["expression"] for payload in replacement.sent]
    assert first.closed and replacement.closed


def test_each_action_uses_enum_and_sends_only_whitelisted_previous_focus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    first = FakeSocket(runtime_result=VALID_RESULT)
    commands = [
        (Command.NAV_UP, "NAV_UP"),
        (Command.NAV_DOWN, "NAV_DOWN"),
        (Command.NAV_LEFT, "NAV_LEFT"),
        (Command.NAV_RIGHT, "NAV_RIGHT"),
        (Command.OK, "OK"),
        (Command.BACK, "BACK"),
        (Command.PLAY_PAUSE, "PLAY_PAUSE"),
        (Command.FULLSCREEN, "FULLSCREEN"),
        (Command.SPEED_UP, "SPEED_UP"),
        (Command.SPEED_DOWN, "SPEED_DOWN"),
        (Command.SEEK_FORWARD_5, "SEEK_FORWARD_5"),
        (Command.SEEK_BACKWARD_5, "SEEK_BACKWARD_5"),
        (Command.TAB, "FOCUS_NEXT"),
    ]
    remaining = [
        FakeSocket(
            runtime_result={
                "ok": True,
                "status": "boundary",
                "focus": VALID_FOCUS,
                "context": BROWSE_CONTEXT,
            }
        )
        for _ in commands
    ]
    install_transport(monkeypatch, controller, [first, *remaining])

    asyncio.run(controller.initialize())
    for (command, action), socket in zip(commands, remaining, strict=True):
        asyncio.run(controller.execute(command))
        expression = runtime_expressions(socket)[0]
        prefix = "globalThis.__freeTvNetflixControl.run("
        assert expression.startswith(prefix)
        action_json, focus_json = expression[len(prefix) : -1].split(", ", 1)
        assert json.loads(action_json) == action
        focus = json.loads(focus_json)
        assert focus == VALID_FOCUS
        assert set(focus) == {"role", "label", "uia", "text", "pathKind", "rail", "index"}
        assert "value" not in expression
        assert "innerHTML" not in expression
        assert "getBoundingClientRect" not in expression


def test_back_preserves_previous_focus_for_browse_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    focused = FakeSocket(runtime_result=VALID_RESULT)
    closed = FakeSocket(runtime_result={"ok": True, "status": "closed", "context": BROWSE_CONTEXT})
    next_command = FakeSocket(runtime_result=VALID_RESULT)
    install_transport(monkeypatch, controller, [focused, closed, next_command])

    asyncio.run(controller.initialize())
    asyncio.run(controller.execute(Command.BACK))
    asyncio.run(controller.initialize())

    assert runtime_expressions(closed)[0].endswith(
        f", {json.dumps(VALID_FOCUS, ensure_ascii=True)})"
    )
    assert runtime_expressions(next_command)[0].endswith(
        f", {json.dumps(VALID_FOCUS, ensure_ascii=True)})"
    )


def test_execute_rejects_non_enum_action_before_page_discovery(tmp_path: Path) -> None:
    controller = make_controller(tmp_path)
    with pytest.raises(TypeError, match="Command"):
        asyncio.run(controller.execute("OK"))  # type: ignore[arg-type]


def test_type_text_focuses_editable_then_uses_input_insert_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket(
        runtime_result={
            "ok": True,
            "status": "focused",
            "focus": VALID_FOCUS,
            "context": LOGIN_PASSWORD_CONTEXT,
        }
    )
    install_transport(monkeypatch, controller, [socket])
    secret = "account-password-驗證碼"

    assert asyncio.run(controller.type_text(secret)) == NetflixContext(
        stage=NetflixStage.LOGIN,
        input_kind=NetflixInputKind.PASSWORD,
        can_submit=True,
    )

    methods = [payload["method"] for payload in socket.sent]
    assert methods == ["Runtime.evaluate", "Runtime.evaluate", "Input.insertText"]
    expression = runtime_expressions(socket)[0]
    assert '"FOCUS_EDITABLE"' in expression
    assert secret not in expression
    assert socket.sent[-1]["params"] == {"text": secret}
    assert socket.closed


def test_input_insert_text_ack_loss_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    first = FakeSocket(drop_insert_ack=True)
    second = FakeSocket()
    connect, page_calls = install_transport(monkeypatch, controller, [first, second])
    secret = "send-once-secret"

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.type_text(secret))

    insert_calls = [
        payload
        for socket in (first, second)
        for payload in socket.sent
        if payload["method"] == "Input.insertText"
    ]
    assert caught.value.code == "netflix_controller_unavailable"
    assert page_calls == [9222]
    assert len(connect.calls) == 1
    assert len(insert_calls) == 1
    assert insert_calls[0]["params"] == {"text": secret}
    assert first.closed
    assert not second.closed


def test_type_text_does_not_expose_secret_in_error_log_or_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    controller = make_controller(tmp_path)
    secret = "secret-password-驗證碼"
    first = FakeSocket(fail_insert=True, secret_in_error=secret)
    second = FakeSocket(fail_insert=True, secret_in_error=secret)
    connect, page_calls = install_transport(monkeypatch, controller, [first, second])

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.type_text(secret))

    assert caught.value.code == "netflix_controller_unavailable"
    assert secret not in str(caught.value)
    assert secret not in caught.value.message
    assert secret not in caplog.text
    assert secret not in repr(controller.__dict__)
    assert page_calls == [9222]
    assert len(connect.calls) == 1
    assert first.closed
    assert not second.closed


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("netflix_focus_unavailable", "找不到可操作的 Netflix 項目，請稍後再試。"),
        ("netflix_input_unavailable", "找不到可輸入的 Netflix 欄位，請先選取輸入欄。"),
        ("netflix_video_unavailable", "目前沒有可播放或暫停的 Netflix 影片。"),
        ("netflix_direct_play_unavailable", "找不到可播放的 Netflix 項目，請稍後再試。"),
        ("netflix_submit_unavailable", "Netflix 目前無法送出，請確認電視畫面後再試。"),
        ("netflix_back_unavailable", "Netflix 目前無法返回，請確認電視畫面後再試。"),
        ("netflix_fullscreen_unavailable", "Netflix 目前沒有可切換為全螢幕的影片。"),
    ],
)
def test_runtime_codes_map_to_fixed_local_chinese_messages_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    message: str,
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket(runtime_result={"ok": False, "status": "error", "code": code})
    connect, page_calls = install_transport(monkeypatch, controller, [socket])

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.execute(Command.PLAY_PAUSE))

    assert caught.value.code == code
    assert caught.value.message == message
    assert page_calls == [9222]
    assert len(connect.calls) == 1
    assert socket.closed


@pytest.mark.parametrize(
    "runtime_result",
    [
        {"ok": True, "status": "focused", "unexpected": True},
        {"ok": True, "status": "focused", "code": None},
        {"ok": True, "status": "focused", "focus": {**VALID_FOCUS, "value": "secret"}},
        {
            "ok": True,
            "status": "focused",
            "focus": {key: value for key, value in VALID_FOCUS.items() if key != "rail"},
        },
        {"ok": True, "status": "focused", "focus": {**VALID_FOCUS, "label": "x" * 257}},
        {"ok": True, "status": "focused", "focus": {**VALID_FOCUS, "index": True}},
        *[
            {"ok": True, "status": status}
            for status in (
                "focused",
                "restored",
                "error_refocused",
                "moved",
                "boundary",
                "clicked",
            )
        ],
        *[
            {"ok": True, "status": status, "focus": VALID_FOCUS}
            for status in ("closed", "history", "playing", "paused")
        ],
        {"ok": False, "status": "error", "code": "netflix_page_unavailable"},
        {"ok": False, "status": "error"},
        {"ok": True, "status": "not-a-runtime-status"},
        {"ok": True, "status": "x" * 65},
        "not-an-object",
    ],
)
def test_malformed_runtime_results_are_rejected_and_retried_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime_result: Any,
) -> None:
    controller = make_controller(tmp_path)
    first = FakeSocket(runtime_result=runtime_result)
    second = FakeSocket(runtime_result=runtime_result)
    connect, page_calls = install_transport(monkeypatch, controller, [first, second])

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.initialize())

    assert caught.value.code == "netflix_controller_unavailable"
    assert caught.value.message == "無法載入 Netflix 遙控控制，請稍後再試。"
    assert page_calls == [9222, 9222]
    assert len(connect.calls) == 2
    assert first.closed and second.closed


@pytest.mark.parametrize(
    ("command", "runtime_result"),
    [
        (Command.OK, {"ok": True, "status": "clicked"}),
        (
            Command.BACK,
            {
                "ok": True,
                "status": "closed",
                "focus": VALID_FOCUS,
                "context": BROWSE_CONTEXT,
            },
        ),
    ],
)
def test_non_idempotent_action_schema_failure_is_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: Command,
    runtime_result: dict[str, Any],
) -> None:
    controller = make_controller(tmp_path)
    first = FakeSocket(runtime_result=runtime_result)
    second = FakeSocket()
    connect, page_calls = install_transport(monkeypatch, controller, [first, second])

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.execute(command))

    assert caught.value.code == "netflix_controller_unavailable"
    assert page_calls == [9222]
    assert len(connect.calls) == 1
    assert len(runtime_expressions(first)) == 1
    assert runtime_expressions(second) == []
    assert first.closed
    assert not second.closed


def test_execute_returns_a_strict_safe_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket()
    connect, page_calls = install_transport(monkeypatch, controller, [socket])

    context = asyncio.run(controller.execute(Command.NAV_RIGHT))

    assert context == NetflixContext(
        stage=NetflixStage.BROWSE,
        input_kind=NetflixInputKind.NONE,
        focused_title="Alpha",
    )
    assert page_calls == [9222]
    assert len(connect.calls) == 1
    assert socket.closed


def test_non_browse_runtime_title_and_extra_fields_are_rejected_safely(
    tmp_path: Path,
) -> None:
    controller = make_controller(tmp_path)
    invalid_context = {
        **LOGIN_PASSWORD_CONTEXT,
        "focused_title": "must-not-pass",
        "value": "secret",
    }
    with pytest.raises(CommandExecutionError) as caught:
        controller._accept_runtime_result(
            {
                "ok": True,
                "status": "focused",
                "focus": VALID_FOCUS,
                "context": invalid_context,
            }
        )
    assert caught.value.code == "netflix_controller_unavailable"
    assert "secret" not in str(caught.value)


def test_live_profile_gate_unknown_title_is_controller_unavailable(
    tmp_path: Path,
) -> None:
    controller = make_controller(tmp_path)
    with pytest.raises(CommandExecutionError) as caught:
        controller._accept_runtime_result(
            {
                "ok": True,
                "status": "focused",
                "focus": {
                    "role": "link",
                    "label": "Profile",
                    "uia": "action-select-profile+primary",
                    "text": "Profile",
                    "pathKind": "switchprofile",
                    "rail": "",
                    "index": 3,
                },
                "context": {
                    "stage": "unknown",
                    "input_kind": "none",
                    "has_error": False,
                    "can_submit": False,
                    "focused_title": "Profile",
                },
            }
        )
    assert caught.value.code == "netflix_controller_unavailable"
    assert caught.value.message == "無法載入 Netflix 遙控控制，請稍後再試。"


def test_initialize_accepts_profile_gate_browse_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket(
        runtime_result={
            "ok": True,
            "status": "focused",
            "focus": {
                "role": "link",
                "label": "Profile",
                "uia": "action-select-profile+primary",
                "text": "Profile",
                "pathKind": "switchprofile",
                "rail": "",
                "index": 0,
            },
            "context": {
                "stage": "browse",
                "input_kind": "none",
                "has_error": False,
                "can_submit": False,
                "focused_title": "Profile",
            },
        }
    )
    install_transport(monkeypatch, controller, [socket])

    context = asyncio.run(controller.initialize())

    assert context == NetflixContext(
        stage=NetflixStage.BROWSE,
        input_kind=NetflixInputKind.NONE,
        focused_title="Profile",
    )
    assert socket.closed


def test_type_submit_runs_once_in_one_short_transaction_and_returns_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    submitted_context = {
        **LOGIN_PASSWORD_CONTEXT,
        "input_kind": "none",
        "can_submit": False,
    }
    socket = FakeSocket(
        runtime_results=[
            {
                "ok": True,
                "status": "focused",
                "focus": VALID_FOCUS,
                "context": LOGIN_PASSWORD_CONTEXT,
            },
            {
                "ok": True,
                "status": "submitted",
                "context": submitted_context,
            },
        ]
    )
    connect, _ = install_transport(monkeypatch, controller, [socket])

    context = asyncio.run(controller.type_text("secret", submit=True))

    methods = [message["method"] for message in socket.sent]
    assert methods.count("Input.insertText") == 1
    assert len(runtime_expressions(socket)) == 2
    assert context.input_kind is NetflixInputKind.NONE
    assert "secret" not in repr(context)
    assert len(connect.calls) == 1
    assert socket.closed


def test_insert_text_ack_loss_does_not_send_submit_or_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket(
        runtime_result={
            "ok": True,
            "status": "focused",
            "focus": VALID_FOCUS,
            "context": LOGIN_PASSWORD_CONTEXT,
        },
        drop_insert_ack=True,
    )
    connect, _ = install_transport(monkeypatch, controller, [socket])

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.type_text("secret", submit=True))

    assert caught.value.code == "netflix_controller_unavailable"
    assert len(connect.calls) == 1
    assert len(runtime_expressions(socket)) == 1
    assert [message["method"] for message in socket.sent].count("Input.insertText") == 1
    assert socket.closed


def test_submit_ack_loss_does_not_reconnect_or_repeat_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket(
        runtime_result={
            "ok": True,
            "status": "focused",
            "focus": VALID_FOCUS,
            "context": LOGIN_PASSWORD_CONTEXT,
        },
        drop_run_ack_at=2,
    )
    connect, _ = install_transport(monkeypatch, controller, [socket])

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.type_text("secret", submit=True))

    assert caught.value.code == "netflix_controller_unavailable"
    assert len(connect.calls) == 1
    submit_expressions = [
        expression for expression in runtime_expressions(socket) if '"SUBMIT_PRIMARY"' in expression
    ]
    assert len(submit_expressions) == 1
    assert socket.closed


def test_ok_direct_play_unknown_outcome_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket(drop_run_ack=True)
    connect, _ = install_transport(monkeypatch, controller, [socket])

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.execute(Command.OK))

    assert caught.value.code == "netflix_controller_unavailable"
    assert len(connect.calls) == 1
    assert len(runtime_expressions(socket)) == 1
    assert socket.closed


def test_submit_after_insert_skips_revalidation_and_never_repeats_insert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    submitted_context = {
        **LOGIN_PASSWORD_CONTEXT,
        "input_kind": "none",
        "can_submit": False,
    }
    first = FakeSocket(
        runtime_results=[
            {
                "ok": True,
                "status": "focused",
                "focus": VALID_FOCUS,
                "context": LOGIN_PASSWORD_CONTEXT,
            },
            {
                "ok": True,
                "status": "submitted",
                "context": submitted_context,
            },
        ],
        drop_version_ack_at=2,
    )
    second = FakeSocket()
    connect, _ = install_transport(monkeypatch, controller, [first, second])

    context = asyncio.run(controller.type_text("secret", submit=True))

    assert context.input_kind is NetflixInputKind.NONE
    assert first.version_calls == 1
    assert [message["method"] for message in first.sent].count("Input.insertText") == 1
    assert len(connect.calls) == 1
    assert second.sent == []
    assert first.closed
    assert not second.closed


def test_fullscreen_runtime_evaluate_uses_user_gesture_and_returns_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket(
        runtime_result={
            "ok": True,
            "status": "fullscreen",
            "context": {
                "stage": "watch",
                "input_kind": "none",
                "has_error": False,
                "can_submit": False,
                "focused_title": None,
            },
        }
    )
    connect, _ = install_transport(monkeypatch, controller, [socket])

    context = asyncio.run(controller.execute(Command.FULLSCREEN))

    request = next(
        message
        for message in socket.sent
        if message["method"] == "Runtime.evaluate"
        and '"FULLSCREEN"' in message["params"]["expression"]
    )
    assert request["params"]["userGesture"] is True
    assert context.stage is NetflixStage.WATCH
    assert len(connect.calls) == 1
    assert socket.closed


def test_speed_runtime_evaluate_uses_user_gesture_and_records_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket(runtime_result=SPEED_WATCH_RESULT)
    connect, _ = install_transport(monkeypatch, controller, [socket])

    context = asyncio.run(controller.execute(Command.SPEED_UP))

    request = next(
        message
        for message in socket.sent
        if message["method"] == "Runtime.evaluate"
        and '"SPEED_UP"' in message["params"]["expression"]
    )
    assert request["params"]["userGesture"] is True
    assert context.stage is NetflixStage.WATCH
    assert controller.last_playback_rate == 1.25
    assert len(connect.calls) == 1
    assert socket.closed


@pytest.mark.parametrize(
    ("command", "status", "focus"),
    [
        (Command.OK, "clicked", VALID_FOCUS),
        (Command.PLAY_PAUSE, "playing", None),
        (Command.FULLSCREEN, "fullscreen", None),
        (Command.SEEK_FORWARD_5, "seek", None),
        (Command.SEEK_BACKWARD_5, "seek", None),
    ],
)
def test_side_effect_runtime_actions_use_user_gesture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: Command,
    status: str,
    focus: dict[str, Any] | None,
) -> None:
    controller = make_controller(tmp_path)
    result: dict[str, Any] = {
        "ok": True,
        "status": status,
        "context": {
            "stage": "watch",
            "input_kind": "none",
            "has_error": False,
            "can_submit": False,
            "focused_title": None,
        },
    }
    if focus is not None:
        result["focus"] = focus
    socket = FakeSocket(runtime_result=result)
    install_transport(monkeypatch, controller, [socket])

    asyncio.run(controller.execute(command))

    request = next(
        message
        for message in socket.sent
        if message["method"] == "Runtime.evaluate"
        and f'"{command.value}"' in message["params"]["expression"]
    )
    assert request["params"]["userGesture"] is True


def test_ok_watch_sends_one_fullscreen_evaluate_in_the_same_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket(runtime_results=[PLAYING_WATCH_RESULT, FULLSCREEN_WATCH_RESULT])
    connect, page_calls = install_transport(monkeypatch, controller, [socket])

    context = asyncio.run(controller.execute(Command.OK))

    runs = runtime_expressions(socket)
    assert len(runs) == 2
    assert '"OK"' in runs[0]
    assert '"FULLSCREEN"' in runs[1]
    fullscreen = next(
        message
        for message in socket.sent
        if message["method"] == "Runtime.evaluate"
        and '"FULLSCREEN"' in message["params"]["expression"]
    )
    assert fullscreen["params"]["userGesture"] is True
    assert context == NetflixContext(
        stage=NetflixStage.WATCH,
        input_kind=NetflixInputKind.NONE,
    )
    assert page_calls == [9222]
    assert len(connect.calls) == 1
    assert socket.closed


def test_ok_fullscreen_reject_does_not_replay_play(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = make_controller(tmp_path)
    socket = FakeSocket(
        runtime_results=[
            PLAYING_WATCH_RESULT,
            {
                "ok": False,
                "status": "error",
                "code": "netflix_fullscreen_unavailable",
            },
        ]
    )
    connect, page_calls = install_transport(monkeypatch, controller, [socket, FakeSocket()])

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.execute(Command.OK))

    assert caught.value.code == "netflix_fullscreen_unavailable"
    runs = runtime_expressions(socket)
    assert len(runs) == 2
    assert '"OK"' in runs[0]
    assert '"FULLSCREEN"' in runs[1]
    assert sum('"OK"' in expression for expression in runs) == 1
    assert page_calls == [9222]
    assert len(connect.calls) == 1
    assert socket.closed
