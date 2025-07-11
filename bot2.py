import os
import logging
import re
from datetime import datetime, timedelta
from aiohttp import web
from telegram import Update, ChatMember
from telegram.ext import (
    ApplicationBuilder, MessageHandler, ContextTypes, filters
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)

BAD_WORDS = {
    'хуй', 'хyй', 'хуи', 'хуя', 'хуе', 'хуё', 'хуй', 'хуем', 'хуев', 'хуёв',
    'пизда', 'пиздец', 'пизду', 'пизд', 'пезд', 'пиздюк',
    'ебать', 'ебан', 'ёб', 'ебло', 'еблан', 'ебу', 'ебись', 'ебач', 'ебля',
    'манда', 'мудила', 'мудло', 'мудак', 'долбоеб', 'долбаеб',
    'сука', 'суко', 'суки', 'сукин', 'блядь', 'бля', 'бляд', 'блят', 'блядина',
    'fuck', 'shit', 'asshole', 'fucking', 'bitch', 'bastard', 'nigger', 'faggot'
}

def build_bad_word_patterns(words: set) -> list:
    patterns = []
    for word in words:
        spaced = r'\W{0,2}'.join(re.escape(c) for c in word)
        patterns.append(re.compile(spaced, re.IGNORECASE))
    return patterns

BAD_WORD_PATTERNS = build_bad_word_patterns(BAD_WORDS)

AD_KEYWORDS = {
    'работа', 'заработок', '1400₽', 'удалённо', 'деньги',
    'лёгкие задачи', 'подпишись', 'пиши в лс', '@', 't.me/', 'клиенты'
}

def contains_profanity(text: str) -> bool:
    for pattern in BAD_WORD_PATTERNS:
        if pattern.search(text):
            return True
    return False

def is_emoji_spam(text: str) -> bool:
    emoji_pattern = r'[\U0001F300-\U0001FAFF]'
    emojis = re.findall(emoji_pattern, text)
    if len(emojis) >= 10:
        return True
    if re.search(r'(.)\1{4,}', text):
        return True
    return False

def contains_ads(text: str) -> bool:
    lower_text = text.lower()
    return any(word in lower_text for word in AD_KEYWORDS)

FLOOD_LIMIT = 3
FLOOD_INTERVAL = 10  # секунд

def is_flooding(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    now = datetime.now()
    key = f"flood:{chat_id}:{user_id}"
    history = context.chat_data.get(key, [])
    history = [t for t in history if now - t < timedelta(seconds=FLOOD_INTERVAL)]
    history.append(now)
    context.chat_data[key] = history
    return len(history) >= FLOOD_LIMIT

async def is_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception as e:
        logging.warning(f"Ошибка при проверке статуса админа: {e}")
        return False

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.from_user:
        return

    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text or message.caption or ""

    if await is_admin(chat_id, user_id, context):
        return

    try:
        if contains_profanity(text):
            await message.delete()
            logging.info(f"Удалено сообщение от {user_id} (мат)")
            return

        if contains_ads(text):
            await message.delete()
            logging.info(f"Удалено сообщение от {user_id} (реклама)")
            return

        if is_emoji_spam(text):
            await message.delete()
            logging.info(f"Удалено сообщение от {user_id} (эмодзи-спам)")
            return

        has_media = message.photo or message.video or message.document or message.animation

        # Удаляем медиа-сообщения без подписи (caption)
        if has_media and not text.strip():
            await message.delete()
            logging.info(f"Удалено медиа-сообщение от {user_id} (без подписи)")
            return

    except Exception as e:
        logging.warning(f"Ошибка при удалении: {e}")

    if is_flooding(user_id, chat_id, context):
        try:
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await context.bot.send_message(chat_id, f"🚫 Пользователь @{message.from_user.username or user_id} забанен за флуд.")
            logging.info(f"Пользователь {user_id} забанен за флуд")
        except Exception as e:
            logging.warning(f"Не удалось забанить пользователя: {e}")

# --- Веб-сервер для Webhook и пинга ---
async def handle_webhook(request):
    app = request.app['bot_app']
    data = await request.json()
    update = Update.de_json(data, app.bot)
    await app.update_queue.put(update)
    return web.Response(text='OK')

async def handle_ping(request):
    return web.Response(text='pong')

async def on_startup(app):
    bot_app = app['bot_app']
    # Устанавливаем webhook (замени URL на свой реальный)
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        await bot_app.bot.set_webhook(webhook_url)
        logging.info(f"Webhook установлен: {webhook_url}")
    else:
        logging.warning("WEBHOOK_URL не задан, webhook не установлен!")

async def create_app():
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("Укажи BOT_TOKEN в переменных окружения")

    app = web.Application()

    application = ApplicationBuilder().token(bot_token).build()
    application.add_handler(MessageHandler(filters.ALL, handle_message))

    app['bot_app'] = application

    app.router.add_post(f"/{bot_token}", handle_webhook)
    app.router.add_get('/ping', handle_ping)

    app.on_startup.append(on_startup)

    return app

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    web_app = create_app()
    logging.info(f"Запуск сервера на порту {port}")
    web.run_app(web_app, port=port)