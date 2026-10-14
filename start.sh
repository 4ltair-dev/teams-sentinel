#!/usr/bin/env bash
set -e

# Change to script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

echo "====================================================="
echo "         🚀 ЗАПУСК TEAMS SENTINEL 🛡️                 "
echo "====================================================="

# Check virtual environment
if [ ! -d ".venv" ]; then
    echo "📦 Создаем виртуальное окружение .venv..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
fi

# Ensure requirements installed
if [ ! -f ".venv/installed.flag" ]; then
    echo "📥 Проверка зависимостей..."
    .venv/bin/pip install -r requirements.txt
    touch .venv/installed.flag
fi

# Run main Sentinel service
echo "▶️ Запуск сервиса..."
exec .venv/bin/python main.py
