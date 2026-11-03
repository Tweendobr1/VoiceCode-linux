"""Постоянно открытый микрофонный поток (PortAudio/sounddevice)."""

from __future__ import annotations

import logging
import threading

import numpy as np

from ..config import Config

log = logging.getLogger(__name__)


class Recorder:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._stream = None
        self._recording = False
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._level = 0.0
        self._device_index = None
        self._max_frames = int(cfg.sample_rate * max(1, int(cfg.max_record_sec)))

    # ------------------------------------------------------------------ setup
    def _resolve_device(self, sd) -> int | None:
        wanted = str(self.cfg.microphone or "").strip()
        if not wanted:
            return None
        devices = sd.query_devices()
        for index, device in enumerate(devices):
            if device.get("max_input_channels", 0) <= 0:
                continue
            if wanted.casefold() in str(device.get("name", "")).casefold():
                self._device_index = index
                return index
        names = ", ".join(
            d["name"] for d in devices if d.get("max_input_channels", 0) > 0
        )
        raise RuntimeError(
            f"Микрофон «{wanted}» не найден. Доступные устройства: {names or 'нет'}"
        )

    def open(self) -> None:
        import sounddevice as sd

        if self._stream is not None:
            return
        device = self._resolve_device(sd)
        try:
            stream = sd.InputStream(
                samplerate=int(self.cfg.sample_rate),
                channels=1,
                dtype="float32",
                blocksize=0,
                latency="low",
                device=device,
                callback=self._callback,
            )
            stream.start()
        except Exception as exc:
            raise RuntimeError(
                f"Микрофон недоступен: {exc}. Проверь устройства командой "
                "«python tools/warmup.py»."
            ) from exc
        self._stream = stream
        log.info("Микрофон открыт: %s", device if device is not None else "по умолчанию")

    # --------------------------------------------------------------- recording
    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        if status:
            log.debug("Аудиопоток: %s", status)
        with self._lock:
            active = self._recording
            if active:
                if sum(len(c) for c in self._chunks) < self._max_frames:
                    self._chunks.append(indata.copy())
                self._level = float(np.sqrt(np.mean(np.square(indata)))) if frames else 0.0
            else:
                self._level = 0.0

    def start(self) -> None:
        if self._stream is None:
            self.open()
        with self._lock:
            self._chunks = []
            self._recording = True
        log.debug("Запись начата")

    def stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False
            chunks, self._chunks = self._chunks, []
            self._level = 0.0
        if not chunks:
            return np.zeros(0, dtype="float32")
        log.debug("Запись остановлена: %.2f с", sum(len(c) for c in chunks) / self.cfg.sample_rate)
        return np.concatenate(chunks).reshape(-1).astype("float32", copy=False)

    @property
    def level(self) -> float:
        with self._lock:
            return min(1.0, self._level * 6.0)

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    def close(self) -> None:
        with self._lock:
            self._recording = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                log.debug("Ошибка при закрытии микрофона", exc_info=True)
            self._stream = None
