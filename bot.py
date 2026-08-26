import asyncio
import os
import sqlite3
from datetime import datetime
from html import escape

import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import *

DB_FILE = os.getenv("DB_FILE", "bot.db")

# ---------------- DATABASE ----------------
def db_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            joined TEXT NOT NULL,
            searches INTEGER DEFAULT 0,
            bonus INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            referred INTEGER DEFAULT 0,
            blocked INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tmdb_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            filename TEXT DEFAULT '',
            file_id TEXT NOT NULL,
            file_type TEXT NOT NULL DEFAULT 'document',
            caption TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        );
        """)
    conn.commit()
    conn.close()


def setting(key, default=""):
    conn = db_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key, value):
    conn = db_conn()
    conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()
    conn.close()


def add_user(user_id, name, ref=None):
    conn = db_conn()
    row = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO users(id,name,joined,searches,bonus) VALUES(?,?,?,?,?)",
            (user_id, name, str(datetime.now().date()), START_SEARCH, 0),
        )
        if ref and ref != user_id:
            ref_row = conn.execute("SELECT id FROM users WHERE id=?", (ref,)).fetchone()
            if ref_row:
                conn.execute("UPDATE users SET referrals=referrals+1, bonus=bonus+? WHERE id=?", (REF_BONUS, ref))
                conn.execute("UPDATE users SET referred=1 WHERE id=?", (user_id,))
    else:
        conn.execute("UPDATE users SET name=? WHERE id=?", (name, user_id))
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = db_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return row


def consume_search(user_id):
    conn = db_conn()
    row = conn.execute("SELECT searches,bonus FROM users WHERE id=?", (user_id,)).fetchone()
    if not row or row["searches"] + row["bonus"] <= 0:
        conn.close()
        return False
    if row["bonus"] > 0:
        conn.execute("UPDATE users SET bonus=bonus-1 WHERE id=?", (user_id,))
    else:
        conn.execute("UPDATE users SET searches=searches-1 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return True


# ---------------- FORCE JOIN ----------------
async def check_join(bot, uid):
    try:
        for ch in CHANNELS:
            member = await bot.get_chat_member(ch, uid)
            if member.status in {"left", "kicked"}:
                return False
        return True
    except Exception:
        return False


def join_keyboard():
    rows = []
    for i, ch in enumerate(CHANNELS, 1):
        username = ch.lstrip("@")
        rows.append([InlineKeyboardButton(f"📢 Channel {i}", url=f"https://t.me/{username}")])
    rows.append([InlineKeyboardButton("✅ VERIFY", callback_data="verify")])
    return InlineKeyboardMarkup(rows)


# ---------------- COMMON UI ----------------
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Movies", callback_data="mode_movie"), InlineKeyboardButton("📺 Web Series", callback_data="mode_series")],
        [InlineKeyboardButton("🌸 Anime", callback_data="mode_anime"), InlineKeyboardButton("👥 Invite", callback_data="invite")],
        [InlineKeyboardButton("📊 My Stats", callback_data="stats"), InlineKeyboardButton("📩 Movie Request", callback_data="request")],
    ] + ([[InlineKeyboardButton("🌐 Web Link", url=WEB_LINK)]] if WEB_LINK else []))


def brand_text(name):
    return f"""╔══════════════════════════════════╗
║      🎬  I M D B   M O V I E   R O B O T
╚══════════════════════════════════╝

Hey {escape(name)}! 👋

🎬 Movies • 📺 Web Series • 🌸 Anime
🔎 Search with TMDB metadata
📁 Files are delivered directly by the bot

Choose an option below 👇"""


# ---------------- START / GATE ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.effective_user.first_name or "User"
    ref = None
    if context.args:
        raw = context.args[0].replace("ref_", "")
        if raw.isdigit():
            ref = int(raw)
    add_user(uid, name, ref)

    popup = setting("popup", "")
    if popup and uid != ADMIN_ID:
        await update.message.reply_text(
            popup,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ I Understand / Continue", callback_data="popup_ok")]])
        )
        return

    await show_gate(update, context)


async def show_gate(update, context):
    name = update.effective_user.first_name or "User"
    text = brand_text(name) + "\n\n📌 Join the required channels, then tap VERIFY."
    await update.effective_message.reply_text(text, reply_markup=join_keyboard(), parse_mode=ParseMode.HTML)


async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await check_join(context.bot, q.from_user.id):
        await q.answer("Join all required channels first ❌", show_alert=True)
        return
    await q.message.edit_text(brand_text(q.from_user.first_name or "User"), reply_markup=main_keyboard(), parse_mode=ParseMode.HTML)


# ---------------- TMDB ----------------
async def tmdb_get(path, params=None):
    base = "https://api.themoviedb.org/3"
    p = dict(params or {})
    p["api_key"] = TMDB_API_KEY
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(base + path, params=p) as r:
            if r.status != 200:
                return {}
            return await r.json()


async def search_tmdb(query, mode):
    data = await tmdb_get("/search/multi", {"query": query, "include_adult": "false", "language": "en-US"})
    results = []
    for item in data.get("results", []):
        media = item.get("media_type")
        if mode == "movie" and media != "movie":
            continue
        if mode == "series" and media != "tv":
            continue
        if mode == "anime" and media not in {"tv", "movie"}:
            continue
        if not (item.get("title") or item.get("name")):
            continue
        results.append(item)
    return results[:8]


async def media_details(tmdb_id):
    movie = await tmdb_get(f"/movie/{tmdb_id}", {"append_to_response": "external_ids"})
    if movie.get("id"):
        return movie, "movie"
    tv = await tmdb_get(f"/tv/{tmdb_id}", {"append_to_response": "external_ids"})
    return tv, "tv"


def year_of(m):
    return (m.get("release_date") or m.get("first_air_date") or "")[:4]


def title_of(m):
    return m.get("title") or m.get("name") or "Unknown"


def file_caption(file_row, meta):
    title = file_row["title"]
    filename = file_row["filename"] or title
    if file_row["caption"]:
        return file_row["caption"]
    return f"📂 {escape(filename)}\n\n🔊 #Hindi\n\n⚠️ Use VLC Player to avoid sound issues & switch languages"


# ---------------- USER SEARCH ----------------
async def search_prompt(update, context, mode):
    context.user_data["mode"] = mode
    prompts = {"movie": "🎬 Send Movie Name:", "series": "📺 Send Web Series Name:", "anime": "🌸 Send Anime Name:"}
    await update.effective_message.reply_text(prompts[mode])


async def callback_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = q.from_user.id
    add_user(uid, q.from_user.first_name or "User")

    if data == "verify":
        return await verify(update, context)
    if data == "popup_ok":
        return await show_gate(update, context)
    if data.startswith("mode_"):
        return await search_prompt(update, context, data.split("_", 1)[1])
    if data == "stats":
        u = get_user(uid)
        await q.message.reply_text(f"📊 <b>Your Stats</b>\n\n👤 {escape(u['name'])}\n🆔 {uid}\n🔍 Searches: {u['searches'] + u['bonus']}\n├ 🆓 Free: {u['searches']}\n└ 🎁 Bonus: {u['bonus']}\n👥 Referrals: {u['referrals']}\n📅 Joined: {u['joined']}", parse_mode=ParseMode.HTML)
        return
    if data == "invite":
        bot = await context.bot.get_me()
        u = get_user(uid)
        link = f"https://t.me/{bot.username}?start=ref_{uid}"
        await q.message.reply_text(f"👥 <b>Invite Friends</b>\n\n🔗 {link}\n\n👫 Invited: {u['referrals']}\n🎁 Bonus: {u['bonus']}\n\nEvery successful referral gives +{REF_BONUS} searches.", parse_mode=ParseMode.HTML)
        return
    if data == "request":
        context.user_data["mode"] = "request"
        await q.message.reply_text("📩 Send the movie/series request. It will be forwarded to admin.")
        return
    if data.startswith("pick:"):
        tmdb_id = int(data.split(":", 1)[1])
        return await show_title(update, context, tmdb_id)
    if data.startswith("file:"):
        file_db_id = int(data.split(":", 1)[1])
        return await send_file(update, context, file_db_id)
    if data == "admin":
        return await admin_panel(update, context)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    add_user(uid, update.effective_user.first_name or "User")
    mode = context.user_data.get("mode")
    text = update.message.text.strip()

    if mode == "request":
        await context.bot.send_message(ADMIN_ID, f"📩 Request from {uid}:\n{text}")
        context.user_data.clear()
        await update.message.reply_text("✅ Request sent to admin.")
        return

    if mode not in {"movie", "series", "anime"}:
        await update.message.reply_text("Use the buttons below 👇", reply_markup=main_keyboard())
        return

    if not await check_join(context.bot, uid):
        await update.message.reply_text("❌ Please join the required channels first.", reply_markup=join_keyboard())
        return

    if not consume_search(uid):
        u = get_user(uid)
        bot = await context.bot.get_me()
        link = f"https://t.me/{bot.username}?start=ref_{uid}"
        await update.message.reply_text(f"🎬 No searches left.\n\n🎁 Invite friends to earn more.\n🔗 {link}")
        return

    results = await search_tmdb(text, mode)
    if not results:
        await update.message.reply_text("❌ No results found.")
        return

    buttons = []
    for item in results:
        label = item.get("title") or item.get("name")
        buttons.append([InlineKeyboardButton(label[:60], callback_data=f"pick:{item['id']}")])
    await update.message.reply_text("🔎 Select a title:", reply_markup=InlineKeyboardMarkup(buttons))


# ---------------- TITLE / FILE DELIVERY ----------------
async def show_title(update, context, tmdb_id):
    q = update.callback_query
    await q.answer()
    meta, media_type = await media_details(tmdb_id)
    if not meta:
        await q.message.reply_text("❌ Metadata unavailable.")
        return

    title = title_of(meta)
    year = year_of(meta) or "N/A"
    rating = meta.get("vote_average")
    overview = (meta.get("overview") or "No overview available.").strip()
    imdb = (meta.get("external_ids") or {}).get("imdb_id")

    conn = db_conn()
    rows = conn.execute("SELECT * FROM files WHERE tmdb_id=? ORDER BY id DESC", (tmdb_id,)).fetchall()
    conn.close()

    rating_text = f"{rating:.1f}" if isinstance(rating, (int, float)) else "N/A"
    text = f"🎬 <b>{escape(title)} ({escape(year)})</b>\n⭐ Rating: {rating_text}\n\n📝 {escape(overview[:500])}"
    if imdb:
        text += f"\n\n🔗 <a href=\"https://www.imdb.com/title/{imdb}/\">IMDb</a>"
    text += "\n\n📁 Available files:"

    buttons = []
    if rows:
        for row in rows:
            label = row["filename"] or row["title"]
            buttons.append([InlineKeyboardButton(f"📂 {label[:55]}", callback_data=f"file:{row['id']}")])
    else:
        text += "\nNo file has been added by the admin yet."
    await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)


async def send_file(update, context, file_db_id):
    q = update.callback_query
    await q.answer()
    conn = db_conn()
    row = conn.execute("SELECT * FROM files WHERE id=?", (file_db_id,)).fetchone()
    conn.close()
    if not row:
        await q.message.reply_text("❌ File no longer available.")
        return

    caption = file_caption(row, None)
    warning = await q.message.reply_text("⚠️ <b>Deleting in 30s, save quickly…</b>", parse_mode=ParseMode.HTML)
    if row["file_type"] == "video":
        sent = await context.bot.send_video(q.message.chat_id, row["file_id"], caption=caption, supports_streaming=True)
    else:
        sent = await context.bot.send_document(q.message.chat_id, row["file_id"], caption=caption)
    await context.bot.send_message(q.message.chat_id, "💾 <b>Save tip:</b> tap ⋮ on the file and choose <b>Save to Saved Messages</b>.", parse_mode=ParseMode.HTML)

    async def delete_later():
        await asyncio.sleep(30)
        for msg in (sent, warning):
            try:
                await msg.delete()
            except Exception:
                pass

    asyncio.create_task(delete_later())


# ---------------- ADMIN ----------------
ADMIN_MENU = "admin_menu"
ADMIN_BROADCAST = "admin_broadcast"
ADMIN_POPUP = "admin_popup"
ADMIN_ADD_TM = "admin_add_tm"
ADMIN_ADD_FILE = "admin_add_file"


def is_admin(uid):
    return uid == ADMIN_ID


async def admin_panel(update, context):
    if not is_admin(update.effective_user.id):
        if update.callback_query:
            await update.callback_query.answer("Admin only ❌", show_alert=True)
        return
    text = """🛠️ <b>IMDB MOVIE ROBOT — ADMIN PANEL</b>\n\nChoose an action:"""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Broadcast", callback_data="a_broadcast"), InlineKeyboardButton("📌 Popup Message", callback_data="a_popup")],
        [InlineKeyboardButton("➕ Add File", callback_data="a_addfile"), InlineKeyboardButton("📊 Stats", callback_data="a_stats")],
        [InlineKeyboardButton("🗑 Clear Popup", callback_data="a_clearpopup")],
    ])
    if update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def admin_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await admin_panel(update, context)


async def admin_actions(update, context):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    if q.data == "a_broadcast":
        context.user_data["admin_state"] = ADMIN_BROADCAST
        await q.message.reply_text("📢 Send the broadcast text. HTML formatting is supported.")
    elif q.data == "a_popup":
        context.user_data["admin_state"] = ADMIN_POPUP
        await q.message.reply_text("📌 Send the message users must see on /start. Send /skip to disable it.")
    elif q.data == "a_clearpopup":
        set_setting("popup", "")
        await q.message.reply_text("✅ Popup disabled.")
    elif q.data == "a_stats":
        conn = db_conn()
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        conn.close()
        await q.message.reply_text(f"📊 Users: {users}\n📁 Files: {files}")
    elif q.data == "a_addfile":
        context.user_data["admin_state"] = ADMIN_ADD_TM
        await q.message.reply_text("➕ Send the TMDB ID for the movie/series, e.g. 12345")


async def admin_media_handler(update, context):
    if not is_admin(update.effective_user.id):
        return
    state = context.user_data.get("admin_state")
    if not state:
        return
    text = update.message.text.strip() if update.message.text else ""

    if state == ADMIN_BROADCAST:
        conn = db_conn()
        ids = [r[0] for r in conn.execute("SELECT id FROM users WHERE blocked=0").fetchall()]
        conn.close()
        ok = 0
        for uid in ids:
            try:
                await context.bot.send_message(uid, text, parse_mode=ParseMode.HTML)
                ok += 1
                await asyncio.sleep(0.04)
            except Exception:
                pass
        context.user_data.pop("admin_state", None)
        await update.message.reply_text(f"✅ Broadcast finished: {ok}/{len(ids)}")
        return

    if state == ADMIN_POPUP:
        if text == "/skip":
            set_setting("popup", "")
            await update.message.reply_text("✅ Popup disabled.")
        else:
            set_setting("popup", text)
            await update.message.reply_text("✅ Popup saved.")
        context.user_data.pop("admin_state", None)
        return

    if state == ADMIN_ADD_TM:
        if not text.isdigit():
            await update.message.reply_text("❌ TMDB ID must be a number.")
            return
        context.user_data["admin_tmdb_id"] = int(text)
        context.user_data["admin_state"] = ADMIN_ADD_FILE
        await update.message.reply_text("Now send the file as a Telegram Document or Video. Its filename will be used as the display name.")
        return


async def admin_file_handler(update, context):
    if not is_admin(update.effective_user.id) or context.user_data.get("admin_state") != ADMIN_ADD_FILE:
        return
    tmdb_id = context.user_data.get("admin_tmdb_id")
    if not tmdb_id:
        return

    file_id = None
    file_type = None
    filename = ""
    if update.message.document:
        file_id = update.message.document.file_id
        file_type = "document"
        filename = update.message.document.file_name or "File"
    elif update.message.video:
        file_id = update.message.video.file_id
        file_type = "video"
        filename = update.message.video.file_name or "Video"
    else:
        await update.message.reply_text("❌ Send a Telegram video or document.")
        return

    meta, _ = await media_details(tmdb_id)
    title = title_of(meta) if meta else filename
    conn = db_conn()
    conn.execute("INSERT INTO files(tmdb_id,title,filename,file_id,file_type,created_at) VALUES(?,?,?,?,?,?)", (tmdb_id, title, filename, file_id, file_type, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    context.user_data.pop("admin_state", None)
    context.user_data.pop("admin_tmdb_id", None)
    await update.message.reply_text(f"✅ File added for <b>{escape(title)}</b>.", parse_mode=ParseMode.HTML)


async def error_handler(update, context):
    print("ERROR:", context.error)


# ---------------- MAIN ----------------
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(admin_actions, pattern=r"^a_"))
    app.add_handler(CallbackQueryHandler(callback_menu, pattern=r"^(verify|popup_ok|mode_|stats|invite|request|pick:|file:|admin$)"))
    app.add_handler(MessageHandler((filters.Document.ALL | filters.VIDEO) & ~filters.COMMAND, admin_file_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_media_handler), group=0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler), group=1)
    app.add_error_handler(error_handler)

    print("🔥 IMDB Movie Robot running")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
