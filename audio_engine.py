"""Audio Sentinel Engine.

Background audio monitoring service using sounddevice, numpy, and Vosk STT.
Listens to system audio loopback/microphone, catches name trigger words,
fires instant callbacks, records question context, and triggers Gemini analysis.
"""

import json
import logging
import os
import sys
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import sounddevice as sd
import vosk

from config import config

logger = logging.getLogger("TeamsSentinel.AudioEngine")

# Silence noisy Vosk debug logs
vosk.SetLogLevel(-1)


class SystemAudioStream:
    """Audio stream reader that captures strictly system output (speakers/headphones).

    On Linux, uses parec to hook directly into PipeWire/PulseAudio sink monitor.
    On Windows / fallback, uses sounddevice.
    """

    def __init__(self, block_size: int = 4000):
        self.block_size = block_size
        self.monitor_name = None
        self.proc = None
        self.sd_stream = None
        self.device_display_name = "Звук системы"

        self._init_stream()

    def _init_stream(self):
        import shutil
        import subprocess

        # Try native Linux pulse/pipewire monitor first
        if sys.platform == "linux" and shutil.which("parec"):
            try:
                sink = subprocess.check_output(["pactl", "get-default-sink"], text=True, timeout=2).strip()
                if sink:
                    self.monitor_name = f"{sink}.monitor"
                    self.proc = subprocess.Popen(
                        ["parec", "-d", self.monitor_name, "--rate=16000", "--channels=1", "--format=s16le"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                    )
                    sink_clean = sink.split(".")[-2] if "." in sink else sink
                    self.device_display_name = f"Звук с ПК ({sink_clean}) [без микрофона]"
                    logger.info(f"Connected directly to system audio monitor: {self.monitor_name}")
                    return
            except Exception as e:
                logger.warning(f"parec monitor hook failed, falling back to sounddevice: {e}")

        # Fallback to sounddevice
        try:
            self.sd_stream = sd.RawInputStream(
                samplerate=16000,
                blocksize=self.block_size,
                dtype="int16",
                channels=1,
                device=config.audio_device_index,
            )
            self.sd_stream.start()
            self.device_display_name = "Системный аудиопоток (sounddevice)"
            logger.info("Connected via sounddevice stream.")
        except Exception as e:
            logger.error(f"Failed to initialize sounddevice stream: {e}")
            raise e

    def read(self) -> bytes:
        """Reads one block of PCM16 mono audio at 16000Hz (block_size samples = block_size*2 bytes)."""
        bytes_to_read = self.block_size * 2
        if self.proc and self.proc.stdout:
            data = self.proc.stdout.read(bytes_to_read)
            return data
        elif self.sd_stream:
            data, _ = self.sd_stream.read(self.block_size)
            return bytes(data)
        return b""

    def close(self):
        if self.proc:
            try:
                if self.proc.stdout:
                    self.proc.stdout.close()
                self.proc.terminate()
                self.proc.wait(timeout=1.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None

        if self.sd_stream:
            try:
                self.sd_stream.stop()
                self.sd_stream.close()
            except Exception:
                pass
            self.sd_stream = None


class SentinelState(str, Enum):
    STOPPED = "Остановлен"
    LISTENING = "Слушает звук с ПК 🟢"
    RECORDING_CONTEXT = "Запись вопроса 🎙"
    COOLDOWN = "Остывание ⏳"
    ERROR = "Ошибка 🔴"


class AudioSentinel:
    def __init__(
        self,
        on_trigger_detected: Optional[Callable[[str], None]] = None,
        on_context_collected: Optional[Callable[[str, str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.on_trigger_detected = on_trigger_detected
        self.on_context_collected = on_context_collected
        self.on_error = on_error

        self.state: SentinelState = SentinelState.STOPPED
        self.last_error: Optional[str] = None
        self.current_device_name: str = "Звук системы (без микрофона)"
        self.current_device_index: Optional[int] = None

        self._model: Optional[vosk.Model] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def load_model(self) -> bool:
        """Loads Vosk model if not already loaded."""
        model_path = Path(config.vosk_model_path)
        if not model_path.exists():
            msg = f"Папка с моделью Vosk не найдена: {model_path}. Запустите python download_model.py"
            logger.error(msg)
            self._set_error(msg)
            return False

        try:
            if self._model is None:
                logger.info(f"Загрузка модели Vosk из {model_path}...")
                self._model = vosk.Model(str(model_path))
                logger.info("Модель Vosk успешно загружена.")
            return True
        except Exception as e:
            msg = f"Ошибка при загрузке модели Vosk: {e}"
            logger.error(msg)
            self._set_error(msg)
            return False

    def _set_error(self, message: str):
        with self._lock:
            self.state = SentinelState.ERROR
            self.last_error = message
        if self.on_error:
            try:
                self.on_error(message)
            except Exception as ex:
                logger.error(f"Error in on_error callback: {ex}")

    def _contains_trigger(self, text: str) -> Optional[str]:
        if not text:
            return None
        import re
        raw_words = re.findall(r'[а-яёa-z0-9]+', text.lower())

        # Valid Russian grammatical declension endings for personal names
        valid_declension_suffixes = {
            "", "а", "у", "ом", "е", "ы", "ым", "ой", "ему", "ами", "ах",
            "ова", "ову", "овым", "ове", "овна", "ович", "овну", "овичу"
        }

        for w in raw_words:
            for trigger in config.trigger_words:
                t = trigger.lower().strip()
                # 1. Exact match
                if w == t:
                    return trigger
                # 2. Strict stem prefix match with valid grammar ending (blocks 'альтернативный', 'альбом' etc.)
                if w.startswith(t):
                    suffix = w[len(t):]
                    if suffix in valid_declension_suffixes:
                        return trigger
        return None

    def start_listening(self) -> bool:
        """Starts background monitoring thread."""
        with self._lock:
            if self.state in [SentinelState.LISTENING, SentinelState.RECORDING_CONTEXT]:
                logger.info("Radar is already running.")
                return True

            if not self.load_model():
                return False

            self._stop_event.clear()
            self.state = SentinelState.LISTENING
            self.last_error = None

            self._thread = threading.Thread(target=self._listening_worker, daemon=True, name="AudioSentinelWorker")
            self._thread.start()
            logger.info("AudioSentinel thread started.")
            return True

    def stop_listening(self):
        """Stops background audio listener."""
        with self._lock:
            self._stop_event.set()
            self.state = SentinelState.STOPPED

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("AudioSentinel thread stopped.")

    def get_status(self) -> Dict:
        """Returns current status summary dictionary."""
        with self._lock:
            return {
                "state": self.state.value,
                "is_running": self.state in [SentinelState.LISTENING, SentinelState.RECORDING_CONTEXT, SentinelState.COOLDOWN],
                "device_index": self.current_device_index,
                "device_name": self.current_device_name,
                "error": self.last_error,
                "trigger_words": config.trigger_words,
                "context_seconds": config.record_context_seconds,
            }

    def _listening_worker(self):
        """Main listening loop running in background thread."""
        stream = None
        try:
            stream = SystemAudioStream(block_size=config.block_size)
            self.current_device_name = stream.device_display_name
            recognizer = vosk.KaldiRecognizer(self._model, 16000)
            logger.info(f"Listening on {self.current_device_name}...")

            recording_trigger = None
            recording_deadline = 0.0
            context_phrases: List[str] = []
            cooldown_deadline = 0.0

            while not self._stop_event.is_set():
                pcm16_data = stream.read()
                if not pcm16_data:
                    time.sleep(0.01)
                    continue

                accepted = recognizer.AcceptWaveform(pcm16_data)
                now = time.time()

                with self._lock:
                    current_state = self.state

                if current_state == SentinelState.COOLDOWN and now >= cooldown_deadline:
                    with self._lock:
                        self.state = SentinelState.LISTENING
                    current_state = SentinelState.LISTENING

                current_text = ""
                if accepted:
                    res = json.loads(recognizer.Result())
                    current_text = res.get("text", "").strip()
                else:
                    partial_res = json.loads(recognizer.PartialResult())
                    current_text = partial_res.get("partial", "").strip()

                # 1. If currently LISTENING, watch for trigger words
                if current_state == SentinelState.LISTENING and current_text:
                    detected = self._contains_trigger(current_text)
                    if detected:
                        logger.warning(f"🚨 TRIGGER DETECTED: '{detected}' in text: '{current_text}'")
                        recording_trigger = detected
                        recording_deadline = now + config.record_context_seconds
                        context_phrases = [current_text]

                        with self._lock:
                            self.state = SentinelState.RECORDING_CONTEXT

                        if self.on_trigger_detected:
                            try:
                                self.on_trigger_detected(detected)
                            except Exception as ex:
                                logger.error(f"Error in on_trigger_detected callback: {ex}")

                # 2. If RECORDING_CONTEXT, accumulate speech phrases
                elif current_state == SentinelState.RECORDING_CONTEXT:
                    if accepted and current_text:
                        context_phrases.append(current_text)

                    if now >= recording_deadline:
                        final_res = json.loads(recognizer.FinalResult())
                        final_text = final_res.get("text", "").strip()
                        if final_text:
                            context_phrases.append(final_text)

                        recognizer = vosk.KaldiRecognizer(self._model, 16000)
                        full_transcript = " ".join(dict.fromkeys(context_phrases)).strip()
                        logger.info(f"Context collected ({config.record_context_seconds}s): '{full_transcript}'")

                        if self.on_context_collected:
                            try:
                                self.on_context_collected(recording_trigger, full_transcript)
                            except Exception as ex:
                                logger.error(f"Error in on_context_collected callback: {ex}")

                        cooldown_deadline = now + config.cooldown_seconds
                        with self._lock:
                            self.state = SentinelState.COOLDOWN
                        context_phrases = []
                        recording_trigger = None

        except Exception as e:
            logger.exception("AudioSentinel worker encountered an unexpected exception")
            self._set_error(f"Сбой аудиоустройства: {e}")
        finally:
            if stream:
                stream.close()
            with self._lock:
                if self.state != SentinelState.ERROR:
                    self.state = SentinelState.STOPPED

    def test_audio(self, duration: float = 5.0) -> Dict:
        """Records audio for a few seconds from system output to measure signal amplitude and test speech recognition."""
        if not self.load_model():
            return {
                "success": False,
                "error": "Модель Vosk не найдена.",
                "has_sound": False,
                "peak": 0,
                "transcript": "",
            }

        rec = vosk.KaldiRecognizer(self._model, 16000)
        chunks = []
        max_amplitude = 0
        stream = None

        try:
            stream = SystemAudioStream(block_size=config.block_size)
            dev_name = stream.device_display_name
            start_time = time.time()
            while time.time() - start_time < duration:
                pcm16_data = stream.read()
                if not pcm16_data:
                    time.sleep(0.01)
                    continue

                samples = np.frombuffer(pcm16_data, dtype=np.int16)
                if len(samples) > 0:
                    peak = int(np.max(np.abs(samples)))
                    if peak > max_amplitude:
                        max_amplitude = peak

                if rec.AcceptWaveform(pcm16_data):
                    r = json.loads(rec.Result()).get("text", "")
                    if r:
                        chunks.append(r)

            final_r = json.loads(rec.FinalResult()).get("text", "")
            if final_r:
                chunks.append(final_r)

            full_test_text = " ".join(chunks).strip()
            return {
                "success": True,
                "device_name": dev_name,
                "peak": max_amplitude,
                "has_sound": max_amplitude > 200,
                "transcript": full_test_text if full_test_text else "(речь не распознана, проверьте громкость или включите видео с речью)",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "device_name": "Ошибка",
                "peak": 0,
                "has_sound": False,
                "transcript": "",
            }
        finally:
            if stream:
                stream.close()
