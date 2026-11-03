"""Вызов opencode CLI и разбор потока JSON-событий."""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Iterator

from .config import Config
from .paths import APP_DIR, DEFAULT_SYSTEM_PROMPT, agent_dir, resolve

log = logging.getLogger(__name__)

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_SKIP_TYPES = {
    "reasoning",
    "tool",
    "tool_use",
    "tool_result",
    "tool-use",
    "tool-result",
    "step-start",
    "step-finish",
    "step_start",
    "step_finish",
    "error",
    "snapshot",
    "patch",
    "file",
    "agent",
}


def extract_text(obj) -> str:
    """Достаёт текст из события opencode, игнорируя reasoning и инструменты."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return "".join(extract_text(item) for item in obj)
    if not isinstance(obj, dict):
        return ""

    kind = str(obj.get("type") or "").lower()
    if kind in _SKIP_TYPES:
        return ""
    if kind == "text":
        value = obj.get("text")
        if isinstance(value, str):
            return value

    for key in ("text", "delta"):
        value = obj.get(key)
        if isinstance(value, str):
            return value

    for key in ("part", "properties", "message"):
        if key in obj:
            found = extract_text(obj[key])
            if found:
                return found

    content = obj.get("content")
    if isinstance(content, (str, list)) and kind in {"", "content", "message"}:
        return extract_text(content)
    return ""


class TextAccumulator:
    """Склеивает дельты и полные снапшоты, отдавая только новый текст."""

    def __init__(self) -> None:
        self.text = ""

    def feed(self, candidate: str) -> str:
        candidate = _ANSI.sub("", candidate).replace("\r", "")
        if not candidate:
            return ""
        if candidate.startswith(self.text):
            delta = candidate[len(self.text) :]
            self.text = candidate
            return delta
        if self.text.endswith(candidate):
            return ""
        if len(candidate) > len(self.text) and self.text and self.text in candidate:
            index = candidate.find(self.text)
            delta = candidate[:index] + candidate[index + len(self.text) :]
            self.text = candidate
            return delta
        self.text += candidate
        return candidate


class OpenCodeClient:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.cli = self.find_cli(cfg.opencode_cli)
        workspace = str(cfg.workspace or "").strip()
        if workspace in {"", "agent"}:
            self.workspace = agent_dir()
        else:
            path = Path(workspace).expanduser()
            if not path.is_absolute() and not os.access(APP_DIR, os.W_OK):
                # В /opt/voicecode писать нельзя: относительный путь — от дома.
                self.workspace = (Path.home() / path).resolve()
            else:
                self.workspace = resolve(path, APP_DIR)
        self.workspace.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------- search
    @staticmethod
    def find_cli(configured: str = "") -> str | None:
        candidates: list[str] = []
        if configured:
            value = str(Path(configured).expanduser())
            candidates.append(value)
            found = shutil.which(value)
            if found:
                candidates.append(found)
        for name in ("opencode-cli", "opencode"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
        home = Path.home()
        candidates.extend(
            [
                str(home / ".opencode/bin/opencode"),
                str(home / ".local/bin/opencode"),
                str(home / ".local/bin/opencode-cli"),
                "/usr/local/bin/opencode",
                "/usr/bin/opencode",
                "/opt/opencode/opencode",
            ]
        )
        for candidate in candidates:
            if candidate and Path(candidate).expanduser().is_file():
                return str(Path(candidate).expanduser())
        return None

    def version(self) -> str:
        if not self.cli:
            return "не найден"
        try:
            out = subprocess.run(
                [self.cli, "--version"], capture_output=True, text=True, timeout=8
            )
            return (out.stdout or out.stderr).strip().splitlines()[0] or "?"
        except (OSError, subprocess.SubprocessError, IndexError):
            return "?"

    # ------------------------------------------------------------------- prompt
    def build_prompt(self, question: str, history: list[tuple[str, str]]) -> str:
        if not self.cfg.keep_context or not history:
            return f"{DEFAULT_SYSTEM_PROMPT}\n\n{question}"
        lines = [DEFAULT_SYSTEM_PROMPT, "", "История разговора:"]
        for asked, answered in history[-int(self.cfg.max_context_turns) :]:
            lines.append(f"Пользователь: {asked}")
            lines.append(f"Ты: {answered}")
        lines.append("")
        lines.append(f"Новый вопрос: {question}")
        return "\n".join(lines)

    # ------------------------------------------------------------------- stream
    def stream(self, prompt: str, cancel: threading.Event) -> Iterator[str]:
        if not self.cli:
            raise RuntimeError(
                "Не нашёл opencode. Установи opencode или укажи путь в opencode_cli."
            )

        for attempt in (0, 1):
            if cancel.is_set():
                return
            produced = False
            stderr_lines: deque[str] = deque(maxlen=60)
            proc = self._spawn(prompt, with_json=attempt == 0)
            reader = threading.Thread(
                target=self._read_stderr, args=(proc, stderr_lines), daemon=True
            )
            reader.start()

            deadline = time.monotonic() + float(self.cfg.timeout_sec)
            accumulator = TextAccumulator()
            try:
                yield from self._read_stdout(proc, accumulator, cancel, deadline)
            except TimeoutError as exc:
                raise RuntimeError("opencode не ответил за отведённое время") from exc
            finally:
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self._terminate(proc)
                reader.join(timeout=1)
                if proc.stderr is not None:
                    try:
                        proc.stderr.close()
                    except (OSError, ValueError):
                        pass

            stderr_text = "\n".join(stderr_lines)
            produced = bool(accumulator.text.strip())
            if cancel.is_set():
                return
            if not produced and proc.returncode not in (0, None):
                if attempt == 0 and self._looks_like_bad_option(stderr_text):
                    log.warning("opencode не понял --format json, повторяю без него")
                    continue
                message = stderr_text.strip().splitlines()
                raise RuntimeError(
                    "opencode завершился с ошибкой"
                    + (f": {message[-1]}" if message else "")
                )
            if not produced and stderr_text.strip():
                raise RuntimeError(f"opencode: {stderr_text.strip().splitlines()[-1]}")
            return

    def _spawn(self, prompt: str, with_json: bool) -> subprocess.Popen:
        cmd = [self.cli, "run"]
        if with_json:
            cmd += ["--format", "json"]
        cmd += ["--model", str(self.cfg.model), "--agent", str(self.cfg.agent)]
        if self.cfg.auto_approve:
            cmd.append("--auto")
        cmd.append(prompt)

        env = os.environ.copy()
        env.update({"TERM": "dumb", "NO_COLOR": "1", "CI": "1"})
        log.debug("opencode: %s", " ".join(cmd[:-1]))
        return subprocess.Popen(
            cmd,
            cwd=str(self.workspace),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

    def _read_stdout(
        self,
        proc: subprocess.Popen,
        accumulator: TextAccumulator,
        cancel: threading.Event,
        deadline: float,
    ) -> Iterator[str]:
        assert proc.stdout is not None
        lines: queue.Queue[str | None] = queue.Queue()

        def reader() -> None:
            try:
                for line in proc.stdout:
                    lines.put(line)
            except (OSError, ValueError):
                pass
            finally:
                lines.put(None)

        thread = threading.Thread(target=reader, name="opencode-stdout", daemon=True)
        thread.start()
        finished = False
        try:
            while True:
                if cancel.is_set():
                    self._terminate(proc)
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._terminate(proc)
                    raise TimeoutError("opencode timeout")
                try:
                    line = lines.get(timeout=min(0.2, remaining))
                except queue.Empty:
                    continue
                if line is None:
                    finished = True
                    break
                delta = self._parse_line(line, accumulator)
                if delta:
                    yield delta
        finally:
            if not finished:
                self._terminate(proc)
            thread.join(timeout=1)
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._terminate(proc)
            if proc.stdout is not None:
                try:
                    proc.stdout.close()
                except (OSError, ValueError):
                    pass

    @staticmethod
    def _parse_line(line: str, accumulator: TextAccumulator) -> str:
        stripped = _ANSI.sub("", line).strip()
        if not stripped:
            return ""
        if stripped.startswith("{"):
            try:
                candidate = extract_text(json.loads(stripped))
            except json.JSONDecodeError:
                candidate = stripped + "\n"
        else:
            # В обычном (не JSON) режиме строка — это кусок ответа,
            # поэтому сохраняем перевод строки между кусками.
            candidate = stripped + "\n"
        return accumulator.feed(candidate)

    @staticmethod
    def _read_stderr(proc: subprocess.Popen, sink: deque[str]) -> None:
        if proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                sink.append(line.rstrip())
        except (OSError, ValueError):
            pass

    @staticmethod
    def _looks_like_bad_option(stderr: str) -> bool:
        text = stderr.lower()
        return any(
            marker in text
            for marker in ("unknown option", "unexpected argument", "invalid value", "--format")
        )

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            proc.kill()
        except OSError:
            pass
