import os
import re
import logging
from datetime import datetime, timedelta
from aiohttp import web
from telegram import Update, ChatMember
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

# --- Логгирование ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# --- Маты, реклама, деньги ---
BAD_WORDS = {
    "хуй", "х у й", "х@й", "хyй", "х*й", "хуи", "пиз", "п и з", "п*з",
    "еб", "ёб", "е б а", "еба", "манда", "сучка", "бля", "б л я", "гандон", "долбоёб",
    "залупа", "уеб", "пидор", "чмо", "мразь", "жопа", "мудило"
}
AD_KEYWORDS = {"работа", "деньги", "заработок", "@", "t.me", "в лс", "+7", "8-9"}
FLOOD_LIMIT = 3
FLOOD_INTERVAL = 10  # секунд
MONEY_PATTERN = re.compile(r'\b\d{2,7}\s?(₽|р|руб|рублей)\b', re.IGNORECASE)

def build_patterns(words: set) -> list:
    return [re.compile(r'\W*'.join(re.escape(c) for c in word), re.IGNORECASE) for word in words]

BAD_PATTERNS = build_patterns(BAD_WORDS)

def contains_profanity(text: str) -> bool:
    return any(p.search(text) for p in BAD_PATTERNS)

def contains_ads(text: str) -> bool:
    return any(word in text.lower() for word in AD_KEYWORDS)

def contains_money(text: str) -> bool:
    return bool(MONEY_PATTERN.search(text))

def is_emoji_spam(text: str) -> bool:
    return len(re.findall(r'[\U0001F300-\U0001FAFF]', text)) > 10 or re.search(r'(.)\1{4,}', text)

def filename_contains_ads(msg) -> bool:
    return msg.document and msg.document.file_name and contains_ads(msg.document.file_name)

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
        if contains_profanity(text) or contains_ads(text) or contains_money(text) or is_emoji_spam(text):
            await msg.delete()
            logging.info(f"Удалено сообщение от {user_id} (текст)")
            return

        if has_media and not text.strip():
            if filename_contains_ads(msg):
                await msg.delete()
                logging.info(f"Удалено медиа от {user_id} (имя файла)")
                return
            await msg.delete()
            logging.info(f"Удалено медиа от {user_id} без текста")
            return

        if has_media and (contains_ads(text) or contains_money(text)):
            await msg.delete()
            logging.info(f"Удалено медиа от {user_id} (caption с рекламой/ценой)")
            return

    except Exception as e:
        logging.warning(f"Ошибка при удалении: {e}")

    if is_flooding(user_id, chat_id, context):
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            await context.bot.send_message(chat_id, f"🚫 @{msg.from_user.username or user_id} забанен за флуд.")
            logging.info(f"Забанен за флуд: {user_id}")
        except Exception as e:
            logging.warning(f"Ошибка при бане: {e}")

# --- Запуск ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.environ.get("PORT", 8443))
BASE_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}"

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.ALL, handle_message))

# --- /ping обработка ---
async def ping_handler(request):
    return web.Response(text="OK")

app.web_app.add_get("/ping", ping_handler)

# --- Запуск Webhook ---
if __name__ == "__main__":
    webhook_url = f"{BASE_URL}/{BOT_TOKEN}"
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=webhook_url,
    )