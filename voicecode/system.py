"""Linux-действия: приложения, сайты, скриншоты, громкость, окна, блокировка."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .apps import AppIndex, find_site
from .config import Config
from .paths import pictures_dir

log = logging.getLogger(__name__)

MONTHS_GENITIVE = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]


def time_reply(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"Сейчас {now:%H:%M}"


def date_reply(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"Сегодня {now.day} {MONTHS_GENITIVE[now.month - 1]} {now.year} года"


def _run(cmd: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("Команда %s не выполнилась: %s", cmd[0], exc)
        return None


def _which(name: str) -> str | None:
    return shutil.which(name)


def session_type() -> str:
    return os.environ.get("XDG_SESSION_TYPE", "").lower()


def current_desktop() -> str:
    return os.environ.get("XDG_CURRENT_DESKTOP", "").lower()


def is_wayland() -> bool:
    return session_type() == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def is_hyprland() -> bool:
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) or "hyprland" in current_desktop()


def is_sway() -> bool:
    return bool(os.environ.get("SWAYSOCK")) or "sway" in current_desktop()


def is_kde() -> bool:
    return "kde" in current_desktop() or "plasma" in current_desktop()


def is_gnome() -> bool:
    return "gnome" in current_desktop()


class SystemActions:
    def __init__(self, cfg: Config, apps: AppIndex | None = None) -> None:
        self.cfg = cfg
        self.apps = apps or AppIndex()
        configured = str(cfg.compositor or "auto").lower()
        self.compositor = self._detect_compositor(configured)

    @staticmethod
    def _detect_compositor(configured: str) -> str:
        if configured and configured != "auto":
            return configured
        if is_hyprland():
            return "hyprland"
        if is_sway():
            return "sway"
        if is_kde():
            return "kde"
        if is_gnome():
            return "gnome"
        if is_wayland():
            return "wayland"
        return "x11"

    # -------------------------------------------------------------- общее
    def notify(self, title: str, body: str) -> None:
        if not self.cfg.notifications or not _which("notify-send"):
            return
        _run(["notify-send", "-a", "VoiceCode", title, body], timeout=3)

    def open_url(self, url: str) -> tuple[bool, str]:
        if not _which("xdg-open"):
            return False, "Не установлен xdg-utils"
        try:
            subprocess.Popen(
                ["xdg-open", url],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True, "Открываю"
        except OSError as exc:
            return False, f"Не удалось открыть ссылку: {exc}"

    def open_site(self, query: str) -> tuple[bool, str]:
        found = find_site(query)
        if found is None:
            return False, f"Не знаю сайт «{query}»"
        _alias, url = found
        ok, _ = self.open_url(url)
        return (True, "Открываю сайт") if ok else (ok, "Не удалось открыть сайт")

    def search(self, query: str) -> tuple[bool, str]:
        query = query.strip()
        if not query:
            return False, "Не понял, что искать"
        template = str(self.cfg.search_url)
        url = template.format(query=quote(query))
        ok, _ = self.open_url(url)
        return (True, f"Ищу: {query}") if ok else (ok, "Не удалось открыть поиск")

    def screenshot(self) -> tuple[bool, str]:
        directory = (
            Path(str(self.cfg.screenshot_dir)).expanduser()
            if str(self.cfg.screenshot_dir or "").strip()
            else pictures_dir()
        )
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, f"Не удалось создать папку для скриншотов: {exc}"
        path = directory / f"Screenshot_{datetime.now():%Y-%m-%d_%H-%M-%S}.png"

        commands: list[list[str]] = []
        if is_wayland():
            if _which("grim"):
                commands.append(["grim", str(path)])
            if _which("spectacle"):
                commands.append(["spectacle", "-b", "-n", "-o", str(path)])
            if _which("gnome-screenshot"):
                commands.append(["gnome-screenshot", "-f", str(path)])
            if _which("flameshot"):
                commands.append(["flameshot", "full", "-p", str(directory)])
        if _which("scrot"):
            commands.append(["scrot", "-q", "100", str(path)])
        if _which("maim"):
            commands.append(["maim", str(path)])

        for command in commands:
            result = _run(command, timeout=20)
            if result is not None and result.returncode == 0:
                self.notify("Скриншот", str(path))
                return True, "Сделал скриншот"
        return False, "Не нашёл чем сделать скриншот. Установи grim или spectacle."

    # ------------------------------------------------------------ громкость
    def volume(self, action: str) -> tuple[bool, str]:
        step = max(1, min(50, int(self.cfg.volume_step)))
        if _which("wpctl"):
            sink = "@DEFAULT_AUDIO_SINK@"
            if action == "up":
                result = _run(["wpctl", "set-volume", sink, f"{step}%+"])
            elif action == "down":
                result = _run(["wpctl", "set-volume", sink, f"{step}%-"])
            elif action == "mute":
                result = _run(["wpctl", "set-mute", sink, "1"])
            elif action == "unmute":
                result = _run(["wpctl", "set-mute", sink, "0"])
            else:
                result = None
            if result is not None and result.returncode == 0:
                return self._volume_reply(action)
        if _which("pamixer"):
            flags = {
                "up": [f"--increase={step}"],
                "down": [f"--decrease={step}"],
                "mute": ["--mute"],
                "unmute": ["--unmute"],
            }
            result = _run(["pamixer", *flags.get(action, [])])
            if result is not None and result.returncode == 0:
                return self._volume_reply(action)
        if _which("amixer"):
            sign = {"up": f"{step}%+", "down": f"{step}%-"}.get(action)
            if sign:
                result = _run(["amixer", "-D", "pulse", "sset", "Master", sign])
            elif action == "mute":
                result = _run(["amixer", "-D", "pulse", "sset", "Master", "mute"])
            elif action == "unmute":
                result = _run(["amixer", "-D", "pulse", "sset", "Master", "unmute"])
            else:
                result = None
            if result is not None and result.returncode == 0:
                return self._volume_reply(action)
        return False, "Не удалось изменить громкость: проверь wpctl, pamixer или amixer"

    def _volume_reply(self, action: str) -> tuple[bool, str]:
        if action == "mute":
            return True, "Звук выключен"
        if action == "unmute":
            return True, "Звук включён"
        percent = self._volume_percent()
        word = "Громче" if action == "up" else "Тише"
        return True, f"{word}, {percent} процентов" if percent is not None else word

    @staticmethod
    def _volume_percent() -> int | None:
        if _which("wpctl"):
            result = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
            if result and result.returncode == 0:
                for token in result.stdout.replace(":", " ").split():
                    try:
                        return round(float(token) * 100)
                    except ValueError:
                        continue
        if _which("pamixer"):
            result = _run(["pamixer", "--get-volume"])
            if result and result.stdout.strip().isdigit():
                return int(result.stdout.strip())
        return None

    # ------------------------------------------------------------------ окна
    def minimize_window(self) -> tuple[bool, str]:
        if self.compositor == "hyprland" and _which("hyprctl"):
            info = _run(["hyprctl", "activewindow", "-j"])
            address = ""
            if info and info.returncode == 0:
                try:
                    address = json.loads(info.stdout).get("address", "")
                except json.JSONDecodeError:
                    address = ""
            if not address:
                return False, "Нет активного окна"
            result = _run(
                ["hyprctl", "dispatch", "movetoworkspacesilent", f"special:minimized,address:{address}"]
            )
            if result and result.returncode == 0:
                return True, "Свернул окно"
        if self.compositor == "sway" and _which("swaymsg"):
            result = _run(["swaymsg", "-q", "move", "scratchpad"])
            if result and result.returncode == 0:
                return True, "Свернул окно"
        if self.compositor == "kde":
            if self._kwin_shortcut("Window Minimize"):
                return True, "Свернул окно"
        if self.compositor in {"x11", "wayland"} and not is_wayland() and _which("xdotool"):
            _run(["xdotool", "getactivewindow", "windowminimize"])
            return True, "Свернул окно"
        return False, "На этом рабочем столе не умею сворачивать окна"

    def minimize_all(self) -> tuple[bool, str]:
        if self.compositor == "hyprland" and _which("hyprctl"):
            _run(["hyprctl", "dispatch", "togglespecialworkspace", "desktop"])
            return True, "Открываю рабочий стол"
        if self.compositor == "kde" and self._kwin_shortcut("Show Desktop"):
            return True, "Открываю рабочий стол"
        if self.compositor == "sway" and _which("swaymsg"):
            result = _run(["swaymsg", "-q", "workspace", "__desktop__"])
            if result and result.returncode == 0:
                return True, "Открываю рабочий стол"
        if not is_wayland() and _which("xdotool"):
            _run(["xdotool", "key", "super+d"])
            return True, "Открываю рабочий стол"
        return False, "Не умею показывать рабочий стол на этом окружении"

    def close_window(self) -> tuple[bool, str]:
        if self.compositor == "hyprland" and _which("hyprctl"):
            _run(["hyprctl", "dispatch", "killactive"])
            return True, "Закрыл окно"
        if self.compositor == "sway" and _which("swaymsg"):
            result = _run(["swaymsg", "-q", "kill"])
            if result and result.returncode == 0:
                return True, "Закрыл окно"
        if self.compositor == "kde" and self._kwin_shortcut("Window Close"):
            return True, "Закрыл окно"
        if not is_wayland() and _which("xdotool"):
            _run(["xdotool", "getactivewindow", "windowclose"])
            return True, "Закрыл окно"
        return False, "Не умею закрывать окна на этом окружении"

    def switch_window(self) -> tuple[bool, str]:
        if self.compositor == "hyprland" and _which("hyprctl"):
            _run(["hyprctl", "dispatch", "cyclenext"])
            return True, "Переключаю окно"
        if self.compositor == "sway" and _which("swaymsg"):
            result = _run(["swaymsg", "-q", "focus", "next"])
            if result and result.returncode == 0:
                return True, "Переключаю окно"
        if self.compositor == "kde" and self._kwin_shortcut("Walk Through Windows"):
            return True, "Переключаю окно"
        if not is_wayland() and _which("xdotool"):
            _run(["xdotool", "key", "alt+Tab"])
            return True, "Переключаю окно"
        if _which("wtype"):
            _run(["wtype", "-M", "alt", "-k", "Tab", "-m", "alt"])
            return True, "Переключаю окно"
        return False, "Не умею переключать окна на этом окружении"

    def lock(self) -> tuple[bool, str]:
        if _which("loginctl"):
            result = _run(["loginctl", "lock-session"])
            if result and result.returncode == 0:
                return True, "Блокирую компьютер"
        if _which("hyprlock"):
            subprocess.Popen(["hyprlock"], start_new_session=True)
            return True, "Блокирую компьютер"
        if _which("swaylock"):
            subprocess.Popen(["swaylock"], start_new_session=True)
            return True, "Блокирую компьютер"
        if self._kwin_shortcut("Lock Session"):
            return True, "Блокирую компьютер"
        if _which("xdg-screensaver"):
            _run(["xdg-screensaver", "lock"])
            return True, "Блокирую компьютер"
        return False, "Не нашёл чем заблокировать сеанс"

    def close_process(self, name: str) -> tuple[bool, str]:
        name = name.strip()
        if len(name) < 2:
            return False, "Не понял, что закрывать"
        if "voicecode" in name.casefold():
            return False, "Себя я не закрою"
        if not _which("pkill"):
            return False, "Не установлен procps-ng (pkill)"
        result = _run(["pkill", "-f", "-i", "--", name])
        if result and result.returncode == 0:
            return True, f"Закрываю {name}"
        return False, f"{name} не запущен или не закрылся"

    def _kwin_shortcut(self, shortcut: str) -> bool:
        for binary in ("qdbus6", "qdbus"):
            if not _which(binary):
                continue
            result = _run(
                [binary, "org.kde.kglobalaccel", "/component/kwin", "invokeShortcut", shortcut],
                timeout=5,
            )
            if result and result.returncode == 0:
                return True
        return False

    # --------------------------------------------------------------- приложения
    def open_app(self, name: str) -> tuple[bool, str]:
        app = self.apps.find(name)
        if app is None:
            return False, f"Не нашёл приложение «{name}»"
        return self.apps.launch(app)

    def close_app(self, name: str) -> tuple[bool, str]:
        app = self.apps.close_by_name(name)
        if app is not None:
            return app
        return self.close_process(name)

    def capabilities(self) -> str:
        return (
            "Я открываю программы и сайты, ищу в интернете, делаю скриншоты, "
            "управляю громкостью и окнами, блокирую компьютер, подсказываю время и дату. "
            "А на вопросы отвечаю через opencode."
        )
