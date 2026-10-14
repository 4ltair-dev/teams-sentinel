"""Integration simulation test for AudioSentinel with Vosk recognizer."""

import json
import time
import unittest
import numpy as np

from audio_engine import AudioSentinel, SentinelState
from config import config


class TestAudioSentinelSimulation(unittest.TestCase):
    def test_audio_sentinel_lifecycle(self):
        alerts = []
        contexts = []
        errors = []

        sentinel = AudioSentinel(
            on_trigger_detected=lambda w: alerts.append(w),
            on_context_collected=lambda t, c: contexts.append((t, c)),
            on_error=lambda e: errors.append(e),
        )

        # Status check when stopped
        status = sentinel.get_status()
        self.assertEqual(status["state"], SentinelState.STOPPED.value)
        self.assertFalse(status["is_running"])

        # Model loading check
        loaded = sentinel.load_model()
        self.assertTrue(loaded, "Vosk model should load successfully")

        # Test audio method check (runs for 0.5s)
        test_res = sentinel.test_audio(duration=0.5)
        self.assertTrue(test_res["success"], f"Audio test failed: {test_res.get('error')}")
        self.assertIn("peak", test_res)
        self.assertIn("device_name", test_res)


if __name__ == "__main__":
    unittest.main()
