#!/usr/bin/env python3
"""Скачивает готовую faster-whisper модель в models/."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voicecode.paths import models_dir  # noqa: E402

REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Скачать модель faster-whisper")
    parser.add_argument("--size", default="small", choices=sorted(REPOS))
    parser.add_argument("--repo", help="свой репозиторий Hugging Face")
    parser.add_argument("--output", help="каталог назначения")
    args = parser.parse_args()

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("Нет huggingface_hub. Установи зависимости: pip install -r requirements.txt", file=sys.stderr)
        return 1

    repo = args.repo or REPOS[args.size]
    output = Path(args.output).expanduser() if args.output else models_dir() / f"faster-whisper-{args.size}"
    if output.exists() and any(output.iterdir()):
        print(f"Модель уже есть: {output}")
        return 0

    print(f"Скачиваю {repo} → {output}")
    output.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo,
        local_dir=str(output),
        local_dir_use_symlinks=False,
        ignore_patterns=["*.msgpack", "*.h5", "*.ot", "flax_model*", "tf_model*"],
    )
    required = [output / "config.json", output / "model.bin", output / "tokenizer.json"]
    missing = [path.name for path in required if not path.exists()]
    if missing:
        print(f"В модели нет файлов: {', '.join(missing)}", file=sys.stderr)
        return 1

    free = shutil.disk_usage(output).free
    print(f"Готово. Модель: {output} (свободно {free // 1024 ** 3} ГБ)")
    print(f'В config.json: "whisper_model": "{output}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
