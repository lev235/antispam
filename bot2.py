import os
import re
import logging
from datetime import datetime, timedelta

from flask import Flask, request, abort
from telegram import Update, ChatMember
from telegram.ext import (
    ApplicationBuilder, MessageHandler, ContextTypes, filters
)

# --- Логгирование ---
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)

# --- Матерные слова ---
BAD_WORDS = {
    'хуй', 'хyй', 'хуя', 'пизда', 'ебать', 'манда', 'мудак', 'сука', 'блядь',
    'fuck', 'shit', 'asshole', 'fucking', 'bitch', 'bastard', 'nigger', 'faggot'
}

def build_bad_word_patterns(words: set) -> list:
    return [re.compile(r'\W{0,2}'.join(re.escape(c) for c in word), re.IGNORECASE) for word in words]

BAD_WORD_PATTERNS = build_bad_word_patterns(BAD_WORDS)

# --- Реклама и флуд ---
AD_KEYWORDS = {'работа', 'заработок', 'деньги', '@', 't.me/', 'в лс', 'в telegram', '+7', '8-9'}
FLOOD_LIMIT = 3
FLOOD_INTERVAL = 10  # секунд

def contains_profanity(text: str) -> bool:
    return any(p.search(text) for p in BAD_WORD_PATTERNS)

def contains_ads(text: str) -> bool:
    return any(word in text.lower() for word in AD_KEYWORDS)

def is_emoji_spam(text: str) -> bool:
    emoji_pattern = r'[\U0001F300-\U0001FAFF]'
    return len(re.findall(emoji_pattern, text)) >= 10 or re.search(r'(.)\1{4,}', text)

def filename_contains_ads(msg) -> bool:
    return (
        msg.document
        and msg.document.file_name
        and any(w in msg.document.file_name.lower() for w in AD_KEYWORDS)
    )

def is_flooding(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    now = datetime.now()
    key = f"flood:{chat_id}:{user_id}"
    history = [t for t in context.chat_data.get(key, []) if now - t < timedelta(seconds=FLOOD_INTERVAL)]
    history.append(now)
    context.chat_data[key] = history
    return len(history) >= FLOOD_LIMIT

async def is_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception as e:
        logging.warning(f"Ошибка проверки админа: {e}")
        return False

# --- Обработка сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return

    user_id = msg.from_user.id
    chat_id = msg.chat.id
    text = msg.text or msg.caption or ""
    has_media = msg.photo or msg.video or msg.document or msg.animation

    if await is_admin(chat_id, user_id, context):
        return

    try:
        if contains_profanity(text) or contains_ads(text) or is_emoji_spam(text):
            await msg.delete()
            logging.info(f"Удалено сообщение от {user_id} (текст)")
            return

        if has_media and not text.strip():
            if filename_contains_ads(msg):
                await msg.delete()
                logging.info(f"Удалено медиа от {user_id} (реклама в имени файла)")
                return
            await msg.delete()
            logging.info(f"Удалено медиа от {user_id} без текста")
            return

        if has_media and contains_ads(text):
            await msg.delete()
            logging.info(f"Удалено медиа от {user_id} (caption с рекламой)")
            return

    except Exception as e:
        logging.warning(f"Ошибка при удалении: {e}")

    if is_flooding(user_id, chat_id, context):
        try:
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await context.bot.send_message(chat_id, f"🚫 @{msg.from_user.username or user_id} забанен за флуд.")
            logging.info(f"Забанен за флуд: {user_id}")
        except Exception as e:
            logging.warning(f"Ошибка при бане: {e}")

# --- Flask-сервер ---
app = Flask(__name__)

@app.route("/")
def ping():
    logging.info("✅ Пинг получен")
    return "Бот работает!", 200

@app.route(f"/{os.getenv('BOT_TOKEN')}", methods=["POST"])
def telegram_webhook():
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), telegram_app.bot)
        telegram_app.create_task(telegram_app.update_queue.put(update))
        return "OK"
    else:
        abort(405)

# --- Запуск приложения ---
if __name__ == "__main__":
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    DOMAIN = os.getenv("DOMAIN")  # Например: https://antispam-xxxxx.onrender.com

    if not BOT_TOKEN or not DOMAIN:
        logging.error("❌ Переменные окружения BOT_TOKEN и DOMAIN обязательны!")
        exit(1)

    telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()
    telegram_app.add_handler(MessageHandler(filters.ALL, handle_message))

    # Установка webhook
    telegram_app.bot.delete_webhook()
    telegram_app.bot.set_webhook(url=f"{DOMAIN}/{BOT_TOKEN}")
    logging.info("📡 Вебхук установлен")

    port = int(os.environ.get("PORT", 10000))
    telegram_app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{DOMAIN}/{BOT_TOKEN}",
    )