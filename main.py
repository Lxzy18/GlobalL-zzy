# global_nsfw_bot.py
"""
GlobalNSFWBot
Single-file Telegram moderation bot (python-telegram-bot v20).
- Token: paste inside BOT_TOKEN variable below
- Uses nsfw-image-detector (open-source) for image NSFW detection
- SQLite for state (bot_data.db by default)
- Inline keyboard /menu, admin menu, broadcasts, CSV export of chats/admins
- Auto language detection (tr/en/ru)
"""

import os
import logging
import asyncio
from datetime import datetime, timedelta
from functools import partial
import csv
import io

import aiosqlite
from nsfw_detector import predict  # pip install nsfw-image-detector

from telegram import (
    Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
)
from telegram.constants import ParseMode, ChatType
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# -----------------------------
# CONFIG — edit token HERE
# -----------------------------
BOT_TOKEN = "8397099975:AAHrvDJLwryw4out49TTyQLnbISvK2GXFdE"   # <<< paste your bot token here
BOT_NAME = "GlobalNSFWBot"
DB_FILE = "bot_data.db"
NSFW_THRESHOLD = 0.65
CONSECUTIVE_LIMIT = 10
MUTE_DURATION_SEC = 3600  # default mute duration when limit reached
DEFAULT_LANG = "tr"
OWNER_ID = 8052545580  # optional owner id (put your Telegram ID if you want broadcast control)
# -----------------------------

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load NSFW model (may take time)
logger.info("Loading NSFW model (nsfw-image-detector)...")
MODEL = predict.load_model(None)
logger.info("NSFW model loaded.")

# Multilingual messages
MESSAGES = {
    "en": {
        "deleted_notice": '⚠️ <a href="tg://user?id={user_id}">{name}</a> attempted to send banned media.',
        "deleted_notice_short": '⚠️ @{username} attempted to send banned media.',
        "warn_private": "Your media was removed because it appears to be adult content. Please follow the chat rules.",
        "locked_chat": "🔒 Chat has been locked due to repeated uploads of banned media.",
        "muted_user": "🔇 {name} has been muted for repeated uploads of banned media.",
        "menu_title": "Moderation Menu",
        "moderation_on": "Moderation ON",
        "moderation_off": "Moderation OFF",
        "not_admin": "You must be an admin to use this.",
        "broadcast_prompt": "Send the message to broadcast to all saved chats (admins only).",
        "broadcast_sent": "Broadcast sent to {} chats.",
        "csv_ready": "Admin export ready."
    },
    "tr": {
        "deleted_notice": '⚠️ <a href="tg://user?id={user_id}">{name}</a> yasaklı bir medya gönderdi.',
        "deleted_notice_short": '⚠️ @{username} yasaklı bir medya gönderdi.',
        "warn_private": "Medyanız, yetişkin içeriği gibi göründüğü için kaldırıldı. Lütfen sohbet kurallarına uyun.",
        "locked_chat": "🔒 Sohbet, tekrarlanan yasaklı medya gönderimleri nedeniyle kilitlendi.",
        "muted_user": "🔇 {name} tekrar eden yasaklı medya gönderimleri nedeniyle susturuldu.",
        "menu_title": "Moderasyon Menüsü",
        "moderation_on": "Moderasyon AÇIK",
        "moderation_off": "Moderasyon KAPALI",
        "not_admin": "Bu işlemi yapabilmek için yönetici olmalısınız.",
        "broadcast_prompt": "Tüm kayıtlı sohbetlere gönderilecek mesajı gönderin (sadece admin).",
        "broadcast_sent": "{} sohbete broadcast gönderildi.",
        "csv_ready": "Admin dışa aktarımı hazır."
    },
    "ru": {
        "deleted_notice": '⚠️ <a href="tg://user?id={user_id}">{name}</a> отправил(а) запрещённый медиафайл.',
        "deleted_notice_short": '⚠️ @{username} отправил(а) запрещённый медиафайл.',
        "warn_private": "Ваше медиа было удалено, так как похоже на контент для взрослых.",
        "locked_chat": "🔒 Чат заблокирован из-за повторных загрузок запрещённого медиа.",
        "muted_user": "🔇 {name} был(а) отключён(а) за повторные загрузки запрещённого медиа.",
        "menu_title": "Меню модерации",
        "moderation_on": "Модерация ВКЛ",
        "moderation_off": "Модерация ВЫКЛ",
        "not_admin": "Вы должны быть админом, чтобы использовать это.",
        "broadcast_prompt": "Отправьте сообщение для рассылки всем сохранённым чатам (только админам).",
        "broadcast_sent": "Рассылка отправлена {} чатам.",
        "csv_ready": "Экспорт админов готов."
    }
}

# Helper: choose language (chat override > user language code > default)
def choose_lang(chat_lang, user_lang_code):
    if chat_lang:
        return chat_lang
    if user_lang_code:
        code = user_lang_code.split("-")[0].lower()
        if code in ("tr", "tr-TR"):
            return "tr"
        if code in ("ru",):
            return "ru"
        if code in ("en",):
            return "en"
    return DEFAULT_LANG

# DB init and helpers
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_state (
                chat_id INTEGER PRIMARY KEY,
                moderation INTEGER DEFAULT 1,
                lang TEXT DEFAULT NULL,
                locked INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_counts (
                chat_id INTEGER,
                user_id INTEGER,
                consecutive INTEGER DEFAULT 0,
                last_nsfw_ts INTEGER,
                PRIMARY KEY(chat_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS known_chats (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                is_bot_admin INTEGER DEFAULT 0,
                admin_count INTEGER DEFAULT 0
            )
        """)
        await db.commit()

async def get_chat_state(chat_id):
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT moderation, lang, locked FROM chat_state WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        if row:
            return {"moderation": bool(row[0]), "lang": row[1], "locked": bool(row[2])}
        else:
            return {"moderation": True, "lang": None, "locked": False}

async def set_chat_lang(chat_id, lang):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT INTO chat_state(chat_id, lang) VALUES(?, ?) ON CONFLICT(chat_id) DO UPDATE SET lang=excluded.lang", (chat_id, lang))
        await db.commit()

async def set_moderation(chat_id, onoff: bool):
    async with aiosqlite.connect(DB_FILE) as db:
        val = 1 if onoff else 0
        await db.execute("INSERT INTO chat_state(chat_id, moderation) VALUES(?, ?) ON CONFLICT(chat_id) DO UPDATE SET moderation=excluded.moderation", (chat_id, val))
        await db.commit()

async def set_chat_locked(chat_id, locked: bool):
    async with aiosqlite.connect(DB_FILE) as db:
        val = 1 if locked else 0
        await db.execute("INSERT INTO chat_state(chat_id, locked) VALUES(?, ?) ON CONFLICT(chat_id) DO UPDATE SET locked=excluded.locked", (chat_id, val))
        await db.commit()

async def incr_user_count(chat_id, user_id):
    now = int(datetime.utcnow().timestamp())
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT consecutive FROM user_counts WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        row = await cur.fetchone()
        if row:
            new = row[0] + 1
            await db.execute("UPDATE user_counts SET consecutive=?, last_nsfw_ts=? WHERE chat_id=? AND user_id=?", (new, now, chat_id, user_id))
        else:
            new = 1
            await db.execute("INSERT INTO user_counts(chat_id, user_id, consecutive, last_nsfw_ts) VALUES(?,?,?,?)", (chat_id, user_id, 1, now))
        await db.commit()
    return new

async def reset_user_count(chat_id, user_id):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM user_counts WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        await db.commit()

async def register_chat_info(chat_id, title, is_bot_admin, admin_count):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO known_chats(chat_id, title, is_bot_admin, admin_count) VALUES(?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, is_bot_admin=excluded.is_bot_admin, admin_count=excluded.admin_count",
            (chat_id, title, int(bool(is_bot_admin)), admin_count)
        )
        await db.commit()

# util: mention user
def mention_user_html(user):
    if user.username:
        return f"@{user.username}"
    name = (user.first_name or "") + (" " + (user.last_name or ""))
    return f'<a href="tg://user?id={user.id}">{name.strip()}</a>'

# Build main menu inline keyboard
def main_menu_markup(lang):
    texts = {
        "en": ["Toggle Moderation", "Set Language", "Admin Menu", "Stats", "Export Admins"],
        "tr": ["Moderasyonu Aç/Kapa", "Dili Ayarla", "Admin Menüsü", "İstatistikler", "Adminleri Dışa Aktar"],
        "ru": ["Вкл/Выкл модерацию", "Установить язык", "Меню админа", "Статистика", "Экспорт админов"]
    }
    t = texts.get(lang, texts["tr"])
    kb = [
        [InlineKeyboardButton(t[0], callback_data="toggle_mod")],
        [InlineKeyboardButton(t[1], callback_data="set_lang")],
        [InlineKeyboardButton(t[2], callback_data="admin_menu")],
        [InlineKeyboardButton(t[3], callback_data="stats")],
        [InlineKeyboardButton(t[4], callback_data="export_admins")]
    ]
    return InlineKeyboardMarkup(kb)

# Admin menu keyboard
def admin_menu_markup(lang):
    texts = {
        "en": ["Broadcast (all chats)", "Send to ID", "Reset Counters"],
        "tr": ["Toplu Mesaj (tüm sohbetler)", "ID'ye Gönder", "Sayaçları Sıfırla"],
        "ru": ["Рассылка (все чаты)", "Отправить по ID", "Сбросить счётчики"]
    }
    t = texts.get(lang, texts["tr"])
    kb = [
        [InlineKeyboardButton(t[0], callback_data="admin_broadcast")],
        [InlineKeyboardButton(t[1], callback_data="admin_send_id")],
        [InlineKeyboardButton(t[2], callback_data="admin_reset_counters")],
        [InlineKeyboardButton("🔙", callback_data="menu_back")]
    ]
    return InlineKeyboardMarkup(kb)

# -------------------------
# Handlers
# -------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"{BOT_NAME} active. Use /menu in a group to open moderation menu.")

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only in groups
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text("This bot is for group moderation. Add it to a group and run /menu there.")
        return
    chat = update.effective_chat
    # get chat lang and moderation state
    state = await get_chat_state(chat.id)
    lang = choose_lang(state.get("lang"), update.effective_user.language_code)
    await register_chat_on_interaction(context.application, chat)
    title = MESSAGES[lang]["menu_title"]
    await update.message.reply_text(title, reply_markup=main_menu_markup(lang))

async def register_chat_on_interaction(app, chat):
    # Check if bot is admin in chat and admin count
    try:
        member = await app.bot.get_chat_member(chat.id, app.bot.id)
        is_admin = member.status in ("administrator", "creator")
        # count admins
        admins = await app.bot.get_administrators(chat.id)
        admin_count = len(admins)
        await register_chat_info(chat.id, chat.title or str(chat.id), is_admin, admin_count)
    except Exception:
        # maybe bot not admin or private or error
        await register_chat_info(chat.id, chat.title or str(chat.id), False, 0)

# Callback query handler for inline menu
async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    chat = q.message.chat
    user = q.from_user

    state = await get_chat_state(chat.id)
    lang = choose_lang(state.get("lang"), user.language_code)

    # ensure user is admin for managerial actions
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        is_admin = member.status in ("administrator", "creator")
    except Exception:
        is_admin = False

    if data == "toggle_mod":
        if not is_admin:
            await q.edit_message_text(MESSAGES[lang]["not_admin"])
            return
        new = not state["moderation"]
        await set_moderation(chat.id, new)
        text = MESSAGES[lang]["moderation_on"] if new else MESSAGES[lang]["moderation_off"]
        await q.edit_message_text(text, reply_markup=main_menu_markup(lang))
        return

    if data == "set_lang":
        # present language options
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Türkçe", callback_data="lang_tr"),
             InlineKeyboardButton("English", callback_data="lang_en"),
             InlineKeyboardButton("Русский", callback_data="lang_ru")],
            [InlineKeyboardButton("🔙", callback_data="menu_back")]
        ])
        await q.edit_message_text("Select language / Dil seç / Выберите язык", reply_markup=kb)
        return

    if data.startswith("lang_"):
        if not is_admin:
            await q.edit_message_text(MESSAGES[lang]["not_admin"])
            return
        chosen = data.split("_", 1)[1]
        await set_chat_lang(chat.id, chosen)
        await q.edit_message_text(MESSAGES[chosen]["lang_set"], reply_markup=main_menu_markup(chosen))
        return

    if data == "admin_menu":
        if not is_admin:
            await q.edit_message_text(MESSAGES[lang]["not_admin"])
            return
        await q.edit_message_text("Admin Menu", reply_markup=admin_menu_markup(lang))
        return

    if data == "admin_broadcast":
        if not is_admin:
            await q.edit_message_text(MESSAGES[lang]["not_admin"])
            return
        await q.edit_message_text(MESSAGES[lang]["broadcast_prompt"])
        # set a flag in user_data to receive next message as broadcast
        context.user_data["awaiting_broadcast"] = True
        return

    if data == "admin_send_id":
        if not is_admin:
            await q.edit_message_text(MESSAGES[lang]["not_admin"])
            return
        await q.edit_message_text("Send message in the form: <chat_id_or_user_id>|<message>")
        context.user_data["awaiting_send_id"] = True
        return

    if data == "admin_reset_counters":
        if not is_admin:
            await q.edit_message_text(MESSAGES[lang]["not_admin"])
            return
        await q.edit_message_text("Send user_id to reset counters for (or 'all' to clear all).")
        context.user_data["awaiting_reset"] = True
        return

    if data == "stats":
        # simple stats: number of known chats
        async with aiosqlite.connect(DB_FILE) as db:
            cur = await db.execute("SELECT COUNT(*) FROM known_chats")
            cnt = (await cur.fetchone())[0]
        await q.edit_message_text(f"Known chats: {cnt}", reply_markup=main_menu_markup(lang))
        return

    if data == "export_admins":
        # export known_chats to CSV
        async with aiosqlite.connect(DB_FILE) as db:
            cur = await db.execute("SELECT chat_id, title, is_bot_admin, admin_count FROM known_chats")
            rows = await cur.fetchall()
        bio = io.StringIO()
        writer = csv.writer(bio)
        writer.writerow(["chat_id", "title", "is_bot_admin", "admin_count"])
        for r in rows:
            writer.writerow(r)
        bio.seek(0)
        await context.bot.send_document(chat.id, document=InputFile(bio, filename="known_chats.csv"), caption=MESSAGES[lang]["csv_ready"])
        await q.message.delete()
        return

    if data == "menu_back":
        await q.edit_message_text(MESSAGES[lang]["menu_title"], reply_markup=main_menu_markup(lang))
        return

# Message handler for awaiting admin actions
async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user
    chat = msg.chat

    # check awaiting broadcast
    if context.user_data.get("awaiting_broadcast"):
        # send to all known chats
        async with aiosqlite.connect(DB_FILE) as db:
            cur = await db.execute("SELECT chat_id FROM known_chats")
            rows = await cur.fetchall()
        count = 0
        for r in rows:
            try:
                await context.bot.send_message(r[0], msg.text)
                count += 1
            except Exception:
                pass
        await msg.reply_text(MESSAGES[choose_lang(None, user.language_code)]["broadcast_sent"].format(count))
        context.user_data.pop("awaiting_broadcast", None)
        return

    if context.user_data.get("awaiting_send_id"):
        text = msg.text.strip()
        if "|" not in text:
            await msg.reply_text("Format error. Use: <id>|<message>")
            return
        sid, message = text.split("|", 1)
        try:
            sid = int(sid.strip())
            await context.bot.send_message(sid, message.strip())
            await msg.reply_text("Sent.")
        except Exception as e:
            await msg.reply_text(f"Failed: {e}")
        context.user_data.pop("awaiting_send_id", None)
        return

    if context.user_data.get("awaiting_reset"):
        target = msg.text.strip()
        if target.lower() == "all":
            async with aiosqlite.connect(DB_FILE) as db:
                await db.execute("DELETE FROM user_counts")
                await db.commit()
            await msg.reply_text("All counters cleared.")
        else:
            try:
                uid = int(target)
                async with aiosqlite.connect(DB_FILE) as db:
                    await db.execute("DELETE FROM user_counts WHERE user_id=?", (uid,))
                    await db.commit()
                await msg.reply_text(f"Counters reset for {uid}.")
            except Exception:
                await msg.reply_text("Invalid id.")
        context.user_data.pop("awaiting_reset", None)
        return

# Media handler - photos/videos/documents
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    chat = msg.chat
    # only process in groups/supergroups
    if chat.type == ChatType.PRIVATE:
        return

    # register chat
    await register_chat_on_interaction(context.application, chat)

    # get chat state
    state = await get_chat_state(chat.id)
    lang = choose_lang(state.get("lang"), msg.from_user.language_code)
    if state.get("locked"):
        # chat locked -> ignore
        return
    if not state.get("moderation", True):
        return

    # find media file (photo/video/document)
    file_obj = None
    fname = f"tmp_{msg.message_id}"
    try:
        if msg.photo:
            # biggest photo
            p = msg.photo[-1]
            file_obj = await p.get_file()
            fname += ".jpg"
        elif msg.video:
            file_obj = await msg.video.get_file()
            fname += ".mp4"
        elif msg.document:
            file_obj = await msg.document.get_file()
            # try keep extension
            if msg.document.file_name:
                ext = os.path.splitext(msg.document.file_name)[1]
                fname += ext or ".bin"
            else:
                fname += ".bin"
        else:
            return
    except Exception as e:
        logger.exception("Failed to get file: %s", e)
        return

    # download
    try:
        await file_obj.download_to_drive(fname)
    except Exception as e:
        logger.exception("Download failed: %s", e)
        return

    # predict (run in executor)
    loop = asyncio.get_event_loop()
    predict_func = partial(predict.classify, MODEL, fname)
    try:
        res = await loop.run_in_executor(None, predict_func)
    except Exception as e:
        logger.exception("Prediction failed: %s", e)
        res = {}
    # cleanup file
    try:
        os.remove(fname)
    except Exception:
        pass

    # parse result
    score = 0.0
    if isinstance(res, dict):
        vals = list(res.values())
        if vals and isinstance(vals[0], dict):
            v = vals[0]
            porn = v.get("porn", 0.0)
            sexy = v.get("sexy", 0.0)
            hentai = v.get("hentai", 0.0)
            score = max(porn, sexy * 0.8, hentai)
    logger.info("NSFW score for msg %s in chat %s: %s", msg.message_id, chat.id, score)

    if score >= NSFW_THRESHOLD:
        # delete message
        try:
            await context.bot.delete_message(chat.id, msg.message_id)
        except Exception:
            pass

        # increment user counter
        count = await incr_user_count(chat.id, msg.from_user.id)

        # send group notice (mention) - try html mention
        try:
            notice = MESSAGES[lang]["deleted_notice"].format(user_id=msg.from_user.id, name=msg.from_user.first_name)
            await context.bot.send_message(chat.id, notice, parse_mode=ParseMode.HTML)
        except Exception:
            short = MESSAGES[lang]["deleted_notice_short"].format(username=msg.from_user.username or str(msg.from_user.id))
            await context.bot.send_message(chat.id, short)

        # try private warn
        try:
            await context.bot.send_message(msg.from_user.id, MESSAGES[lang]["warn_private"])
        except Exception:
            pass

        # offer admin quick actions (in group) - inline keyboard under a small message
        try:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Mute user", callback_data=f"quick_mute:{chat.id}:{msg.from_user.id}"),
                 InlineKeyboardButton("Ignore", callback_data=f"quick_ignore:{chat.id}:{msg.from_user.id}")],
            ])
            await context.bot.send_message(chat.id, f"Admin actions for {mention_user_html(msg.from_user)}", parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass

        # if exceeds limit -> mute and lock chat
        if count >= CONSECUTIVE_LIMIT:
            # mute user
            until = int((datetime.utcnow() + timedelta(seconds=MUTE_DURATION_SEC)).timestamp())
            try:
                await context.bot.restrict_chat_member(chat.id, msg.from_user.id,
                                                       permissions=ChatPermissions(can_send_messages=False),
                                                       until_date=until)
            except Exception:
                pass
            # lock chat (remove send permissions for everyone except admins)
            perms = ChatPermissions(can_send_messages=False, can_send_media_messages=False, can_send_polls=False,
                                    can_send_other_messages=False, can_add_web_page_previews=False)
            try:
                await context.bot.set_chat_permissions(chat.id, perms)
                await set_chat_locked(chat.id, True)
            except Exception:
                pass
            # notify
            try:
                await context.bot.send_message(chat.id, MESSAGES[lang]["muted_user"].format(name=msg.from_user.first_name))
                await context.bot.send_message(chat.id, MESSAGES[lang]["locked_chat"])
            except Exception:
                pass
            # reset counter
            await reset_user_count(chat.id, msg.from_user.id)
    else:
        # safe media -> reset consecutive counter for this user
        await reset_user_count(chat.id, msg.from_user.id)

# Quick admin action callbacks (mute/ignore)
async def quick_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    # data format: quick_mute:chat_id:user_id or quick_ignore:...
    try:
        action, chat_id, user_id = data.split(":")
        chat_id = int(chat_id); user_id = int(user_id)
    except Exception:
        return
    # check if caller is admin
    caller = q.from_user
    try:
        member = await context.bot.get_chat_member(chat_id, caller.id)
        if member.status not in ("administrator", "creator"):
            await q.edit_message_text("Admin only.")
            return
    except Exception:
        await q.edit_message_text("Admin check failed.")
        return

    if action == "quick_mute":
        until = int((datetime.utcnow() + timedelta(seconds=MUTE_DURATION_SEC)).timestamp())
        try:
            await context.bot.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions(can_send_messages=False), until_date=until)
            await q.edit_message_text("User muted.")
        except Exception as e:
            await q.edit_message_text(f"Failed: {e}")
    elif action == "quick_ignore":
        await q.edit_message_text("Ignored.")
    else:
        await q.edit_message_text("Unknown action.")

# When bot starts: init DB
async def main():
    await init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(CallbackQueryHandler(quick_action_callback, pattern=r"^quick_"))
    # admin awaiting/inline text
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_message_handler))
    # media handler
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, media_handler))

    logger.info("Starting bot...")
    await app.start()
    await app.updater.start_polling()
    await app.idle()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
