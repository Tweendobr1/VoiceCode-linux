"""Озвучка: edge-tts с потоковой очередью и офлайн-фолбэк."""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import re
import shutil
import socket
import subprocess
import tempfile
import threading
from pathlib import Path

from ..config import Config
from ..paths import CACHE_DIR

log = logging.getLogger(__name__)

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MD_MARKS = re.compile(r"[*_#>~|]+")
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\uFE0F]"
)
_SPACES = re.compile(r"\s+")


def clean_for_speech(text: str) -> str:
    """Убирает markdown, код и ссылки — всё, что плохо читается вслух."""
    text = _CODE_FENCE.sub(" … ", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub(" ссылка ", text)
    text = _MD_MARKS.sub(" ", text)
    text = _EMOJI.sub("", text)
    text = text.replace("\r", " ").replace("\n", " ")
    return _SPACES.sub(" ", text).strip()


def split_sentences(text: str, limit: int = 180) -> list[str]:
    """Режет текст на фразы, которые можно ставить в очередь озвучки."""
    cleaned = clean_for_speech(text)
    if not cleaned:
        return []
    parts = [p.strip() for p in _SENTENCE_END.split(cleaned) if p.strip()]
    result: list[str] = []
    for part in parts:
        while len(part) > limit:
            cut = max(part.rfind(",", 0, limit), part.rfind(";", 0, limit))
            if cut < limit // 2:
                cut = part.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            result.append(part[: cut + 1].strip())
            part = part[cut + 1 :].strip()
        if part:
            result.append(part)
    return result


def _rate_factor(value: str) -> float:
    match = re.search(r"([+-]?\d+)", str(value or ""))
    if not match:
        return 1.0
    return max(0.5, min(2.0, 1.0 + int(match.group(1)) / 100.0))


def edge_reachable(timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection(("speech.platform.bing.com", 443), timeout):
            return True
    except OSError:
        return False


class Speaker:
    """Очередь фраз; фразы синтезируются и проигрываются по одной."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.engine = str(cfg.tts_engine or "edge").lower()
        if self.engine not in {"edge", "system"}:
            self.engine = "edge"
        self.system_engine = str(cfg.system_tts or "auto").lower()
        self._generation = 0
        self._gen_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, int] = {}
        self._queue: queue.Queue[tuple[int, str]] = queue.Queue()
        self._idle = threading.Event()
        self._idle.set()
        self._proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()
        self._player = self._find_player()
        self._thread = threading.Thread(target=self._worker, name="speaker", daemon=True)
        self._thread.start()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ public
    def prepare(self) -> str:
        """Проверяет доступность движков. Возвращает описание выбранного."""
        if self.engine == "edge" and Path(self._player).name == "paplay":
            try:
                self._system_engine()
            except RuntimeError:
                log.warning(
                    "paplay не умеет mp3: установи ffmpeg или mpv, иначе ответы не зазвучат"
                )
            else:
                log.warning("paplay не умеет mp3, переключаюсь на локальный синтез")
                self.engine = "system"
        if self.engine == "edge" and self.cfg.edge_check and not edge_reachable():
            log.warning("edge-tts недоступен, переключаюсь на локальный синтез")
            self.engine = "system"
        if self.engine == "system":
            name = self._system_engine()
            log.info("Системный синтез: %s", name)
            return name
        log.info("edge-tts, голос %s", self.cfg.voice)
        return f"edge-tts ({self.cfg.voice})"

    def enqueue(self, text: str) -> None:
        cleaned = clean_for_speech(text)
        if not cleaned:
            return
        with self._gen_lock:
            generation = self._generation
        sentences = split_sentences(cleaned)
        if not sentences:
            return
        with self._pending_lock:
            self._pending[generation] = self._pending.get(generation, 0) + len(sentences)
            self._idle.clear()
            for sentence in sentences:
                self._queue.put((generation, sentence))

    def stop(self) -> None:
        with self._gen_lock:
            self._generation += 1
        with self._pending_lock:
            while True:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    break
            self._pending.clear()
            self._idle.set()
        self._kill_current()

    def wait(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout)

    @property
    def busy(self) -> bool:
        return not self._idle.is_set()

    def say_blocking(self, text: str, timeout: float = 60.0) -> None:
        self.enqueue(text)
        self.wait(timeout)

    def close(self) -> None:
        self.stop()
        self._queue.put((-1, ""))
        self._thread.join(timeout=3)

    # ------------------------------------------------------------------ worker
    def _worker(self) -> None:
        while True:
            generation, text = self._queue.get()
            if generation == -1:
                self._queue.task_done()
                return
            try:
                if generation == self._current_generation():
                    self._speak(text, generation)
            except Exception:
                log.exception("Ошибка озвучки: %s", text[:80])
                if self.engine == "edge":
                    self.engine = "system"
                    try:
                        self._speak(text, generation)
                    except Exception:
                        log.exception("Локальная озвучка тоже не удалась")
            finally:
                self._queue.task_done()
                with self._pending_lock:
                    count = self._pending.get(generation, 0)
                    if count > 1:
                        self._pending[generation] = count - 1
                    else:
                        self._pending.pop(generation, None)
                    if self._generation not in self._pending:
                        self._idle.set()

    def _current_generation(self) -> int:
        with self._gen_lock:
            return self._generation

    def _speak(self, text: str, generation: int) -> None:
        suffix = ".mp3" if self.engine == "edge" else ".wav"
        fd, raw_path = tempfile.mkstemp(prefix="voicecode-", suffix=suffix, dir=str(CACHE_DIR))
        os.close(fd)
        path = Path(raw_path)
        try:
            if self.engine == "edge":
                asyncio.run(asyncio.wait_for(self._edge_save(text, path), timeout=30))
            else:
                self._system_save(text, path)
            if generation != self._current_generation():
                return
            self._play(path, generation)
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    # -------------------------------------------------------------------- edge
    async def _edge_save(self, text: str, path: Path) -> None:
        import edge_tts

        communicate = edge_tts.Communicate(
            text=text,
            voice=self.cfg.voice,
            rate=self.cfg.tts_rate,
            volume=self.cfg.tts_volume,
        )
        await communicate.save(str(path))
        if path.stat().st_size < 512:
            raise RuntimeError("edge-tts вернул пустой файл")

    # ------------------------------------------------------------------ offline
    def _system_engine(self) -> str:
        choice = self.system_engine
        if choice in {"piper", "auto"}:
            model = str(self.cfg.piper_model or "").strip()
            if model and Path(model).expanduser().exists() and shutil.which("piper"):
                return "piper"
            if choice == "piper":
                raise RuntimeError("piper не найден: укажи piper_model и установи piper-tts")
        if shutil.which("espeak-ng") or shutil.which("espeak"):
            return "espeak"
        raise RuntimeError(
            "Нет локального синтеза: установи espeak-ng (pacman -S espeak-ng) "
            "или piper-tts и укажи piper_model"
        )

    def _system_save(self, text: str, path: Path) -> None:
        engine = self._system_engine()
        if engine == "piper":
            model = str(Path(self.cfg.piper_model).expanduser())
            subprocess.run(
                ["piper", "--model", model, "--output_file", str(path)],
                input=text.encode("utf-8"),
                check=True,
                timeout=60,
                capture_output=True,
            )
            return
        binary = shutil.which("espeak-ng") or shutil.which("espeak")
        speed = int(175 * _rate_factor(self.cfg.tts_rate))
        subprocess.run(
            [binary, "-v", "ru", "-s", str(speed), "-w", str(path), text],
            check=True,
            timeout=60,
            capture_output=True,
        )

    # -------------------------------------------------------------------- play
    @staticmethod
    def _find_player() -> str:
        for name in ("ffplay", "mpv", "paplay"):
            binary = shutil.which(name)
            if binary:
                return binary
        raise RuntimeError("Нет аудиоплеера: установи ffmpeg (ffplay) или mpv")

    def _play(self, path: Path, generation: int) -> None:
        if self._player.endswith("paplay"):
            if path.suffix != ".wav":
                raise RuntimeError("paplay не воспроизводит mp3")
            cmd = [self._player, str(path)]
        elif self._player.endswith("mpv"):
            cmd = [self._player, "--no-video", "--really-quiet", str(path)]
        else:
            cmd = [self._player, "-nodisp", "-autoexit", "-loglevel", "error", "-i", str(path)]
        if generation != self._current_generation():
            return
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        with self._proc_lock:
            self._proc = proc
        try:
            if generation != self._current_generation():
                proc.terminate()
            proc.wait()
        finally:
            with self._proc_lock:
                if self._proc is proc:
                    self._proc = None

    def _kill_current(self) -> None:
        with self._proc_lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
        except OSError:
            pass
