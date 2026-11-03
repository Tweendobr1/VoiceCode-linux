"""Распознавание речи через faster-whisper."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from .config import Config
from .paths import APP_DIR, USER_MODELS_DIR, models_dir

log = logging.getLogger(__name__)


class Transcriber:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.model = None
        self._lock = threading.Lock()
        self._model_name = self._resolve_model(cfg.whisper_model)

    @staticmethod
    def _resolve_model(raw: str) -> str:
        path = Path(raw).expanduser()
        candidates = [path] if path.is_absolute() else [APP_DIR / path, USER_MODELS_DIR / path.name]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        name = Path(raw).name
        if "faster-whisper-" in name:
            # «models/faster-whisper-small» → «small»: скачаем с Hugging Face.
            return name.split("faster-whisper-")[-1]
        return raw

    @property
    def model_name(self) -> str:
        return self._model_name

    def load(self) -> None:
        from faster_whisper import WhisperModel

        log.info(
            "Загружаю Whisper: %s (%s, потоков: %s)",
            self._model_name,
            self.cfg.whisper_compute,
            self.cfg.resolved_threads(),
        )
        download_root = models_dir()
        download_root.mkdir(parents=True, exist_ok=True)
        try:
            self.model = WhisperModel(
                self._model_name,
                device="cpu",
                compute_type=self.cfg.whisper_compute,
                cpu_threads=self.cfg.resolved_threads(),
                download_root=str(download_root),
            )
        except Exception as exc:
            if self._model_name != self.cfg.whisper_model:
                raise RuntimeError(f"Не удалось загрузить модель Whisper: {exc}") from exc
            # Локальной папки нет — пробуем скачать одноимённую модель с Hugging Face.
            fallback = Path(self.cfg.whisper_model).name.split("faster-whisper-")[-1]
            log.warning("Локальная модель не найдена, пробую «%s» с Hugging Face", fallback)
            self.model = WhisperModel(
                fallback,
                device="cpu",
                compute_type=self.cfg.whisper_compute,
                cpu_threads=self.cfg.resolved_threads(),
                download_root=str(download_root),
            )
            self._model_name = fallback
        log.info("Whisper загружен")

    def warmup(self) -> None:
        import numpy as np

        if self.model is None:
            self.load()
        self.transcribe(np.zeros(8000, dtype="float32"))
        log.info("Whisper прогрет")

    def transcribe(self, audio) -> str:
        if self.model is None:
            raise RuntimeError("Модель Whisper ещё не загружена")
        language = None if str(self.cfg.language).lower() == "auto" else self.cfg.language
        with self._lock:
            segments, _info = self.model.transcribe(
                audio,
                language=language,
                beam_size=1,
                best_of=1,
                temperature=0.0,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
                condition_on_previous_text=False,
                without_timestamps=True,
            )
            text = " ".join(segment.text.strip() for segment in segments)
        return " ".join(text.split()).strip()
