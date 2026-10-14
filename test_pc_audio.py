"""Quick standalone utility to test capturing laptop/PC audio output."""

import sys
import time
import numpy as np
import json
import vosk

from audio_engine import SystemAudioStream

print("=" * 70)
print("🔊 ПРОВЕРКА ЗАХВАТА ЗВУКА С НОУТБУКА (БЕЗ МИКРОФОНА)")
print("=" * 70)

try:
    stream = SystemAudioStream(block_size=4000)
    print(f"🎯 Источник захвата: {stream.device_display_name}")
    print("ℹ️  Это прямой цифровой поток вывода звука с ноутбука.")
    print("🔒 Физический микрофон ОТКЛЮЧЕН — звуки в комнате не записываются.")
except Exception as e:
    print(f"❌ Не удалось инициализировать аудиопоток: {e}")
    sys.exit(1)

print("\n👉 Включи лекцию или видео со звуком на ноутбуке.")
print("Тестирование начнется через 2 секунды...\n")
time.sleep(2)

print("🎙 Слушаю 7 секунд системного звука...")

# Load Vosk model
try:
    vosk.SetLogLevel(-1)
    model = vosk.Model("model")
    rec = vosk.KaldiRecognizer(model, 16000)
except Exception as e:
    print(f"⚠️ Vosk модель не загрузилась ({e}), проверяем только уровень звука...")
    rec = None

max_peak = 0
transcript_parts = []

try:
    start_time = time.time()
    while time.time() - start_time < 7.0:
        pcm_data = stream.read()
        if not pcm_data:
            time.sleep(0.01)
            continue

        samples = np.frombuffer(pcm_data, dtype=np.int16)
        peak = int(np.max(np.abs(samples))) if len(samples) > 0 else 0
        if peak > max_peak:
            max_peak = peak

        # Visual volume bar
        bars = int((peak / 32768) * 30)
        bar_str = "█" * bars + "░" * (30 - bars)
        sys.stdout.write(f"\rГромкость: [{bar_str}] {peak:5d} / 32767")
        sys.stdout.flush()

        if rec and rec.AcceptWaveform(pcm_data):
            r = json.loads(rec.Result()).get("text", "")
            if r:
                transcript_parts.append(r)

    if rec:
        final_r = json.loads(rec.FinalResult()).get("text", "")
        if final_r:
            transcript_parts.append(final_r)

    print("\n\n" + "=" * 70)
    print("📊 РЕЗУЛЬТАТЫ ПРОВЕРКИ:")
    print("=" * 70)
    print(f"• Максимальная громкость: {max_peak} / 32767")

    if max_peak > 200:
        print("✅ Звук с ноутбука успешно захвачен!")
        text = " ".join(transcript_parts).strip()
        if text:
            print(f"📝 РАСПОЗНАННАЯ РЕЧЬ С НОУТБУКА:\n   «{text}»")
        else:
            print("📝 Слова не распознаны (в этот момент была тишина или музыка).")
    else:
        print("⚠️ На ноутбуке не было звука или громкость была на нуле.")
    print("=" * 70 + "\n")

finally:
    stream.close()
