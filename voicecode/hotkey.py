"""Глобальный push-to-talk хоткей: evdev (Wayland/X11) или pynput (X11)."""

from __future__ import annotations

import logging
import os
import select
import threading

from .config import Config

log = logging.getLogger(__name__)


def _evdev_keycode(name: str):
    from evdev import ecodes

    key = name.strip().lower().replace(" ", "")
    attribute = "KEY_" + key.upper()
    return getattr(ecodes, attribute, None)


class HotkeyListener:
    def __init__(self, cfg: Config, on_press, on_release) -> None:
        self.cfg = cfg
        self.on_press = on_press
        self.on_release = on_release
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._devices = []
        self._listener = None
        self._pressed = False

    def start(self) -> str:
        """Возвращает описание бэкенда или текст ошибки."""
        name = str(self.cfg.global_hotkey or "f8")
        if not name:
            return "глобальный хоткей отключён"
        try:
            code = _evdev_keycode(name)
        except ImportError:
            code = None
        if code is not None:
            error = self._start_evdev(code)
            if error is None:
                return f"evdev ({name})"
            log.warning("evdev недоступен: %s", error)
            evdev_error = error
        else:
            evdev_error = "неизвестная клавиша"

        if not self._is_wayland():
            error = self._start_pynput(name)
            if error is None:
                return f"pynput ({name})"
            log.warning("pynput недоступен: %s", error)
            return f"хоткей не работает: {evdev_error}; {error}"
        return (
            f"хоткей не работает: {evdev_error}. Добавь пользователя в группу input "
            "(sudo usermod -aG input $USER) и перезайди."
        )

    @staticmethod
    def _is_wayland() -> bool:
        return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(
            os.environ.get("WAYLAND_DISPLAY")
        )

    # ------------------------------------------------------------------- evdev
    def _start_evdev(self, code) -> str | None:
        import evdev
        from evdev import InputDevice, ecodes

        devices = []
        denied = 0
        for path in evdev.list_devices():
            try:
                device = InputDevice(path)
            except PermissionError:
                denied += 1
                continue
            except OSError:
                continue
            keys = device.capabilities().get(ecodes.EV_KEY, [])
            if code in keys:
                try:
                    if self.cfg.hotkey_grab:
                        device.grab()
                except OSError:
                    log.debug("Не удалось захватить %s", device.path)
                devices.append(device)
            else:
                device.close()

        if not devices:
            if denied:
                return "нет доступа к /dev/input (нужна группа input)"
            return f"клавиша {self.cfg.global_hotkey} не найдена на устройствах ввода"

        self._devices = devices
        log.info("Слушаю %s через evdev: %s", self.cfg.global_hotkey, [d.path for d in devices])
        self._thread = threading.Thread(target=self._evdev_loop, args=(code,), daemon=True)
        self._thread.start()
        return None

    def _evdev_loop(self, code) -> None:
        from evdev import ecodes

        devices = list(self._devices)
        while not self._stop.is_set() and devices:
            try:
                readable, _, _ = select.select(devices, [], [], 0.3)
            except (OSError, ValueError):
                break
            for device in readable:
                try:
                    events = device.read()
                except OSError:
                    devices.remove(device)
                    continue
                for event in events:
                    if event.type != ecodes.EV_KEY or event.code != code:
                        continue
                    if event.value == 1 and not self._pressed:
                        self._pressed = True
                        self._safe(self.on_press)
                    elif event.value == 0 and self._pressed:
                        self._pressed = False
                        self._safe(self.on_release)

    # ------------------------------------------------------------------ pynput
    def _start_pynput(self, name: str) -> str | None:
        try:
            from pynput import keyboard
        except Exception as exc:  # pragma: no cover - зависит от окружения
            return f"pynput не загрузился: {exc}"
        key = getattr(keyboard.Key, name.strip().lower(), None)
        if key is None:
            return f"pynput не знает клавишу {name}"

        def on_press(pressed) -> None:
            if pressed == key and not self._pressed:
                self._pressed = True
                self._safe(self.on_press)

        def on_release(released) -> None:
            if released == key and self._pressed:
                self._pressed = False
                self._safe(self.on_release)

        try:
            self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._listener.start()
        except Exception as exc:  # pragma: no cover
            return f"pynput не запустился: {exc}"
        return None

    # ------------------------------------------------------------------ service
    @staticmethod
    def _safe(callback) -> None:
        try:
            callback()
        except Exception:
            log.exception("Ошибка обработчика хоткея")

    def stop(self) -> None:
        self._stop.set()
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
        for device in self._devices:
            try:
                if self.cfg.hotkey_grab:
                    device.ungrab()
            except OSError:
                pass
            try:
                device.close()
            except OSError:
                pass
        self._devices = []
