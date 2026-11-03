"""Индекс .desktop-файлов, запуск приложений и сайты."""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .paths import DATA_HOME

log = logging.getLogger(__name__)

_APPS_DIRS = [
    DATA_HOME / "applications",
    Path.home() / ".local/share/flatpak/exports/share/applications",
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
]
for _dir in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
    if _dir:
        _APPS_DIRS.append(Path(_dir) / "applications")

_BAD_CHARS = re.compile(r"[^\w\s.]+", re.UNICODE)
_DOTS = re.compile(r"\s*\.\s*")
_GENERIC_EXEC = {
    "sh",
    "bash",
    "env",
    "python",
    "python3",
    "flatpak",
    "gtk-launch",
    "gio",
    "wine",
}


def normalize(text: str) -> str:
    text = text.casefold().replace("ё", "е")
    text = _DOTS.sub(".", _BAD_CHARS.sub(" ", text))
    return " ".join(text.split()).strip(" .")


@dataclass
class DesktopApp:
    id: str
    name: str
    name_ru: str
    exec: str
    path: Path
    keywords: list[str] = field(default_factory=list)
    terminal: bool = False

    @property
    def title(self) -> str:
        return self.name_ru or self.name

    def haystack(self) -> list[str]:
        values = [
            self.name,
            self.name_ru,
            self.id.replace(".desktop", ""),
            *self.keywords,
        ]
        return [normalize(value) for value in values if value]


SITES: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "ютуб": "https://www.youtube.com",
    "youtu.be": "https://www.youtube.com",
    "github": "https://github.com",
    "гитхаб": "https://github.com",
    "google": "https://www.google.com",
    "гугл": "https://www.google.com",
    "yandex": "https://yandex.ru",
    "яндекс": "https://yandex.ru",
    "vk": "https://vk.com",
    "вконтакте": "https://vk.com",
    "вк": "https://vk.com",
    "telegram web": "https://web.telegram.org",
    "телеграм веб": "https://web.telegram.org",
    "wikipedia": "https://ru.wikipedia.org",
    "википедия": "https://ru.wikipedia.org",
    "хабр": "https://habr.com",
    "habr": "https://habr.com",
    "reddit": "https://www.reddit.com",
    "редит": "https://www.reddit.com",
    "кинопоиск": "https://www.kinopoisk.ru",
    "ozon": "https://www.ozon.ru",
    "озон": "https://www.ozon.ru",
    "wildberries": "https://www.wildberries.ru",
    "вайлдберриз": "https://www.wildberries.ru",
    "mail": "https://mail.google.com",
    "почта": "https://mail.google.com",
    "maps": "https://yandex.ru/maps",
    "карты": "https://yandex.ru/maps",
    "openai": "https://chat.openai.com",
    "opencode": "https://opencode.ai",
    "stackoverflow": "https://stackoverflow.com",
    "стековерфлоу": "https://stackoverflow.com",
    "пикабу": "https://pikabu.ru",
    "pikabu": "https://pikabu.ru",
}

# Русские названия → вероятные имена .desktop-файлов.
APP_ALIASES: dict[str, list[str]] = {
    "телеграм": ["telegram", "telegramdesktop", "org.telegram.desktop"],
    "телеграмм": ["telegram", "telegramdesktop", "org.telegram.desktop"],
    "калькулятор": ["calculator", "qalculate", "kcalc", "gnome-calculator"],
    "блокнот": ["kate", "gedit", "gnome-text-editor", "mousepad", "featherpad"],
    "текстовый редактор": ["kate", "gedit", "code", "codium"],
    "терминал": ["konsole", "alacritty", "kitty", "foot", "gnome-terminal", "xterm"],
    "консоль": ["konsole", "alacritty", "kitty", "foot", "gnome-terminal"],
    "файлы": ["dolphin", "nautilus", "thunar", "pcmanfm"],
    "проводник": ["dolphin", "nautilus", "thunar"],
    "настройки": ["systemsettings", "gnome-control-center", "xfce-settings"],
    "параметры": ["systemsettings", "gnome-control-center"],
    "браузер": ["firefox", "chromium", "google-chrome", "brave"],
    "хром": ["google-chrome", "chromium", "brave"],
    "фаерфокс": ["firefox"],
    "код": ["code", "codium", "code-oss"],
    "редактор кода": ["code", "codium", "code-oss"],
    "стим": ["steam"],
    "steam": ["steam"],
    "дискорд": ["discord"],
    "дискорд каннари": ["discord-canary"],
    "обсидиан": ["obsidian"],
    "спотифай": ["spotify"],
    "музыка": ["spotify", "elisa", "rhythmbox", "vlc"],
    "видео": ["vlc", "mpv"],
    "плеер": ["vlc", "mpv", "elisa"],
    "скриншот": ["flameshot", "spectacle"],
    "почта": ["thunderbird", "evolution"],
    "офис": ["libreoffice", "onlyoffice"],
    "ворд": ["libreoffice-writer", "onlyoffice-desktopeditors"],
    "эксель": ["libreoffice-calc", "onlyoffice-desktopeditors"],
    "телеграм десктоп": ["telegram", "telegramdesktop"],
    "файловый менеджер": ["dolphin", "nautilus", "thunar"],
    "монитор": ["systemmonitor", "plasma-systemmonitor", "gnome-system-monitor"],
    "зум": ["zoom"],
    "скайп": ["skype"],
    "слак": ["slack"],
    "опера": ["opera"],
    "тор": ["torbrowser", "tor-browser"],
    "гимп": ["gimp"],
    "инкскейп": ["inkscape"],
    "блендер": ["blender"],
}


class AppIndex:
    def __init__(self) -> None:
        self._apps: dict[str, DesktopApp] = {}
        self._loaded = False

    def load(self, force: bool = False) -> None:
        if self._loaded and not force:
            return
        apps: dict[str, DesktopApp] = {}
        seen_paths: set[Path] = set()
        for directory in _APPS_DIRS:
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.desktop")):
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                app = self._parse(path, directory)
                if app is not None:
                    apps.setdefault(app.id, app)
        self._apps = apps
        self._loaded = True
        log.info("Проиндексировано приложений: %d", len(apps))

    @staticmethod
    def _parse(path: Path, directory: Path) -> DesktopApp | None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        section = ""
        data: dict[str, str] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue
            if section != "Desktop Entry" or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
        if data.get("Type", "Application") != "Application":
            return None
        if data.get("NoDisplay", "").lower() == "true" or data.get("Hidden", "").lower() == "true":
            return None
        name = data.get("Name", "").strip()
        exec_value = data.get("Exec", "").strip()
        if not name or not exec_value:
            return None
        try:
            relative = path.relative_to(directory).as_posix()
        except ValueError:
            relative = path.name
        app_id = relative.replace("/", "-")
        name_ru = data.get("Name[ru]", "").strip()
        if not name_ru:
            for key, value in data.items():
                if key.startswith("Name[ru_") and value.strip():
                    name_ru = value.strip()
                    break
        return DesktopApp(
            id=app_id,
            name=name,
            name_ru=name_ru,
            exec=exec_value,
            path=path,
            keywords=[k.strip() for k in data.get("Keywords", "").split(";") if k.strip()],
            terminal=data.get("Terminal", "").lower() == "true",
        )

    def find(self, query: str) -> DesktopApp | None:
        self.load()
        normalized = normalize(query)
        if not normalized:
            return None

        # Сначала русские псевдонимы: «телеграм» → telegram.
        alias_candidates: list[str] = []
        for alias, targets in APP_ALIASES.items():
            if normalized == alias or normalized in alias or alias in normalized:
                alias_candidates.extend(normalize(target) for target in targets)
        if alias_candidates:
            best_alias = self._best(alias_candidates, minimum=40)
            if best_alias is not None:
                return best_alias

        return self._best([normalized], minimum=58)

    def _best(self, queries: list[str], minimum: float) -> DesktopApp | None:
        best: tuple[float, DesktopApp] | None = None
        for app in self._apps.values():
            for query in queries:
                score = self._score(app, query)
                if best is None or score > best[0]:
                    best = (score, app)
        if best is not None and best[0] >= minimum:
            log.debug("Приложение «%s» → %s (%.0f)", queries, best[1].id, best[0])
            return best[1]
        return None

    @staticmethod
    def _score(app: DesktopApp, query: str) -> float:
        best = 0.0
        for name in app.haystack():
            if not name:
                continue
            if name == query:
                score = 100.0
            elif name.startswith(query) or query.startswith(name):
                score = 86.0
            elif query in name:
                score = max(60.0, 80.0 - (len(name) - len(query)))
            elif name in query and len(name) >= 3:
                score = 66.0
            else:
                score = SequenceMatcher(None, query, name).ratio() * 64.0
            best = max(best, score)
        return best

    # ------------------------------------------------------------------ launch
    def launch(self, app: DesktopApp) -> tuple[bool, str]:
        if shutil.which("gtk-launch"):
            result = subprocess.run(
                ["gtk-launch", app.id], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return True, f"Открываю {app.title}"

        if shutil.which("gio"):
            result = subprocess.run(
                ["gio", "launch", str(app.path)], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return True, f"Открываю {app.title}"

        try:
            command = self._exec_command(app)
            subprocess.Popen(
                command,
                cwd=str(Path.home()),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as exc:
            log.exception("Не удалось запустить %s", app.id)
            return False, f"Не получилось открыть {app.title}: {exc}"
        return True, f"Открываю {app.title}"

    @staticmethod
    def _exec_command(app: DesktopApp) -> list[str]:
        raw = re.sub(r"%[fFuUdDnNickvm]", "", app.exec)
        args = shlex.split(raw)
        if not args:
            raise RuntimeError("пустая команда запуска")
        if app.terminal:
            terminal = None
            for candidate in (
                ("konsole", "-e"),
                ("alacritty", "-e"),
                ("kitty", "--"),
                ("foot", "--"),
                ("gnome-terminal", "--"),
                ("xterm", "-e"),
            ):
                if shutil.which(candidate[0]):
                    terminal = candidate
                    break
            if terminal:
                args = [terminal[0], *terminal[1:], *args]
        return args

    def close_by_name(self, query: str) -> tuple[bool, str] | None:
        """Закрывает приложение по имени, включая русские псевдонимы."""
        app = self.find(query)
        if app is not None:
            return self.close(app)
        if not shutil.which("pkill"):
            return None
        normalized = normalize(query)
        for alias, targets in APP_ALIASES.items():
            alias_norm = normalize(alias)
            if normalized != alias_norm and alias_norm not in normalized:
                continue
            for target in targets:
                if "." in target or len(target) < 3 or target in _GENERIC_EXEC:
                    continue
                result = subprocess.run(
                    ["pkill", "-f", "-i", "--", target], capture_output=True, timeout=10
                )
                if result.returncode == 0:
                    return True, f"Закрываю {query}"
        return None

    def close(self, app: DesktopApp) -> tuple[bool, str]:
        exec_value = app.exec
        flatpak = re.search(r"flatpak\s+run\s+([\w.\-]+)", exec_value)
        if flatpak:
            result = subprocess.run(
                ["flatpak", "kill", flatpak.group(1)], capture_output=True, timeout=10
            )
            if result.returncode == 0:
                return True, f"Закрываю {app.title}"
            return False, f"{app.title} не запущен или не закрылся"

        try:
            pattern = self._exec_program(exec_value)
        except ValueError:
            return False, "Не понял, что закрывать"
        if not pattern or len(pattern) < 3 or pattern in _GENERIC_EXEC:
            return False, f"Не понял, как закрыть {app.title}"
        if "voicecode" in pattern.casefold():
            return False, "Себя я не закрою"
        result = subprocess.run(
            ["pkill", "-f", "-i", "--", pattern], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True, f"Закрываю {app.title}"
        return False, f"{app.title} не запущен или не закрылся"

    @staticmethod
    def _exec_program(exec_value: str) -> str:
        raw = re.sub(r"%[fFuUdDnNickvm]", "", exec_value)
        args = shlex.split(raw)
        while args and "=" in args[0] and not args[0].startswith("/"):
            args.pop(0)
        if args and Path(args[0]).name == "env":
            args.pop(0)
            while args and "=" in args[0]:
                args.pop(0)
        if not args:
            raise ValueError("пустая команда")
        return Path(args[0]).name

    def __len__(self) -> int:
        self.load()
        return len(self._apps)


def find_site(query: str) -> tuple[str, str] | None:
    """Ищет сайт по русскому или английскому названию/домену."""
    normalized = normalize(query)
    for alias, url in SITES.items():
        alias_norm = normalize(alias)
        if len(alias_norm) <= 3:
            # «вк» не должно срабатывать внутри слова «вкладка».
            words = normalized.split()
            if normalized != alias_norm and alias_norm not in words:
                continue
        elif not (
            normalized == alias_norm
            or normalized.startswith(alias_norm + " ")
            or alias_norm in normalized
        ):
            continue
        return alias, url
    domain = query.strip()
    if re.fullmatch(r"[\w\-]+(\.[\w\-]+)+(/\S*)?", domain):
        return domain, domain if domain.startswith("http") else f"https://{domain}"
    return None
