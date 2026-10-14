#!/usr/bin/env bash
# Teams Sentinel - Desktop Shortcut Installer
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

DESKTOP_FILE="$SCRIPT_DIR/teams-sentinel.desktop"

echo "Creating desktop shortcut for Teams Sentinel..."
cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Version=1.0
Type=Application
Name=Teams Sentinel
Comment=Автономный радар для онлайн-пар (Vosk + Gemini + Telegram)
Exec=/bin/bash -c "cd '$SCRIPT_DIR' && ./start.sh"
Path=$SCRIPT_DIR
Icon=audio-input-microphone
Terminal=true
Categories=Utility;AudioVideo;
StartupNotify=true
EOF

chmod +x "$DESKTOP_FILE"

# Install to user application menu if available
if [ -d "$HOME/.local/share/applications" ]; then
    cp "$DESKTOP_FILE" "$HOME/.local/share/applications/"
    echo "✅ Установлено в системное меню: ~/.local/share/applications/teams-sentinel.desktop"
fi

# Install to Desktop (English or Russian locale)
if [ -d "$HOME/Desktop" ]; then
    cp "$DESKTOP_FILE" "$HOME/Desktop/"
    chmod +x "$HOME/Desktop/teams-sentinel.desktop"
    echo "✅ Ярлык создан на рабочем столе: ~/Desktop/teams-sentinel.desktop"
elif [ -d "$HOME/Рабочий стол" ]; then
    cp "$DESKTOP_FILE" "$HOME/Рабочий стол/"
    chmod +x "$HOME/Рабочий стол/teams-sentinel.desktop"
    echo "✅ Ярлык создан на рабочем столе: ~/Рабочий стол/teams-sentinel.desktop"
fi

echo "🎉 Готово! Ярлык успешно настроен для текущего пути: $SCRIPT_DIR"
