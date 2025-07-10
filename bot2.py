import os
import re
import logging
from datetime import datetime, timedelta

from aiohttp import web
from telegram import Update, ChatMember
from telegram.ext import (
    Application, ApplicationBuilder, ContextTypes,
    MessageHandler, filters
)

# --- Логгирование ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# --- Конфигурация ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logging.error("❌ Переменная окружения BOT_TOKEN не установлена")
    exit(1)

BAD_WORDS = {
    'хуй', 'хyй', 'хуя', 'пизда', 'ебать', 'манда', 'мудак', 'сука', 'блядь',
    'член', 'залупа', 'гандон', 'пидор', 'пидр', 'пидорас', 'даун', 'шлюха', "пиши", "пишите", "в личные сообщения", "писать", "заработать", "заработком", "заработки", "заработай" "бюджет", "плачу", "платим"
}
AD_KEYWORDS = {'работа', 'заработок', 'деньги', 't.me/', '@', '+7', '8-9', "https://"}
FLOOD_LIMIT = 3
FLOOD_INTERVAL = 10  # секунд

def build_patterns(words):
    return [re.compile(r'\W{0,2}'.join(re.escape(c) for c in w), re.IGNORECASE) for w in words]

BAD_PATTERNS = build_patterns(BAD_WORDS)
MONEY_REGEX = re.compile(r'\b\d{2,6}\s?(р|руб|руб\.|рублей)\b', re.IGNORECASE)

def contains_profanity(text): return any(p.search(text) for p in BAD_PATTERNS)
def contains_ads(text): return any(k in text.lower() for k in AD_KEYWORDS)
def contains_money(text): return MONEY_REGEX.search(text)
def is_emoji_spam(text): return len(re.findall(r'[\U0001F300-\U0001FAFF]', text)) > 10

async def is_admin(chat_id, user_id, context):
    try:
        m = await context.bot.get_chat_member(chat_id, user_id)
        return m.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception as e:
        logging.warning(f"Ошибка проверки админа: {e}")
        return False

def is_flooding(user_id, chat_id, context):
    now = datetime.now()
    key = f"flood:{chat_id}:{user_id}"
    history = [t for t in context.chat_data.get(key, []) if now - t < timedelta(seconds=FLOOD_INTERVAL)]
    history.append(now)
    context.chat_data[key] = history
    return len(history) >= FLOOD_LIMIT

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            logging.info(f"Удалено сообщение от {user_id}")
            return
    except Exception as e:
        logging.warning(f"Ошибка удаления: {e}")

    if is_flooding(user_id, chat_id, context):
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            await context.bot.send_message(chat_id, f"🚫 @{msg.from_user.username or user_id} забанен за флуд.")
        except Exception as e:
            logging.warning(f"Ошибка при бане: {e}")

# --- Запуск aiohttp + Telegram Webhook ---
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

    # Aiohttp сервер
    aio_app = web.Application()
    aio_app.add_routes([
        web.post(f'/{BOT_TOKEN}', handle_webhook),
        web.get('/ping', handle_ping)
    ])

    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 10000)))
    await site.start()

    logging.info("✅ Сервер запущен")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await app.updater.idle()
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())