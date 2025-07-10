import os
import re
import logging
import asyncio
from datetime import datetime, timedelta
from aiohttp import web
from telegram import Update, ChatMember
from telegram.ext import (
    ApplicationBuilder, MessageHandler, ContextTypes, filters
)

from PIL import Image
import pytesseract
import aiohttp
from io import BytesIO

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ Укажи переменную окружения BOT_TOKEN")

# --- Настройки ---
BAD_WORDS = {
    'хуй', 'пизда', 'ебать', 'манда', 'сука', 'блядь', 'мудила',
    'хуесос', 'еблан', 'соси', 'пидор', 'залупа', 'шлюха', 'гандон',
    "пиши", "пишите", "в личные сообщения", "писать", "заработать",
    "заработком", "заработки", "заработай", "бюджет", "плачу", "платим"
}
AD_KEYWORDS = {'работа', 'заработок', 'деньги', '@', 't.me/', '+7', '8-9', "https://"}

FLOOD_LIMIT = 3
FLOOD_INTERVAL = 10  # секунд

# --- Построение паттернов ---
def build_bad_patterns(words):
    return [re.compile(r'\W{0,3}'.join(re.escape(c) for c in word), re.IGNORECASE) for word in words]

BAD_PATTERNS = build_bad_patterns(BAD_WORDS)

# --- Проверки текста ---
def contains_profanity(text):
    return any(p.search(text) for p in BAD_PATTERNS)

def contains_ads(text):
    return any(word in text.lower() for word in AD_KEYWORDS)

def contains_money(text):
    return bool(re.search(r'\b\d{2,}\s?(р|руб|рублей)\b', text.lower()))

def is_emoji_spam(text):
    return len(re.findall(r'[\U0001F300-\U0001FAFF]', text)) > 10

def is_flooding(user_id, chat_id, context):
    now = datetime.now()
    key = f"flood:{chat_id}:{user_id}"
    history = [t for t in context.chat_data.get(key, []) if now - t < timedelta(seconds=FLOOD_INTERVAL)]
    history.append(now)
    context.chat_data[key] = history
    return len(history) >= FLOOD_LIMIT

# --- Проверка администратора ---
async def is_admin(chat_id, user_id, context):
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception as e:
        logging.warning(f"Ошибка при проверке админа: {e}")
        return False

# --- Распознавание текста с картинки ---
async def extract_text_from_image(file_url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                if resp.status == 200:
                    img_bytes = await resp.read()
                    image = Image.open(BytesIO(img_bytes))
                    # Укажи путь к tessdata, если требуется
                    return pytesseract.image_to_string(
                        image,
                        lang='rus+eng',
                        config='--tessdata-dir /usr/local/share/tessdata/'
                    )
    except Exception as e:
        logging.warning(f"Ошибка распознавания изображения: {e}")
    return ""

# --- Обработка сообщений ---
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return

    chat_id = msg.chat.id
    user_id = msg.from_user.id
    text = msg.text or msg.caption or ""

    if await is_admin(chat_id, user_id, context):
        return

    try:
        # Проверка текста и подписи
        if contains_profanity(text) or contains_ads(text) or contains_money(text) or is_emoji_spam(text):
            await msg.delete()
            logging.info(f"Удалено сообщение от {user_id} (по тексту)")
            return

        # Проверка фото
        if msg.photo:
            file = await context.bot.get_file(msg.photo[-1].file_id)
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
            img_text = await extract_text_from_image(file_url)

            logging.info(f"Распознанный текст из фото: {img_text[:200]}")  # лог первых 200 символов

            if img_text:
                # Усиленная проверка рекламы по распознанному тексту
                ad_pattern = re.compile(r'(' + '|'.join(re.escape(word) for word in AD_KEYWORDS) + r')', re.IGNORECASE)
                if contains_profanity(img_text) or ad_pattern.search(img_text) or contains_money(img_text):
                    await msg.delete()
                    logging.info(f"Удалено фото от {user_id} (по изображению)")
                    return

    except Exception as e:
        logging.warning(f"Ошибка при удалении: {e}")

    # Проверка на флуд
    if is_flooding(user_id, chat_id, context):
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            await context.bot.send_message(chat_id, f"🚫 @{msg.from_user.username or user_id} забанен за флуд.")
            logging.info(f"Забанен {user_id}")
        except Exception as e:
            logging.warning(f"Ошибка при бане: {e}")

# --- aiohttp сервер и Webhook ---
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, handle))

    async def handle_ping(request):
        return web.Response(text="OK")

    async def handle_webhook(request):
        data = await request.json()
        update = Update.de_json(data, app.bot)
        await app.update_queue.put(update)
        return web.Response(text="ok")

    aio_app = web.Application()
    aio_app.add_routes([
        web.post(f"/{BOT_TOKEN}", handle_webhook),
        web.get("/", handle_ping),
        web.get("/ping", handle_ping)
    ])

    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 10000)))
    await site.start()

    logging.info("✅ Сервер запущен")
    await app.initialize()
    await app.start()
    await app.updater.idle()

if __name__ == "__main__":
    asyncio.run(main())