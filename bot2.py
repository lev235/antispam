import logging
import re
from datetime import datetime, timedelta
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
    'хуй', 'хyй', 'хуи', 'хуя', 'хуе', 'хуё', 'хуй', 'хуем', 'хуев', 'хуёв',
    'пизда', 'пиздец', 'пизду', 'пизд', 'пезд', 'пиздюк',
    'ебать', 'ебан', 'ёб', 'ебло', 'еблан', 'ебу', 'ебись', 'ебач', 'ебля',
    'манда', 'мудила', 'мудло', 'мудак', 'долбоеб', 'долбаеб',
    'сука', 'суко', 'суки', 'сукин', 'блядь', 'бля', 'бляд', 'блят', 'блядина',
    'fuck', 'shit', 'asshole', 'fucking', 'bitch', 'bastard', 'nigger', 'faggot',
    "заработок", "заработком", "зароботка", "зарааботки", 
}

def build_bad_word_patterns(words: set) -> list:
    patterns = []
    for word in words:
        spaced = r'\W{0,2}'.join(re.escape(c) for c in word)
        patterns.append(re.compile(spaced, re.IGNORECASE))
    return patterns

BAD_WORD_PATTERNS = build_bad_word_patterns(BAD_WORDS)

# --- Рекламные слова ---
AD_KEYWORDS = {
    'работа', 'заработок', 'удалённо', 'деньги', '1400₽', 'в лс', 'в личные',
    'пишите', 'подпишись', 'в телеграм', 'в telegram', 'в tg', 'whatsapp',
    'номер', 'телефон', 'водительские права', 'права', '@', 't.me/', '+7', '8-9'
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

def filename_contains_ads(message) -> bool:
    doc = message.document
    if not doc or not doc.file_name:
        return False
    lower_name = doc.file_name.lower()
    return any(word in lower_name for word in AD_KEYWORDS)

# --- Антифлуд ---
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

# --- Проверка: является ли пользователь админом ---
async def is_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception as e:
        logging.warning(f"Ошибка при проверке админа: {e}")
        return False

# --- Обработка сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.from_user:
        return

    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text or message.caption or ""
    has_media = message.photo or message.video or message.document or message.animation

    if await is_admin(chat_id, user_id, context):
        return

    try:
        if contains_profanity(text) or contains_ads(text) or is_emoji_spam(text):
            await message.delete()
            logging.info(f"Удалено сообщение от {user_id} (текст)")
            return

        if has_media and not text.strip():
            if filename_contains_ads(message):
                await message.delete()
                logging.info(f"Удалено медиа от {user_id} (имя файла с рекламой)")
                return

            await message.delete()
            logging.info(f"Удалено медиа от {user_id} без текста")
            return

        if has_media and contains_ads(text):
            await message.delete()
            logging.info(f"Удалено медиа от {user_id} (caption с рекламой)")
            return

    except Exception as e:
        logging.warning(f"Ошибка при удалении: {e}")

    # Антифлуд
    if is_flooding(user_id, chat_id, context):
        try:
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await context.bot.send_message(chat_id, f"🚫 Пользователь @{message.from_user.username or user_id} забанен за флуд.")
            logging.info(f"Пользователь {user_id} забанен за флуд")
        except Exception as e:
            logging.warning(f"Ошибка при бане: {e}")

# --- Запуск бота ---
if __name__ == '__main__':
    BOT_TOKEN = "7871463826:AAHQyxV0BtGtieuqNUHtSUb60A5vWU6HKWk"

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    print("🤖 Бот запущен...")
    app.run_polling()