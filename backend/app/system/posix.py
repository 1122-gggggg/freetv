from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence

from app.commands.ports import CommandExecutionError
from app.protocol import Command, PointerAction, PointerActionMessage

CommandRunner = Callable[[Sequence[str]], str]
ToolLookup = Callable[..., str | None]

LAUNCHER_TITLE = "我的電視"

_XDOTOL_KEYS: dict[Command, str] = {
    Command.NAV_UP: "Up",
    Command.NAV_DOWN: "Down",
    Command.NAV_LEFT: "Left",
    Command.NAV_RIGHT: "Right",
    Command.OK: "Return",
    Command.BACK: "Escape",
    Command.TAB: "Tab",
    Command.PLAY_PAUSE: "space",
    Command.FULLSCREEN: "F11",
    Command.NEXT: "XF86AudioNext",
    Command.PREVIOUS: "XF86AudioPrev",
}

_MAC_KEY_CODES: dict[Command, str] = {
    Command.NAV_UP: "126",
    Command.NAV_DOWN: "125",
    Command.NAV_LEFT: "123",
    Command.NAV_RIGHT: "124",
    Command.OK: "36",
    Command.BACK: "53",
    Command.TAB: "48",
    Command.PLAY_PAUSE: "49",
    Command.FULLSCREEN: "103",
    Command.NEXT: "119",
    Command.PREVIOUS: "115",
}


def run_command(arguments: Sequence[str], *, timeout: float = 3.0) -> str:
    try:
        completed = subprocess.run(
            list(arguments),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CommandExecutionError(
            "posix_command_failed",
            f"無法執行 {arguments[0]}。",
        ) from error
    if completed.returncode != 0:
        raise CommandExecutionError(
            "posix_command_failed",
            f"{arguments[0]} 回傳失敗。",
        )
    return completed.stdout


def which_first(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class PosixInputController:
    def __init__(
        self,
        runner: CommandRunner | None = None,
        lookup: ToolLookup | None = None,
    ) -> None:
        self._run = runner or run_command
        self._lookup = lookup or which_first

    async def pointer(self, message: PointerActionMessage) -> None:
        backend = self._backend()
        if backend == "xdotool":
            self._xdotool_pointer(message)
            return
        if backend == "osascript":
            raise CommandExecutionError(
                "pointer_unavailable",
                "這個 macOS 環境沒有 cliclick，觸控板移動無法使用。",
            )
        raise CommandExecutionError("input_unavailable", "找不到 xdotool 或 osascript。")

    async def text(self, text: str) -> None:
        backend = self._backend()
        if backend == "xdotool":
            self._run(["xdotool", "type", "--delay", "0", "--", text])
            return
        if backend == "osascript":
            escaped = text.replace("\\", "\\\\").replace('"', '\\"')
            self._run(
                [
                    "osascript",
                    "-e",
                    f'tell application "System Events" to keystroke "{escaped}"',
                ]
            )
            return
        raise CommandExecutionError("input_unavailable", "找不到可用的文字輸入後端。")

    def send_command(self, command: Command) -> None:
        backend = self._backend()
        if backend == "xdotool":
            key = _XDOTOL_KEYS.get(command)
            if key is None:
                raise CommandExecutionError(
                    "unsupported_forward_command",
                    "這個操作不適用於目前的應用程式。",
                )
            self._run(["xdotool", "key", key])
            return
        if backend == "osascript":
            code = _MAC_KEY_CODES.get(command)
            if code is None:
                raise CommandExecutionError(
                    "unsupported_forward_command",
                    "這個操作不適用於目前的應用程式。",
                )
            self._run(
                [
                    "osascript",
                    "-e",
                    f'tell application "System Events" to key code {code}',
                ]
            )
            return
        raise CommandExecutionError("input_unavailable", "找不到可用的鍵盤後端。")

    def send_browser_back(self) -> None:
        backend = self._backend()
        if backend == "xdotool":
            self._run(["xdotool", "key", "alt+Left"])
            return
        if backend == "osascript":
            self._run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to key code 123 using {command down}',
                ]
            )
            return
        raise CommandExecutionError("input_unavailable", "找不到可用的返回鍵後端。")

    def _backend(self) -> str:
        if self._lookup("xdotool"):
            return "xdotool"
        if sys.platform == "darwin" and self._lookup("osascript"):
            return "osascript"
        return ""

    def _xdotool_pointer(self, message: PointerActionMessage) -> None:
        if message.action is PointerAction.MOVE:
            self._run(["xdotool", "mousemove_relative", "--", str(message.dx), str(message.dy)])
        elif message.action is PointerAction.TAP:
            self._run(["xdotool", "click", "1"])
        elif message.action is PointerAction.DOUBLE_TAP:
            self._run(["xdotool", "click", "--repeat", "2", "--delay", "50", "1"])
        elif message.action is PointerAction.SCROLL:
            button = "4" if message.dy >= 0 else "5"
            repeats = str(max(1, min(abs(message.dy), 30)))
            self._run(["xdotool", "click", "--repeat", repeats, button])
        else:  # pragma: no cover - Pydantic prevents unknown actions.
            raise CommandExecutionError("invalid_pointer_action", "不允許這個觸控板操作。")


class PosixVolumeController:
    def __init__(
        self,
        *,
        step_percent: int = 5,
        runner: CommandRunner | None = None,
        lookup: ToolLookup | None = None,
    ) -> None:
        self._step = step_percent
        self._run = runner or run_command
        self._lookup = lookup or which_first

    async def increase(self) -> tuple[int, bool]:
        return self._adjust(self._step)

    async def decrease(self) -> tuple[int, bool]:
        return self._adjust(-self._step)

    async def toggle_mute(self) -> tuple[int, bool]:
        backend = self._backend()
        if backend == "wpctl":
            self._run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
            return self._read_wpctl()
        if backend == "pactl":
            self._run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
            return self._read_pactl()
        if backend == "osascript":
            muted = not self._read_osascript()[1]
            flag = "true" if muted else "false"
            self._run(["osascript", "-e", f"set volume output muted {flag}"])
            return self._read_osascript()
        raise CommandExecutionError("volume_unavailable", "找不到 wpctl、pactl 或 osascript。")

    def _adjust(self, delta: int) -> tuple[int, bool]:
        backend = self._backend()
        if backend == "wpctl":
            change = f"{abs(delta)}%+" if delta >= 0 else f"{abs(delta)}%-"
            self._run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", change, "-l", "1.0"])
            return self._read_wpctl()
        if backend == "pactl":
            sign = "+" if delta >= 0 else "-"
            self._run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}{abs(delta)}%"])
            return self._read_pactl()
        if backend == "osascript":
            level, muted = self._read_osascript()
            level = min(100, max(0, level + delta))
            self._run(["osascript", "-e", f"set volume output volume {level}"])
            return level, muted
        raise CommandExecutionError("volume_unavailable", "找不到可用的系統音量後端。")

    def _backend(self) -> str:
        if self._lookup("wpctl"):
            return "wpctl"
        if self._lookup("pactl"):
            return "pactl"
        if sys.platform == "darwin" and self._lookup("osascript"):
            return "osascript"
        return ""

    def _read_wpctl(self) -> tuple[int, bool]:
        output = self._run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
        muted = "[MUTED]" in output.upper()
        number = "".join(
            character for character in output if character.isdigit() or character == "."
        )
        try:
            level = int(round(float(number) * 100)) if "." in number else int(number or "0")
        except ValueError:
            level = 0
        return min(100, max(0, level)), muted

    def _read_pactl(self) -> tuple[int, bool]:
        volume_text = self._run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
        mute_text = self._run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
        percent = 0
        for token in volume_text.replace(",", " ").split():
            if token.endswith("%"):
                try:
                    percent = int(token[:-1])
                    break
                except ValueError:
                    continue
        muted = "yes" in mute_text.casefold()
        return min(100, max(0, percent)), muted

    def _read_osascript(self) -> tuple[int, bool]:
        level_text = self._run(
            ["osascript", "-e", "output volume of (get volume settings)"]
        ).strip()
        muted_text = (
            self._run(["osascript", "-e", "output muted of (get volume settings)"])
            .strip()
            .casefold()
        )
        try:
            level = int(level_text)
        except ValueError:
            level = 0
        return min(100, max(0, level)), muted_text == "true"


class PosixPowerController:
    def __init__(
        self,
        runner: CommandRunner | None = None,
        lookup: ToolLookup | None = None,
    ) -> None:
        self._run = runner or run_command
        self._lookup = lookup or which_first

    async def sleep(self) -> None:
        if sys.platform == "darwin":
            if self._lookup("pmset"):
                self._run(["pmset", "sleepnow"])
                return
            raise CommandExecutionError("sleep_failed", "找不到 pmset，無法讓這台 Mac 休眠。")
        for command in (("systemctl", "suspend"), ("loginctl", "suspend")):
            if self._lookup(command[0]):
                self._run(list(command))
                return
        raise CommandExecutionError("sleep_failed", "這個系統沒有可用的休眠指令。")

    async def shutdown(self) -> None:
        if sys.platform == "darwin":
            if self._lookup("osascript"):
                self._run(
                    [
                        "osascript",
                        "-e",
                        'tell application "System Events" to shut down',
                    ]
                )
                return
            raise CommandExecutionError("shutdown_failed", "找不到 osascript，無法關閉這台 Mac。")
        for command in (("systemctl", "poweroff"), ("loginctl", "poweroff")):
            if self._lookup(command[0]):
                self._run(list(command))
                return
        raise CommandExecutionError("shutdown_failed", "這個系統沒有可用的關機指令。")


class PosixWindowController:
    """Treats PIDs as window handles so HOME/launch work without Win32 HWND."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        lookup: ToolLookup | None = None,
    ) -> None:
        self._run = runner or run_command
        self._lookup = lookup or which_first

    def find_window_for_pid(self, pid: int, timeout_seconds: float) -> int | None:
        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        while True:
            if pid_is_running(pid):
                return pid
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.1)

    def window_belongs_to_process(self, handle: int, pid: int) -> bool:
        return handle == pid and pid_is_running(pid)

    def minimize(self, handle: int) -> None:
        self._xdotool_pid("windowminimize", handle, only_visible=True)
        self._osascript_set_visible(handle, False)

    def maximize(self, handle: int) -> None:
        self._activate_pid(handle)

    def activate(self, handle: int) -> None:
        self._activate_pid(handle)

    def is_foreground(self, handle: int) -> bool:
        if not pid_is_running(handle):
            return False
        if self._lookup("xdotool"):
            try:
                active = self._run(["xdotool", "getactivewindow"]).strip()
                owner = self._run(["xdotool", "getwindowpid", active]).strip()
                return owner == str(handle)
            except CommandExecutionError:
                return False
        if sys.platform == "darwin":
            try:
                front = self._run(
                    [
                        "osascript",
                        "-e",
                        'tell application "System Events" '
                        "to unix id of first process whose frontmost is true",
                    ]
                ).strip()
                return front == str(handle)
            except CommandExecutionError:
                return False
        return False

    def bring_launcher_to_foreground(self) -> None:
        handle = self.focus_window_with_title(LAUNCHER_TITLE)
        if handle is not None:
            self.activate(handle)

    def close_launcher(self) -> None:
        handle = self.focus_window_with_title(LAUNCHER_TITLE)
        if handle is not None:
            self.close_window(handle)

    def focus_window_with_title(self, title_fragment: str) -> int | None:
        if self._lookup("xdotool"):
            try:
                window_id = self._run(
                    ["xdotool", "search", "--onlyvisible", "--name", title_fragment]
                ).split()[0]
                owner = self._run(["xdotool", "getwindowpid", window_id]).strip()
                return int(owner)
            except (CommandExecutionError, IndexError, ValueError):
                return None
        if sys.platform == "darwin":
            script = (
                'tell application "System Events"\n'
                f'set matches to every process whose name contains "{title_fragment}" '
                f'or (exists (window 1 whose name contains "{title_fragment}"))\n'
                "if matches is {} then return 0\n"
                "return unix id of item 1 of matches\n"
                "end tell"
            )
            try:
                owner = int(self._run(["osascript", "-e", script]).strip() or "0")
            except (CommandExecutionError, ValueError):
                return None
            return owner or None
        return None

    def close_window(self, handle: int) -> None:
        if not pid_is_running(handle):
            return
        try:
            os.kill(handle, signal.SIGTERM)
        except OSError as error:
            raise CommandExecutionError("window_close_failed", "無法關閉這個視窗。") from error

    def _activate_pid(self, handle: int) -> None:
        self._xdotool_pid("windowactivate", handle)
        if sys.platform != "darwin":
            return
        try:
            self._run(
                [
                    "osascript",
                    "-e",
                    (
                        'tell application "System Events" to set frontmost of '
                        f"(first process whose unix id is {handle}) to true"
                    ),
                ]
            )
        except CommandExecutionError:
            return

    def _osascript_set_visible(self, handle: int, visible: bool) -> None:
        if sys.platform != "darwin":
            return
        flag = "true" if visible else "false"
        try:
            self._run(
                [
                    "osascript",
                    "-e",
                    (
                        'tell application "System Events" to set visible of '
                        f"(first process whose unix id is {handle}) to {flag}"
                    ),
                ]
            )
        except CommandExecutionError:
            return

    def _xdotool_pid(self, action: str, pid: int, *, only_visible: bool = False) -> None:
        if not self._lookup("xdotool"):
            return
        search = ["xdotool", "search"]
        if only_visible:
            search.append("--onlyvisible")
        search.extend(["--pid", str(pid)])
        try:
            window_id = self._run(search).split()[0]
            if action == "windowactivate":
                try:
                    self._run(["xdotool", "windowmap", window_id])
                except CommandExecutionError:
                    pass
            self._run(["xdotool", action, window_id])
        except (CommandExecutionError, IndexError):
            return


class PosixBrightnessController:
    def __init__(
        self,
        *,
        step_percent: int = 10,
        initial_level: int = 100,
        runner: CommandRunner | None = None,
        lookup: ToolLookup | None = None,
    ) -> None:
        self._step = step_percent
        self._level = initial_level
        self._run = runner or run_command
        self._lookup = lookup or which_first

    async def increase(self) -> int:
        self._level = min(100, self._level + self._step)
        await self._apply_brightness(self._level)
        return self._level

    async def decrease(self) -> int:
        self._level = max(10, self._level - self._step)
        await self._apply_brightness(self._level)
        return self._level

    async def get_level(self) -> int:
        return self._level

    async def _apply_brightness(self, level: int) -> None:
        if self._lookup("brightnessctl"):
            try:
                self._run(["brightnessctl", "set", f"{level}%"])
                return
            except Exception:
                pass
        if self._lookup("brightness"):
            try:
                self._run(["brightness", str(level / 100)])
                return
            except Exception:
                pass
        if self._lookup("xrandr"):
            try:
                self._run(["xrandr", "--brightness", str(level / 100)])
                return
            except Exception:
                pass
