@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo =====================================================
echo          🚀 ЗАПУСК TEAMS SENTINEL 🛡️
echo =====================================================

if not exist ".venv" (
    echo 📦 Создаем виртуальное окружение .venv...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

if not exist ".venv\installed.flag" (
    echo 📥 Проверка зависимостей...
    pip install -r requirements.txt
    type nul > .venv\installed.flag
)

echo ▶️ Запуск сервиса...
python main.py
pause
