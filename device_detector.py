"""Audio device detector for Teams Sentinel.

Lists available audio input devices and PulseAudio/PipeWire monitors,
helping users pick the right audio device index for system loopback capture.
"""

import os
import subprocess
import sys
from typing import List, Optional, Tuple

import sounddevice as sd


def get_sounddevice_inputs() -> List[dict]:
    """Returns list of devices with max_input_channels > 0."""
    devices = sd.query_devices()
    input_devs = []
    default_input = sd.default.device[0]

    for idx, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) > 0:
            hostapi = sd.query_hostapis(dev["hostapi"])["name"]
            is_default = (idx == default_input)
            input_devs.append({
                "index": idx,
                "name": dev["name"],
                "hostapi": hostapi,
                "channels": dev["max_input_channels"],
                "samplerate": int(dev["default_samplerate"]),
                "is_default": is_default,
            })
    return input_devs


def get_pulseaudio_sources() -> List[Tuple[str, str, bool]]:
    """Gets sources from pactl if running on Linux with Pulse/PipeWire.

    Returns: list of (source_name, description, is_monitor).
    """
    if sys.platform != "linux":
        return []

    try:
        res = subprocess.run(
            ["pactl", "list", "sources", "short"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
        )
        if res.returncode != 0:
            return []

        sources = []
        for line in res.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                source_id, source_name = parts[0], parts[1]
                is_mon = "monitor" in source_name.lower()
                sources.append((source_name, is_mon))
        return sources
    except Exception:
        return []


def print_device_table():
    print("=" * 80)
    print("🎧 TEAMS SENTINEL — АНАЛИЗАТОР АУДИОУСТРОЙСТВ")
    print("=" * 80)

    devices = get_sounddevice_inputs()
    if not devices:
        print("❌ Не найдено ни одного устройства ввода звука!")
        return

    print("\n📋 Доступные устройства ввода (sounddevice):")
    print("-" * 80)
    print(f"{'INDEX':<7} | {'CH':<4} | {'RATE (Hz)':<10} | {'API':<10} | {'НАЗВАНИЕ'}")
    print("-" * 80)

    recommended_idx = None
    keywords = ["monitor", "loopback", "stereo mix", "стерео микшер", "микшер", "what u hear"]

    for d in devices:
        idx_str = f"[{d['index']}]"
        if d['is_default']:
            idx_str += " *"
        name = d['name']
        is_rec = any(k in name.lower() for k in keywords)
        rec_marker = " 🌟 [РЕКОМЕНДУЕТСЯ]" if is_rec else ""
        if is_rec and recommended_idx is None:
            recommended_idx = d['index']

        print(f"{idx_str:<7} | {d['channels']:<4} | {d['samplerate']:<10} | {d['hostapi']:<10} | {name}{rec_marker}")

    print("-" * 80)
    print("* — текущее системное устройство ввода по умолчанию")

    # Linux PulseAudio/PipeWire special helper
    pulse_sources = get_pulseaudio_sources()
    if pulse_sources:
        print("\n🐧 Звуковой сервер Linux (PulseAudio / PipeWire):")
        print("Sentinel автоматически настроен слушать ИСКЛЮЧИТЕЛЬНО системный звук (без микрофона)!")
        monitor_sources = [s for s, is_mon in pulse_sources if is_mon]
        if monitor_sources:
            print("\nДоступные мониторы вывода звука с компьютера:")
            default_sink = None
            try:
                res = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True, check=True)
                default_sink = res.stdout.strip()
            except Exception:
                pass
            for src in monitor_sources:
                is_active = default_sink and (src == f"{default_sink}.monitor")
                curr_mark = " 🔊 [АКТИВНО СЕЙЧАС]" if is_active else ""
                print(f"  • {src}{curr_mark}")

    print("\n" + "=" * 80)
    print("📝 НАСТРОЙКА .env:")
    print("👉 ПРОСТО ОСТАВЬ В .env СТРОКУ ПУСТОЙ:")
    print("   AUDIO_DEVICE_INDEX=")
    print("   Sentinel сам автоматически подключится к динамикам ноутбука или наушникам.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    print_device_table()
