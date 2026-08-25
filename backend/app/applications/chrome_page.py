from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import websockets

from app.commands.ports import CommandExecutionError

FOCUS_LOGIN_SCRIPT = """(() => {
  const visible = (el) => {
    if (!(el instanceof HTMLElement)) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
      return false;
    }
    const box = el.getBoundingClientRect();
    return box.width > 8 && box.height > 8;
  };
  const signIn = [...document.querySelectorAll("a, button")].find((el) => {
    const label = `${el.textContent || ""} ${el.getAttribute("data-uia") || ""}`;
    return visible(el) && /sign[\\s-]?in|log[\\s-]?in|登入/i.test(label);
  });
  const inputs = [...document.querySelectorAll("input, textarea")].filter(visible);
  if (signIn && inputs.length === 0) {
    signIn.click();
    return "signin";
  }
  const score = (el) => {
    const hint = [
      el.type || "",
      el.name || "",
      el.id || "",
      el.getAttribute("autocomplete") || "",
      el.getAttribute("data-uia") || "",
    ].join(" ");
    if (/password/i.test(hint) || el.type === "password") return 2;
    if (/email|userLogin|user_login|loginId/i.test(hint) || el.type === "email") return 3;
    if (el.type === "text" || el.type === "tel" || el.tagName === "TEXTAREA") return 1;
    return 0;
  };
  const active = document.activeElement;
  const target =
    (active instanceof HTMLElement && inputs.includes(active) && score(active) > 0 ? active : null) ||
    inputs.sort((left, right) => score(right) - score(left))[0] ||
    null;
  if (!(target instanceof HTMLElement)) return null;
  target.focus();
  target.click();
  return target instanceof HTMLInputElement ? target.type || "text" : "text";
})()"""

FOCUS_NEXT_SCRIPT = """(() => {
  const visible = (el) => {
    if (!(el instanceof HTMLElement)) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const box = el.getBoundingClientRect();
    return box.width > 8 && box.height > 8;
  };
  const inputs = [...document.querySelectorAll("input, textarea, button")].filter(visible);
  if (inputs.length === 0) return null;
  const current = document.activeElement;
  const index = inputs.indexOf(current);
  const target = inputs[(index + 1) % inputs.length];
  target.focus();
  if (target instanceof HTMLElement) target.click();
  return true;
})()"""


def select_debugger_url(pages: list[dict[str, Any]], *, url_hint: str = "netflix.com") -> str | None:
    hinted = [
        page
        for page in pages
        if url_hint in str(page.get("url", "")).lower()
    ]
    for page in hinted or pages:
        debugger = page.get("webSocketDebuggerUrl")
        if debugger:
            return str(debugger)
    return None


class ChromePageInput:
    def __init__(self, timeout: float = 8.0) -> None:
        self._timeout = timeout

    async def ready(self, port: int) -> bool:
        try:
            pages = await self._list_pages(port)
        except Exception:
            return False
        return select_debugger_url(pages) is not None

    async def focus_login_field(self, port: int) -> str | None:
        return await self._evaluate_until(port, FOCUS_LOGIN_SCRIPT)

    async def type_text(self, port: int, text: str) -> None:
        debugger = await self._wait_for_debugger(port)
        async with websockets.connect(
            debugger, open_timeout=self._timeout, max_size=2**22
        ) as socket:
            focused = await self._evaluate_on(socket, FOCUS_LOGIN_SCRIPT)
            if not focused:
                raise CommandExecutionError(
                    "input_field_unavailable",
                    "找不到 Netflix 登入欄。請等登入畫面出現後再送一次。",
                )
            await self._call(socket, "Input.insertText", {"text": text})

    async def focus_next_field(self, port: int) -> None:
        result = await self._evaluate_until(port, FOCUS_NEXT_SCRIPT)
        if not result:
            raise CommandExecutionError(
                "input_field_unavailable",
                "找不到下一個輸入欄。",
            )

    async def _evaluate_until(self, port: int, expression: str) -> str | None:
        debugger = await self._wait_for_debugger(port)
        deadline = asyncio.get_running_loop().time() + self._timeout
        last: str | None = None
        while asyncio.get_running_loop().time() < deadline:
            async with websockets.connect(
                debugger, open_timeout=self._timeout, max_size=2**22
            ) as socket:
                last = await self._evaluate_on(socket, expression)
            if last and last != "signin":
                return last
            await asyncio.sleep(0.25)
        return last

    async def _wait_for_debugger(self, port: int) -> str:
        deadline = asyncio.get_running_loop().time() + self._timeout
        last_error: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                pages = await self._list_pages(port)
                debugger = select_debugger_url(pages)
                if debugger:
                    return debugger
            except Exception as error:  # noqa: BLE001 - retry until timeout
                last_error = error
            await asyncio.sleep(0.2)
        raise CommandExecutionError(
            "input_target_unavailable",
            f"無法連到 Netflix 頁面輸入欄。{last_error or ''}".strip(),
        )

    async def _list_pages(self, port: int) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=1.0) as client:
            response = await client.get(f"http://127.0.0.1:{port}/json/list")
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            return []
        return [page for page in payload if isinstance(page, dict) and page.get("type") == "page"]

    async def _evaluate_on(self, socket: Any, expression: str) -> str | None:
        result = await self._call(
            socket,
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        value = ((result or {}).get("result") or {}).get("value")
        if value in {None, False}:
            return None
        return str(value)

    @staticmethod
    async def _call(socket: Any, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        command_id = id(params) % 1_000_000 + 1
        await socket.send(json.dumps({"id": command_id, "method": method, "params": params}))
        while True:
            payload = json.loads(await socket.recv())
            if payload.get("id") != command_id:
                continue
            if payload.get("error"):
                raise RuntimeError(str(payload["error"]))
            result = payload.get("result")
            return result if isinstance(result, dict) else None
