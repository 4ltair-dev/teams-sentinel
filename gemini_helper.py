"""Gemini AI Reasoning helper for Teams Sentinel.

Analyzes raw speech transcript of the teacher, extracts the core question,
and generates a concise, natural spoken answer (1-2 sentences).
"""

import logging
from typing import Dict, Optional
from google import genai
from google.genai import types

from config import config

logger = logging.getLogger("TeamsSentinel.Gemini")

def get_system_instruction(student_name: str) -> str:
    return (
        f"Ты — умный ассистент студента по имени {student_name}. "
        f"Преподаватель только что обратился к студенту ({student_name}) на онлайн-паре. "
        "Проанализируй распознанный фрагмент речи, выдели суть вопроса и сформулируй "
        "естественный, четкий и уверенный ответ на 1-2 предложения на русском языке, "
        "который студент может сразу зачитать голосом в микрофон. "
        f"Если вопроса не было (например, просто перекличка: '{student_name} здесь?'), "
        "предложи ответ для подтверждения присутствия (например: 'Да, я здесь!').\n\n"
        "Твой ответ ДОЛЖЕН иметь четкую структуру:\n"
        "❓ Вопрос: <суть вопроса или контекст обращения>\n"
        "🗣 Что сказать: <готовая реплика для студента на 1-2 предложения>"
    )


class GeminiHelper:
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = config.gemini_api_key if api_key is None else api_key.strip()
        self.model_name = model_name or config.gemini_model
        self._client: Optional[genai.Client] = None
        if self.api_key and not self.api_key.startswith("AIzaSy..."):
            try:
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Не удалось инициализировать Gemini Client: {e}")

    def is_available(self) -> bool:
        return bool(self.api_key and not self.api_key.startswith("AIzaSy...") and self._client)

    def analyze_question(self, raw_transcript: str) -> str:
        """Analyzes teacher's speech context and produces structured prompt for student.

        Returns markdown formatted text.
        """
        raw_transcript = (raw_transcript or "").strip()
        student_name = config.student_name

        if not raw_transcript:
            return (
                "❓ *Вопрос:* Слова преподавателя после обращения не распознаны.\n"
                "🗣 *Что сказать:* «Да, я здесь! Извините, звук прервался на секунду, повторите, пожалуйста, вопрос?»"
            )

        if not self.is_available():
            logger.warning("Gemini API key is not configured.")
            return (
                f"⚠️ *Gemini API ключ не настроен в .env!*\n\n"
                f"📝 *Распознанные слова препода:*\n_{raw_transcript}_\n\n"
                f"🗣 *Что сказать:* «Да, я здесь! Слушаю вас.»"
            )

        prompt = (
            f"Фрагмент распознанной речи преподавателя во время вызова студента:\n"
            f"\"\"\"\n{raw_transcript}\n\"\"\"\n\n"
            f"Выдели вопрос и напиши ответ для студента ({student_name})."
        )

        try:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=get_system_instruction(student_name),
                    temperature=0.3,
                ),
            )
            result_text = response.text.strip() if response and response.text else ""
            if not result_text:
                raise ValueError("Пустой ответ от модели Gemini")
            return result_text
        except Exception as e:
            logger.error(f"Ошибка при запросе к Gemini API: {e}")
            return (
                f"⚠️ *Ошибка анализа через Gemini ({e}):*\n\n"
                f"📝 *Распознанная речь препода:*\n_{raw_transcript}_\n\n"
                f"🗣 *Что сказать:* «Да, я на связи! Подскажите, пожалуйста, какой вопрос?»"
            )


# Default global instance
gemini_helper = GeminiHelper()
