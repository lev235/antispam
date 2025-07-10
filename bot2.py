#!/usr/bin/env python3
import os, re, json, logging, threading, http.server, socketserver
from pathlib import Path
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    MessageHandler, CommandHandler,
    Defaults, filters
)

# ─── Окружение ───
TOKEN      = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("APP_URL") or os.getenv("RENDER_EXTERNAL_URL")
PORT       = int(os.getenv("PORT", "10000"))
if not (TOKEN and PUBLIC_URL):
    raise SystemExit("Set BOT_TOKEN and APP_URL/RENDER_EXTERNAL_URL")

# ─── База слов ───
BASE = ["бля","бляд","хуй","пизд","еба","еби","ебу","ебат","сука","мудак",
        "пидор","гандон","шлюха","еблан","залуп","мудок","нахуй",
        "соси","хуесос","долбаёб","пидар","мразь", "заработ", "пис", "пиш", "лс"]

def variants(w:str): ch=list(w); return [w, " ".join(ch), "-".join(ch), "_".join(ch)]
def flex(w:str): return r"\s*[\W_]*".join(map(re.escape, w))

MAT_REGEX  = re.compile("|".join(flex(v) for b in BASE for v in variants(b)), re.I)
SPAM_REGEX = re.compile(r"(https?://\S+|t\.me/|joinchat|скидк|деш[её]в|подпис)", re.I)
POSITIVE   = {"спасибо","круто","полезно","супер","great","awesome","thanks"}

# ─── Состояние ───
STORE = Path("state.json")
state = {"rep": {}, "seen_rep": {}, "seen_del": {}}
if STORE.exists():
    state.update(json.loads(STORE.read_text("utf-8")))

def save():
    STORE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def inc_rep(uid:int, delta:int=1) -> int:
    uid=str(uid)
    state["rep"][uid] = state["rep"].get(uid,0) + delta
    save()
    return state["rep"][uid]

# ─── Backlog ───
BACKLOG_LIMIT = 25
backlog_counter = 0
backlog_done    = False

def in_backlog_phase(): return not backlog_done
def mark_backlog_processed():
    global backlog_done
    backlog_done = True

# ─── Handlers ───
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global backlog_counter
    msg = update.effective_message
    if not msg or not msg.text:
        return

    chat_id = str(msg.chat.id)
    mid     = msg.message_id
    txt     = msg.text.lower()

    if in_backlog_phase():
        backlog_counter += 1
        if backlog_counter >= BACKLOG_LIMIT:
            mark_backlog_processed()

    if MAT_REGEX.search(txt) or SPAM_REGEX.search(txt):
        if mid in state["seen_del"].get(chat_id, {}):
            return
        await msg.delete()
        state.setdefault("seen_del", {}).setdefault(chat_id, {})[mid] = 1
        save()
        return

    if any(w in txt for w in POSITIVE):
        if mid in state["seen_rep"].get(chat_id, {}):
            return
        total = inc_rep(msg.from_user.id)
        await msg.reply_text(f"👍 Репутация +1 (итого {total})")
        state.setdefault("seen_rep", {}).setdefault(chat_id, {})[mid] = 1
        save()

async def cmd_rep(update: Update, _):
    uid=str(update.effective_user.id)
    await update.message.reply_text(
        f"👤 Ваша репутация: <b>{state['rep'].get(uid,0)}</b>"
    )

async def cmd_top(update: Update, _):
    if not state["rep"]:
        await update.message.reply_text("Пока пусто."); return
    top = sorted(state["rep"].items(), key=lambda kv: kv[1], reverse=True)[:10]
    lines = ["<b>🏆 ТОП-10</b>"] + [
        f"{i+1}. <a href='tg://user?id={u}'>user_{u}</a> — {s}"
        for i, (u,s) in enumerate(top)
    ]
    await update.message.reply_text("\n".join(lines))

# ─── Telegram App ───
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s: %(message)s")

app = (
    ApplicationBuilder()
    .token(TOKEN)
    .defaults(Defaults(parse_mode=ParseMode.HTML))
    .build()
)
app.add_handler(CommandHandler("rep", cmd_rep))
app.add_handler(CommandHandler("top", cmd_top))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

# ─── HTTP-сервер для Render (фиктивный порт) ───
def fake_webserver():
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()

threading.Thread(target=fake_webserver, daemon=True).start()

# ─── Запуск бота ───
if __name__ == "__main__":
    logging.info("🚀 Бот запускается...")
    app.run_polling()