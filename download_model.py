"""Helper script to download and unpack the Russian Vosk speech recognition model."""

import io
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

from config import config

MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
MODEL_ARCHIVE_NAME = "vosk-model-small-ru-0.22"


def is_model_valid(model_path: Path) -> bool:
    """Checks if the directory contains required Vosk model files."""
    if not model_path.is_dir():
        return False
    # Check for core Vosk model indicators
    indicators = ["am", "conf", "graph", "ivector"]
    existing = [name for name in indicators if (model_path / name).exists()]
    return len(existing) >= 2


def download_progress_hook(block_num: int, block_size: int, total_size: int):
    downloaded = block_num * block_size
    if total_size > 0:
        percent = min(100.0, downloaded * 100.0 / total_size)
        mb_down = downloaded / (1024 * 1024)
        mb_total = total_size / (1024 * 1024)
        sys.stdout.write(f"\r⏳ Загрузка модели: {percent:.1f}% ({mb_down:.1f} / {mb_total:.1f} МБ)")
        sys.stdout.flush()


def download_and_extract_model(target_dir: Path = None) -> bool:
    target_dir = target_dir or config.vosk_model_path

    if is_model_valid(target_dir):
        print(f"✅ Модель Vosk уже установлена: {target_dir}")
        return True

    print(f"📦 Локальная модель Vosk не найдена в {target_dir}.")
    print(f"🌐 Скачиваем русскую легковесную модель с {MODEL_URL} (~45 МБ)...")

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_zip = target_dir.parent / "vosk_model_temp.zip"
    temp_extract = target_dir.parent / "vosk_temp_extract"

    try:
        urllib.request.urlretrieve(MODEL_URL, temp_zip, reporthook=download_progress_hook)
        print("\n📂 Распаковка архива...")

        if temp_extract.exists():
            shutil.rmtree(temp_extract)
        temp_extract.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(temp_zip, "r") as zip_ref:
            zip_ref.extractall(temp_extract)

        # The zip extracts to a folder named vosk-model-small-ru-0.22
        extracted_folder = temp_extract / MODEL_ARCHIVE_NAME
        if not extracted_folder.exists():
            # Fallback search for any child directory that has am/conf
            subdirs = [p for p in temp_extract.iterdir() if p.is_dir()]
            if subdirs:
                extracted_folder = subdirs[0]

        if not extracted_folder.exists():
            print("❌ Ошибка: распакованная папка с моделью не найдена.")
            return False

        if target_dir.exists():
            shutil.rmtree(target_dir)

        shutil.move(str(extracted_folder), str(target_dir))
        print(f"✅ Модель успешно установлена в: {target_dir}")
        return True

    except Exception as e:
        print(f"\n❌ Не удалось скачать или распаковать модель: {e}")
        return False
    finally:
        if temp_zip.exists():
            try:
                temp_zip.unlink()
            except OSError:
                pass
        if temp_extract.exists():
            try:
                shutil.rmtree(temp_extract)
            except OSError:
                pass


if __name__ == "__main__":
    success = download_and_extract_model()
    sys.exit(0 if success else 1)
