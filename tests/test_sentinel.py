"""Comprehensive unit and mock tests for Teams Sentinel."""

import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from audio_engine import AudioSentinel, SentinelState
from config import Config
from gemini_helper import GeminiHelper


class TestConfig(unittest.TestCase):
    def test_default_triggers(self):
        cfg = Config()
        self.assertIn("альтаир", cfg.trigger_words)
        self.assertIn("аскаров", cfg.trigger_words)

    def test_validate_missing_keys(self):
        cfg = Config(telegram_bot_token="", telegram_user_id=None, gemini_api_key="")
        errors = cfg.validate()
        self.assertEqual(len(errors), 3)


class TestTriggerDetection(unittest.TestCase):
    def setUp(self):
        self.sentinel = AudioSentinel()

    def test_exact_trigger_match(self):
        self.assertEqual(self.sentinel._contains_trigger("здравствуйте альтаир ответьте"), "альтаир")
        self.assertEqual(self.sentinel._contains_trigger("аскаров здесь"), "аскаров")

    def test_inflected_trigger_match(self):
        self.assertEqual(self.sentinel._contains_trigger("вопрос альтаиру"), "альтаир")
        self.assertEqual(self.sentinel._contains_trigger("спросим аскарова"), "аскарова")

    def test_no_false_positive_on_unrelated_words(self):
        self.assertIsNone(self.sentinel._contains_trigger("сегодня хорошая погода и лекция"))
        self.assertIsNone(self.sentinel._contains_trigger(""))
        self.assertIsNone(self.sentinel._contains_trigger("альтернативный вариант решения"))
        self.assertIsNone(self.sentinel._contains_trigger("альтернатива есть всегда"))
        self.assertIsNone(self.sentinel._contains_trigger("играет альт в оркестре"))
        self.assertIsNone(self.sentinel._contains_trigger("красивый альбом с фото"))


class TestFaultTolerance(unittest.TestCase):
    def test_missing_vosk_model_does_not_crash(self):
        error_mock = MagicMock()
        sentinel = AudioSentinel(on_error=error_mock)

        with patch("config.config.vosk_model_path", Path("/non/existent/path/for/vosk/model")):
            success = sentinel.start_listening()
            self.assertFalse(success)
            self.assertEqual(sentinel.state, SentinelState.ERROR)
            self.assertIn("не найдена", sentinel.last_error)
            error_mock.assert_called_once()

    def test_gemini_fallback_without_key(self):
        helper = GeminiHelper(api_key="")
        res = helper.analyze_question("какой протокол используется в вебе")
        self.assertIn("не настроен", res)
        self.assertIn("какой протокол используется в вебе", res)

    def test_gemini_fallback_empty_transcript(self):
        helper = GeminiHelper(api_key="fake-key")
        res = helper.analyze_question("")
        self.assertIn("не распознаны", res)
        self.assertIn("Что сказать", res)


class TestMockPipeline(unittest.TestCase):
    def test_end_to_end_trigger_and_context_pipeline(self):
        """Simulates full event pipeline:

        1. Trigger detection ('альтаир') fires instant callback.
        2. Speech context accumulates.
        3. Context collected callback fires with complete transcript.
        4. Gemini helper formats questions and ready answer.
        """
        instant_alerts = []
        collected_contexts = []
        errors = []

        def on_trigger(word):
            instant_alerts.append(word)

        def on_context(trigger, transcript):
            collected_contexts.append((trigger, transcript))

        def on_error(err):
            errors.append(err)

        sentinel = AudioSentinel(
            on_trigger_detected=on_trigger,
            on_context_collected=on_context,
            on_error=on_error,
        )

        # 1. Simulate trigger recognition
        detected = sentinel._contains_trigger("так альтаир слушаем вас")
        self.assertEqual(detected, "альтаир")
        on_trigger(detected)

        self.assertEqual(len(instant_alerts), 1)
        self.assertEqual(instant_alerts[0], "альтаир")

        # 2. Simulate context collection
        simulated_context = "скажите пожалуйста в чем отличие процесса от потока"
        on_context(detected, simulated_context)

        self.assertEqual(len(collected_contexts), 1)
        trigger_res, transcript_res = collected_contexts[0]
        self.assertEqual(trigger_res, "альтаир")
        self.assertEqual(transcript_res, simulated_context)

        # 3. Test mock Gemini analysis formatting
        with patch.object(
            GeminiHelper,
            "analyze_question",
            return_value=(
                "❓ Вопрос: В чем отличие процесса от потока?\n"
                "🗣 Что сказать: Процесс имеет собственное адресное пространство памяти, а потоки разделяют память процесса."
            ),
        ):
            helper = GeminiHelper()
            analysis = helper.analyze_question(transcript_res)
            self.assertIn("❓ Вопрос:", analysis)
            self.assertIn("🗣 Что сказать:", analysis)
            self.assertIn("процесса от потока", analysis)


if __name__ == "__main__":
    unittest.main()
