"""Teams Sentinel - Main entrypoint."""

import asyncio
import sys
from pathlib import Path

from config import BASE_DIR, config
from download_model import download_and_extract_model, is_model_valid


def preflight_checks():
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        print("=" * 70)
        print("⚠️ Файл .env не найден!")
        print("Создаем .env из .env.example...")
        example_file = BASE_DIR / ".env.example"
        if example_file.exists():
            with open(example_file, "r", encoding="utf-8") as src, open(env_file, "w", encoding="utf-8") as dst:
                dst.write(src.read())
            print("✅ Файл .env создан.")
            print("👉 Пожалуйста, откройте .env и укажите:")
            print("   1. TELEGRAM_BOT_TOKEN")
            print("   2. TELEGRAM_USER_ID")
            print("   3. GEMINI_API_KEY")
            print("=" * 70)
        return False

    # Check Vosk model
    if not is_model_valid(config.vosk_model_path):
        print("⏳ Проверка модели Vosk...")
        success = download_and_extract_model(config.vosk_model_path)
        if not success:
            print("❌ Не удалось подготовить модель Vosk. Проверьте интернет-соединение.")
            return False

    errors = config.validate()
    if errors:
        print("=" * 70)
        print("❌ Не заполнены обязательные параметры в файле .env:")
        for e in errors:
            print(f"  • {e}")
        print("=" * 70)
        print("Откройте .env в текстовом редакторе и укажите значения перед запуском.")
        return False

    return True


if __name__ == "__main__":
    if not preflight_checks():
        sys.exit(1)

    import bot
    asyncio.run(bot.main())
