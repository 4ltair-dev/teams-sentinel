"""Telegram Bot Control Interface for Teams Sentinel.

Manages radar lifecycle via inline keyboard, delivers instant roll-call alerts,
and sends Gemini-powered question breakdowns and answer cheat sheets.
"""

import asyncio
import logging
import sys
from typing import Optional

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.client.default import DefaultBotProperties

from audio_engine import AudioSentinel, SentinelState
from config import config
from gemini_helper import gemini_helper
from web_bridge import web_bridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("TeamsSentinel.Bot")

# Event loop reference for threadsafe coroutines
bot_loop: Optional[asyncio.AbstractEventLoop] = None
bot_instance: Optional[Bot] = None
sentinel_instance: Optional[AudioSentinel] = None


def get_control_keyboard() -> InlineKeyboardMarkup:
    """Builds inline control keyboard with auto-plus and Teams chat bridge buttons."""
    auto_plus_txt = f"⚙️ Авто-плюс: {'ВКЛ (' + str(config.auto_plus_threshold) + ')' if config.auto_plus_enabled else 'ВЫКЛ'}"
    buttons = [
        [
            InlineKeyboardButton(text="🟢 Включить радар", callback_data="start_radar"),
            InlineKeyboardButton(text="🔴 Выключить радар", callback_data="stop_radar"),
        ],
        [
            InlineKeyboardButton(text="➕ Поставить «+» в Teams", callback_data="send_plus_teams"),
            InlineKeyboardButton(text=auto_plus_txt, callback_data="toggle_auto_plus"),
        ],
        [
            InlineKeyboardButton(text="📊 Статус", callback_data="status_radar"),
            InlineKeyboardButton(text="🔊 Тест звука с ПК (5с)", callback_data="test_sound"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def is_authorized(user_id: int) -> bool:
    """Checks if the user ID matches the owner configured in .env."""
    if config.telegram_user_id is None:
        return False
    return user_id == config.telegram_user_id


async def send_unauthorized_reply(message_or_call):
    text = "⛔ *Доступ ограничен!*\nЭтот бот настроен исключительно для личного использования владельцем."
    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, parse_mode=ParseMode.MARKDOWN)
    elif isinstance(message_or_call, CallbackQuery):
        await message_or_call.answer("⛔ Доступ ограничен!", show_alert=True)


# --- Thread-Safe Callbacks from AudioSentinel ---

def on_trigger_detected_callback(trigger_word: str):
    """Called immediately from background audio thread when name is detected."""
    logger.warning(f"Firing immediate alert for trigger '{trigger_word}'")
    if bot_instance and bot_loop and config.telegram_user_id:
        asyncio.run_coroutine_threadsafe(
            _async_send_trigger_alert(trigger_word),
            bot_loop,
        )


async def _async_send_trigger_alert(trigger_word: str):
    alert_text = (
        "🚨🚨🚨 *ТЕБЯ ВЫЗВАЛИ НА ПАРЕ!* 🚨🚨🚨\n\n"
        "⚡ Срочно подойди к компьютеру и включи микрофон!\n"
        f"🎯 Обнаружено имя/триггер: *{trigger_word}*\n"
        f"⏳ Слушаю вопрос преподавателя ({config.record_context_seconds} сек) и готовлю ответ..."
    )
    try:
        await bot_instance.send_message(
            chat_id=config.telegram_user_id,
            text=alert_text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"Failed to send immediate trigger alert: {e}")


def on_context_collected_callback(trigger_word: str, full_transcript: str):
    """Called from background thread after 12-15 seconds of context recording."""
    logger.info("Context collected. Requesting Gemini analysis and dispatching to bot...")
    if bot_instance and bot_loop and config.telegram_user_id:
        asyncio.run_coroutine_threadsafe(
            _async_send_context_analysis(trigger_word, full_transcript),
            bot_loop,
        )


async def _async_send_context_analysis(trigger_word: str, full_transcript: str):
    # Run Gemini reasoning in thread pool to avoid blocking asyncio loop
    analysis = await asyncio.to_thread(gemini_helper.analyze_question, full_transcript)

    message_text = (
        "📋 *КОНТЕКСТ ВОПРОСА ПРЕПОДАВАТЕЛЯ:*\n"
        f"_{full_transcript if full_transcript else '(Слова после имени не распознаны)'}_\n\n"
        "──────────────────────\n"
        "💡 *АНАЛИЗ И ШПАРГАЛКА (GEMINI):*\n\n"
        f"{analysis}\n"
        "──────────────────────\n"
        "🟢 Радар продолжает слушать эфир."
    )
    try:
        await bot_instance.send_message(
            chat_id=config.telegram_user_id,
            text=message_text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"Failed to send context analysis: {e}")


def on_audio_error_callback(error_msg: str):
    """Called from background thread when audio or model fails."""
    logger.error(f"Audio sentinel error: {error_msg}")
    if bot_instance and bot_loop and config.telegram_user_id:
        asyncio.run_coroutine_threadsafe(
            _async_send_error_alert(error_msg),
            bot_loop,
        )


async def _async_send_error_alert(error_msg: str):
    text = (
        f"⚠️ *Ошибка аудио-радара Sentinel:*\n\n"
        f"`{error_msg}`\n\n"
        "Проверьте настройки устройства через `python device_detector.py` или наличие модели Vosk."
    )
    try:
        await bot_instance.send_message(
            chat_id=config.telegram_user_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"Failed to send error alert: {e}")


# --- Telegram Handlers ---

dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message):
    if not is_authorized(message.from_user.id):
        await send_unauthorized_reply(message)
        return

    text = (
        "🛡 *Teams Sentinel v1.0 — Радар онлайн-пар*\n\n"
        "Сервис непрерывно мониторит системный звук Teams/конференций. "
        "Как только препод назовет твое имя или фамилию, ты мгновенно получишь тревогу, "
        "а следом — расшифровку вопроса и готовый ответ от Gemini Flash!\n\n"
        "Управляй радаром кнопками ниже:"
    )
    await message.answer(text, reply_markup=get_control_keyboard(), parse_mode=ParseMode.MARKDOWN)


@dp.callback_query(F.data == "start_radar")
async def cb_start_radar(call: CallbackQuery):
    if not is_authorized(call.from_user.id):
        await send_unauthorized_reply(call)
        return

    await call.answer("Запуск радара...")
    success = sentinel_instance.start_listening()
    status = sentinel_instance.get_status()

    if success:
        dev_info = status["device_name"]
        await call.message.edit_text(
            f"🟢 *Радар АКТИВИРОВАН!*\n\n"
            f"🎧 Аудиоустройство: `{dev_info}`\n"
            f"🎯 Триггеры: `{', '.join(status['trigger_words'])}`\n"
            f"⏱ Запись контекста: `{status['context_seconds']} сек`\n\n"
            "Можешь отходить от ПК. При вызове бот сразу напишет тебе!",
            reply_markup=get_control_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        err = status.get("error") or "Неизвестная ошибка"
        await call.message.edit_text(
            f"❌ *Не удалось запустить радар!*\n\nПричина: `{err}`",
            reply_markup=get_control_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )


@dp.callback_query(F.data == "stop_radar")
async def cb_stop_radar(call: CallbackQuery):
    if not is_authorized(call.from_user.id):
        await send_unauthorized_reply(call)
        return

    await call.answer("Остановка радара...")
    sentinel_instance.stop_listening()

    await call.message.edit_text(
        "🔴 *Радар ОСТАНОВЛЕН.*\n"
        "Аудиоустройство освобождено. Прослушка выключена.",
        reply_markup=get_control_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


@dp.callback_query(F.data == "status_radar")
async def cb_status_radar(call: CallbackQuery):
    if not is_authorized(call.from_user.id):
        await send_unauthorized_reply(call)
        return

    status = sentinel_instance.get_status()
    state_str = status["state"]
    dev_name = status["device_name"]
    err = status.get("error")

    text = (
        "📊 *ТЕКУЩИЙ СТАТУС SENTINEL:*\n\n"
        f"• Режим: *{state_str}*\n"
        f"• Устройство: `{dev_name}`\n"
        f"• Индекс: `{status['device_index'] if status['device_index'] is not None else 'По умолчанию'}`\n"
        f"• Триггеры: `{', '.join(status['trigger_words'])}`\n"
        f"• Окно контекста: `{status['context_seconds']} сек`\n"
        f"• Gemini AI: `{'Подключен (' + gemini_helper.model_name + ')' if gemini_helper.is_available() else 'Ключ не задан'}`\n"
        f"• Teams в браузере: `{'Подключен 🟢' if web_bridge.is_browser_connected() else 'Не открыт ⚪'}`\n"
        f"• Авто-плюс: `{'ВКЛ (порог: ' + str(config.auto_plus_threshold) + ' чел.)' if config.auto_plus_enabled else 'Выключен 🔴'}`\n"
    )
    if err:
        text += f"\n⚠️ *Последняя ошибка:* `{err}`\n"

    await call.message.edit_text(
        text,
        reply_markup=get_control_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )
    await call.answer()


@dp.callback_query(F.data == "test_sound")
async def cb_test_sound(call: CallbackQuery):
    if not is_authorized(call.from_user.id):
        await send_unauthorized_reply(call)
        return

    await call.message.edit_text(
        "🔊 *Тестирование звука с компьютера (5 секунд)...*\n"
        "Включи любое видео на YouTube или звук в Teams, чтобы проверить громкость захвата.\n\n"
        "_(Микрофон выключен, радар слушает только динамики/наушники)_",
        parse_mode=ParseMode.MARKDOWN,
    )
    await call.answer()

    result = await asyncio.to_thread(sentinel_instance.test_audio, 5.0)

    if not result.get("success"):
        err = result.get("error", "Неизвестная ошибка")
        await call.message.edit_text(
            f"❌ *Ошибка при тестировании звука:*\n`{err}`",
            reply_markup=get_control_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    has_sound = result["has_sound"]
    peak = result["peak"]
    transcript = result["transcript"]
    dev_name = result.get("device_name", "Устройство")

    sound_indicator = "🔊 Звук с ПК идет нормально!" if has_sound else "🔇 Звук не обнаружен (на ПК ничего не играет)"

    res_text = (
        f"🔊 *РЕЗУЛЬТАТ ТЕСТА ЗВУКА С ПК:*\n\n"
        f"• Источник: `{dev_name}`\n"
        f"• Физический микрофон: `НЕ используется (выключен)`\n"
        f"• Уровень громкости: `{peak} / 32767`\n"
        f"• Статус: *{sound_indicator}*\n\n"
        f"📝 *Распознанные слова с ПК (Vosk):*\n_{transcript}_\n\n"
        "Радар слушает исключительно то, что идет в твои наушники/динамики."
    )
    await call.message.edit_text(
        res_text,
        reply_markup=get_control_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def on_teams_chat_event_callback(event_type: str, data: dict):
    """Called when userscript detects an event in Teams chat."""
    if event_type == "auto_plus":
        count = data.get("count", config.auto_plus_threshold)
        authors = ", ".join(data.get("authors", []))
        alert_text = (
            "🎯🎯🎯 *АВТО-ПЛЮС СРАБОТАЛ В TEAMS!* 🎯🎯🎯\n\n"
            f"👥 В чате пары уже *{count} чел.* поставили «+»!\n"
            + (f"_(Студенты: {authors})_\n\n" if authors else "\n")
            + "✅ *Я автоматически отправил «+» в чат Teams за тебя!*"
        )
        if bot_instance and config.telegram_user_id:
            try:
                await bot_instance.send_message(
                    chat_id=config.telegram_user_id,
                    text=alert_text,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                logger.error(f"Failed to send auto-plus notification to Telegram: {e}")

    elif event_type == "auto_greeting":
        count = data.get("count", config.auto_greeting_threshold)
        authors = ", ".join(data.get("authors", []))
        alert_text = (
            "👋👋👋 *АВТО-ПРИВЕТСТВИЕ В TEAMS!* 👋👋👋\n\n"
            f"👥 В чате пары уже *{count} чел.* написали приветствие!\n"
            + (f"_(Студенты: {authors})_\n\n" if authors else "\n")
            + "✅ *Я автоматически отправил «Здравствуйте!» в чат Teams за тебя.*"
        )
        if bot_instance and config.telegram_user_id:
            try:
                await bot_instance.send_message(
                    chat_id=config.telegram_user_id,
                    text=alert_text,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                logger.error(f"Failed to send auto-greeting notification to Telegram: {e}")


@dp.callback_query(F.data == "send_plus_teams")
async def cb_send_plus_teams(call: CallbackQuery):
    if not is_authorized(call.from_user.id):
        await send_unauthorized_reply(call)
        return

    await web_bridge.queue_message("+")
    conn = "🟢 Вкладка Teams подключена" if web_bridge.is_browser_connected() else "⚠️ Вкладка Teams не обнаружена (откройте Teams в браузере)"
    await call.answer("Отправка «+» в Teams...")
    await call.message.answer(
        f"➕ *Команда на отправку «+» поставлена в очередь!*\n\n"
        f"Статус: {conn}",
        parse_mode=ParseMode.MARKDOWN,
    )


@dp.callback_query(F.data == "toggle_auto_plus")
async def cb_toggle_auto_plus(call: CallbackQuery):
    if not is_authorized(call.from_user.id):
        await send_unauthorized_reply(call)
        return

    config.auto_plus_enabled = not config.auto_plus_enabled
    state_str = "ВКЛЮЧЕН" if config.auto_plus_enabled else "ВЫКЛЮЧЕН"
    await call.answer(f"Авто-плюс {state_str}")
    try:
        await call.message.edit_reply_markup(reply_markup=get_control_keyboard())
    except Exception:
        pass


@dp.message(Command("say"))
async def cmd_say(message: Message):
    if not is_authorized(message.from_user.id):
        await send_unauthorized_reply(message)
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            "ℹ️ *Использование команды /say:*\n"
            "`/say <текст сообщения>`\n\n"
            "Пример:\n"
            "`/say Здравствуйте, я тут! Микрофон барахлит.`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    text_to_send = args[1].strip()
    await web_bridge.queue_message(text_to_send)
    conn = "🟢 Teams в браузере активен" if web_bridge.is_browser_connected() else "⚠️ Teams в браузере не открыт"
    await message.answer(
        f"💬 *Сообщение передано для отправки в Teams:*\n"
        f"«_{text_to_send}_»\n\n"
        f"Статус браузера: {conn}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def main():
    global bot_loop, bot_instance, sentinel_instance

    errors = config.validate()
    if errors:
        print("=" * 60)
        print("❌ ОШИБКА КОНФИГУРАЦИИ (.env):")
        for err in errors:
            print(f"  • {err}")
        print("=" * 60)
        print("Скопируйте .env.example в .env и заполните параметры.")
        sys.exit(1)

    bot_loop = asyncio.get_running_loop()
    bot_instance = Bot(
        token=config.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )

    sentinel_instance = AudioSentinel(
        on_trigger_detected=on_trigger_detected_callback,
        on_context_collected=on_context_collected_callback,
        on_error=on_audio_error_callback,
    )

    # Initialize Web Bridge for Teams browser integration
    web_bridge.on_chat_event = on_teams_chat_event_callback
    await web_bridge.start()

    logger.info("Initializing Teams Sentinel...")

    # Optional notification on bot start
    try:
        await bot_instance.send_message(
            chat_id=config.telegram_user_id,
            text="🚀 *Teams Sentinel запущен и готов к работе!*\nНажмите кнопку ниже для управления.",
            reply_markup=get_control_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.warning(f"Could not send startup greeting message: {e}")

    logger.info("Bot polling started. Press Ctrl+C to stop.")
    try:
        await dp.start_polling(bot_instance)
    finally:
        if sentinel_instance:
            sentinel_instance.stop_listening()
        await web_bridge.stop()
        await bot_instance.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Teams Sentinel stopped.")
