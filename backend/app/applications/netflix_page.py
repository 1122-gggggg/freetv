from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import websockets
from pydantic import ValidationError

from app.commands.ports import CommandExecutionError
from app.protocol import Command, NetflixContext, NetflixStage

RUNTIME_VERSION = "8"
ERROR_MESSAGES = {
    "netflix_page_unavailable": "無法連到 Netflix 控制頁面，請稍後再試。",
    "netflix_controller_unavailable": "無法載入 Netflix 遙控控制，請稍後再試。",
    "netflix_target_unsupported": "Netflix 目前畫面不是可控制的主要頁面。",
    "netflix_focus_unavailable": "找不到可操作的 Netflix 項目，請稍後再試。",
    "netflix_input_unavailable": "找不到可輸入的 Netflix 欄位，請先選取輸入欄。",
    "netflix_video_unavailable": "目前沒有可播放或暫停的 Netflix 影片。",
    "netflix_direct_play_unavailable": "找不到可播放的 Netflix 項目，請稍後再試。",
    "netflix_submit_unavailable": "Netflix 目前無法送出，請確認電視畫面後再試。",
    "netflix_back_unavailable": "Netflix 目前無法返回，請確認電視畫面後再試。",
    "netflix_fullscreen_unavailable": "Netflix 目前沒有可切換為全螢幕的影片。",
}
RUNTIME_ERROR_CODES = {
    "netflix_focus_unavailable",
    "netflix_input_unavailable",
    "netflix_video_unavailable",
    "netflix_direct_play_unavailable",
    "netflix_submit_unavailable",
    "netflix_back_unavailable",
    "netflix_fullscreen_unavailable",
}
FINGERPRINT_STRING_FIELDS = ("role", "label", "uia", "text", "pathKind", "rail")
FINGERPRINT_FIELDS = (*FINGERPRINT_STRING_FIELDS, "index")
RUNTIME_STATUSES = {
    "focused",
    "restored",
    "error_refocused",
    "moved",
    "boundary",
    "clicked",
    "closed",
    "history",
    "playing",
    "paused",
    "fullscreen",
    "speed",
    "seek",
    "text",
    "osd",
    "context",
    "submitted",
    "error",
}
FOCUS_REQUIRED_STATUSES = {
    "focused",
    "restored",
    "error_refocused",
    "moved",
    "boundary",
    "clicked",
    "text",
}
NO_FOCUS_STATUSES = {
    "closed",
    "history",
    "playing",
    "paused",
    "speed",
    "seek",
    "osd",
    "quality",
    "subtitles",
    "context",
    "submitted",
}


class NetflixAction(StrEnum):
    FOCUS_PRIMARY = "FOCUS_PRIMARY"
    FOCUS_EDITABLE = "FOCUS_EDITABLE"
    FOCUS_NEXT = "FOCUS_NEXT"
    NAV_UP = "NAV_UP"
    NAV_DOWN = "NAV_DOWN"
    NAV_LEFT = "NAV_LEFT"
    NAV_RIGHT = "NAV_RIGHT"
    OK = "OK"
    BACK = "BACK"
    PLAY_PAUSE = "PLAY_PAUSE"
    FULLSCREEN = "FULLSCREEN"
    SPEED_UP = "SPEED_UP"
    SPEED_DOWN = "SPEED_DOWN"
    SEEK_FORWARD_5 = "SEEK_FORWARD_5"
    SEEK_BACKWARD_5 = "SEEK_BACKWARD_5"
    SET_TEXT = "SET_TEXT"
    SHOW_OSD = "SHOW_OSD"
    READ_CONTEXT = "READ_CONTEXT"
    SUBMIT_PRIMARY = "SUBMIT_PRIMARY"
    QUALITY = "QUALITY"
    SUBTITLES = "SUBTITLES"
IDEMPOTENT_ACTIONS = {
    NetflixAction.FOCUS_PRIMARY,
    NetflixAction.FOCUS_EDITABLE,
    NetflixAction.READ_CONTEXT,
}

COMMAND_ACTIONS: dict[Command, NetflixAction] = {
    Command.NAV_UP: NetflixAction.NAV_UP,
    Command.NAV_DOWN: NetflixAction.NAV_DOWN,
    Command.NAV_LEFT: NetflixAction.NAV_LEFT,
    Command.NAV_RIGHT: NetflixAction.NAV_RIGHT,
    Command.OK: NetflixAction.OK,
    Command.BACK: NetflixAction.BACK,
    Command.PLAY_PAUSE: NetflixAction.PLAY_PAUSE,
    Command.FULLSCREEN: NetflixAction.FULLSCREEN,
    Command.SPEED_UP: NetflixAction.SPEED_UP,
    Command.SPEED_DOWN: NetflixAction.SPEED_DOWN,
    Command.SEEK_FORWARD_5: NetflixAction.SEEK_FORWARD_5,
    Command.SEEK_BACKWARD_5: NetflixAction.SEEK_BACKWARD_5,
    Command.TAB: NetflixAction.FOCUS_NEXT,
    Command.QUALITY: NetflixAction.QUALITY,
    Command.SUBTITLES: NetflixAction.SUBTITLES,
}

FocusFingerprint = dict[str, str | int]
Operation = Callable[[Any], Awaitable[NetflixContext]]


class _RetryableControllerError(RuntimeError):
    pass


class _OutcomeUnknownError(RuntimeError):
    pass


class _CdpCallError(RuntimeError):
    pass


def _is_netflix_host(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "netflix.com" or host.endswith(".netflix.com")


def _is_local_debugger_url(url: object) -> bool:
    if not isinstance(url, str) or not url:
        return False
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "ws"
        and parsed.hostname == "127.0.0.1"
        and port is not None
        and 1 <= port <= 65535
        and parsed.username is None
        and parsed.password is None
    )


def select_netflix_target(pages: list[dict[str, Any]]) -> str:
    netflix = [page for page in pages if _is_netflix_host(str(page.get("url", "")))]
    if any(page.get("type") != "page" or page.get("openerId") for page in netflix):
        raise CommandExecutionError(
            "netflix_target_unsupported",
            ERROR_MESSAGES["netflix_target_unsupported"],
        )

    debugger_pages = [page for page in netflix if "webSocketDebuggerUrl" in page]
    if any(not _is_local_debugger_url(page.get("webSocketDebuggerUrl")) for page in debugger_pages):
        raise CommandExecutionError(
            "netflix_target_unsupported",
            ERROR_MESSAGES["netflix_target_unsupported"],
        )
    if len(debugger_pages) > 1:
        raise CommandExecutionError(
            "netflix_target_unsupported",
            ERROR_MESSAGES["netflix_target_unsupported"],
        )
    if not debugger_pages:
        raise CommandExecutionError(
            "netflix_page_unavailable",
            ERROR_MESSAGES["netflix_page_unavailable"],
        )
    return str(debugger_pages[0]["webSocketDebuggerUrl"])


class NetflixPageController:
    VERSION_EXPRESSION = "globalThis.__freeTvNetflixControl?.version ?? null"

    def __init__(
        self,
        port: int,
        timeout: float = 10.0,
        runtime_path: Path | None = None,
    ) -> None:
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be an integer from 1 to 65535")
        self._port = port
        self._timeout = timeout
        self._runtime_source = (
            runtime_path or Path(__file__).with_name("netflix_control.js")
        ).read_text(encoding="utf-8")
        self._focus: FocusFingerprint | None = None
        self._command_id = 0
        self.last_playback_rate = 1.0

    async def initialize(self) -> NetflixContext:
        async def operation(socket: Any) -> NetflixContext:
            result = await self._run_runtime(socket, NetflixAction.FOCUS_PRIMARY)
            return self._accept_runtime_result(result)

        return await self._run_transaction(operation)

    async def execute(self, command: Command) -> NetflixContext:
        if not isinstance(command, Command):
            raise TypeError("command must be a Command")
        action = COMMAND_ACTIONS.get(command)
        if action is None:
            raise CommandExecutionError(
                "command_not_supported",
                "Netflix 不支援這個遙控指令。",
            )

        async def operation(socket: Any) -> NetflixContext:
            result = await self._run_runtime(socket, action)
            try:
                context = self._accept_runtime_result(result)
            except _RetryableControllerError:
                if action not in IDEMPOTENT_ACTIONS:
                    raise _OutcomeUnknownError from None
                raise
            if action is NetflixAction.OK and context.stage is NetflixStage.WATCH:
                fullscreen = await self._run_action(socket, NetflixAction.FULLSCREEN)
                try:
                    self._accept_runtime_result(fullscreen)
                except _RetryableControllerError:
                    raise _OutcomeUnknownError from None
            return context

        return await self._run_transaction(operation)

    async def type_text(
        self,
        text: str,
        submit: bool = False,
    ) -> NetflixContext:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if type(submit) is not bool:
            raise TypeError("submit must be a bool")

        async def operation(socket: Any) -> NetflixContext:
            focused = self._accept_runtime_result(
                await self._run_runtime(socket, NetflixAction.FOCUS_EDITABLE)
            )
            await self._call(
                socket,
                "Input.insertText",
                {"text": text},
                outcome_unknown_on_failure=True,
            )
            if not submit:
                return focused
            result = await self._run_action(socket, NetflixAction.SUBMIT_PRIMARY)
            try:
                return self._accept_runtime_result(result)
            except _RetryableControllerError:
                raise _OutcomeUnknownError from None

        return await self._run_transaction(operation)

    async def show_osd(self, text: str) -> None:
        async def operation(socket: Any) -> NetflixContext:
            result = await self._run_runtime(
                socket,
                NetflixAction.SHOW_OSD,
                previous_focus={"text": text},
            )
            return self._accept_runtime_result(result)

        try:
            await self._run_transaction(operation)
        except Exception:
            pass

    async def _run_transaction(self, operation: Operation) -> NetflixContext:
        failure_code = "netflix_page_unavailable"
        for attempt in range(2):
            try:
                pages = await self._list_pages(self._port)
                debugger_url = select_netflix_target(pages)
                async with websockets.connect(
                    debugger_url,
                    open_timeout=self._timeout,
                    max_size=2**22,
                ) as socket:
                    return await operation(socket)
            except _OutcomeUnknownError:
                raise CommandExecutionError(
                    "netflix_controller_unavailable",
                    ERROR_MESSAGES["netflix_controller_unavailable"],
                ) from None
            except CommandExecutionError:
                raise
            except _RetryableControllerError:
                failure_code = "netflix_controller_unavailable"
            except Exception:
                failure_code = "netflix_page_unavailable"

            if attempt == 1:
                raise CommandExecutionError(
                    failure_code,
                    ERROR_MESSAGES[failure_code],
                ) from None
        raise AssertionError("unreachable")

    async def _list_pages(self, port: int) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(f"http://127.0.0.1:{port}/json/list")
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("CDP target list must be an array")
        return [page for page in payload if isinstance(page, dict)]

    async def _evaluate(
        self,
        socket: Any,
        expression: str,
        *,
        outcome_unknown_on_failure: bool = False,
        user_gesture: bool = False,
    ) -> Any:
        params: dict[str, Any] = {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        }
        if user_gesture:
            params["userGesture"] = True
        response = await self._call(
            socket,
            "Runtime.evaluate",
            params,
            outcome_unknown_on_failure=outcome_unknown_on_failure,
        )
        if response.get("exceptionDetails") is not None:
            if outcome_unknown_on_failure:
                raise _OutcomeUnknownError
            raise _CdpCallError
        remote = response.get("result")
        if not isinstance(remote, dict):
            if outcome_unknown_on_failure:
                raise _OutcomeUnknownError
            raise _CdpCallError
        return remote.get("value")

    async def _run_runtime(
        self, socket: Any, action: NetflixAction, previous_focus: Any = None
    ) -> Any:
        try:
            version = await self._evaluate(socket, self.VERSION_EXPRESSION)
            if version != RUNTIME_VERSION:
                await self._evaluate(socket, self._runtime_source)
                version = await self._evaluate(socket, self.VERSION_EXPRESSION)
                if version != RUNTIME_VERSION:
                    raise _RetryableControllerError
            return await self._run_action(socket, action, previous_focus=previous_focus)
        except CommandExecutionError:
            raise
        except _OutcomeUnknownError:
            raise
        except _RetryableControllerError:
            raise
        except Exception:
            raise _RetryableControllerError from None

    async def _run_action(
        self, socket: Any, action: NetflixAction, previous_focus: Any = None
    ) -> Any:
        focus_payload = previous_focus
        if focus_payload is None and self._focus is not None:
            focus_payload = {field: self._focus[field] for field in FINGERPRINT_FIELDS}
        action_json = json.dumps(action.value, ensure_ascii=True)
        focus_json = json.dumps(focus_payload, ensure_ascii=True)
        expression = f"globalThis.__freeTvNetflixControl.run({action_json}, {focus_json})"
        return await self._evaluate(
            socket,
            expression,
            outcome_unknown_on_failure=action not in IDEMPOTENT_ACTIONS,
            user_gesture=action
            in {
                NetflixAction.OK,
                NetflixAction.PLAY_PAUSE,
                NetflixAction.FULLSCREEN,
                NetflixAction.SPEED_UP,
                NetflixAction.SPEED_DOWN,
                NetflixAction.SEEK_FORWARD_5,
                NetflixAction.SEEK_BACKWARD_5,
            },
        )

    def _accept_runtime_result(self, result: Any) -> NetflixContext:
        if not isinstance(result, dict):
            raise _RetryableControllerError
        keys = set(result)
        allowed_keys = {"ok", "status", "code", "focus", "context", "rate"}
        if not {"ok", "status"}.issubset(keys) or not keys <= allowed_keys:
            raise _RetryableControllerError

        ok = result["ok"]
        status = result["status"]
        if type(ok) is not bool or not isinstance(status, str):
            raise _RetryableControllerError
        if not 1 <= len(status) <= 64 or status not in RUNTIME_STATUSES:
            raise _RetryableControllerError

        code = result.get("code")
        if ok:
            if "code" in result or status == "error" or "context" not in result:
                raise _RetryableControllerError
        else:
            if (
                status != "error"
                or code not in RUNTIME_ERROR_CODES
                or "focus" in result
                or "context" in result
                or "rate" in result
            ):
                raise _RetryableControllerError

        rate_value = result.get("rate")
        if ok and status == "speed":
            if type(rate_value) not in {int, float} or not 0.25 <= float(rate_value) <= 4:
                raise _RetryableControllerError
        elif "rate" in result:
            raise _RetryableControllerError

        has_focus = "focus" in result
        if ok and status in FOCUS_REQUIRED_STATUSES and not has_focus:
            raise _RetryableControllerError
        if ok and status in NO_FOCUS_STATUSES and has_focus:
            raise _RetryableControllerError

        accepted_focus: FocusFingerprint | None = None
        if "focus" in result:
            focus = result["focus"]
            if not isinstance(focus, dict) or set(focus) != set(FINGERPRINT_FIELDS):
                raise _RetryableControllerError
            for field in FINGERPRINT_STRING_FIELDS:
                value = focus[field]
                if not isinstance(value, str) or len(value) > 256:
                    raise _RetryableControllerError
            index = focus["index"]
            if type(index) is not int or not 0 <= index <= 1_000_000:
                raise _RetryableControllerError
            accepted_focus = {field: focus[field] for field in FINGERPRINT_FIELDS}

        if not ok:
            raise CommandExecutionError(code, ERROR_MESSAGES[code])
        try:
            context = NetflixContext.model_validate(result["context"])
        except ValidationError:
            raise CommandExecutionError(
                "netflix_controller_unavailable",
                ERROR_MESSAGES["netflix_controller_unavailable"],
            ) from None
        if accepted_focus is not None:
            self._focus = accepted_focus
        elif status == "submitted":
            self._focus = None
        if ok and status == "speed":
            self.last_playback_rate = float(rate_value)
        return context

    async def _call(
        self,
        socket: Any,
        method: str,
        params: dict[str, Any],
        *,
        outcome_unknown_on_failure: bool = False,
    ) -> dict[str, Any]:
        self._command_id += 1
        command_id = self._command_id
        request = json.dumps(
            {"id": command_id, "method": method, "params": params},
            ensure_ascii=True,
        )
        try:
            await asyncio.wait_for(socket.send(request), timeout=self._timeout)
            while True:
                raw = await asyncio.wait_for(socket.recv(), timeout=self._timeout)
                if not isinstance(raw, str) or len(raw) > 2**22:
                    raise _CdpCallError
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    raise _CdpCallError from None
                if not isinstance(payload, dict):
                    raise _CdpCallError
                if payload.get("id") != command_id:
                    continue
                if payload.get("error") is not None:
                    raise _CdpCallError
                result = payload.get("result")
                if not isinstance(result, dict):
                    raise _CdpCallError
                return result
        except Exception:
            if outcome_unknown_on_failure:
                raise _OutcomeUnknownError from None
            raise
