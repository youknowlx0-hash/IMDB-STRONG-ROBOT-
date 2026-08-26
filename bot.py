import asyncio
import logging
import sqlite3
import aiohttp

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import (
    BOT_TOKEN,
    TMDB_API_KEY,
    ADMIN_ID,
    CHANNELS,
    BOT_NAME,
    DELETE_AFTER_SECONDS,
    SAVE_TUTORIAL_VIDEO_FILE_ID,
    WEB_LINK,
)

from database import (
    init_db,
    add_user,
    block_user,
    get_all_users,
    user_count,
    add_media,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SEARCH_CACHE = {}


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def main_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🔎 Search Movie", callback_data="search_help")],
        [InlineKeyboardButton("📢 Updates Channel", url="https://t.me/webSeriesUpdater")],
    ]
    if WEB_LINK:
        rows.append([InlineKeyboardButton("🌐 Web Link", url=WEB_LINK)])
    return InlineKeyboardMarkup(rows)


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Stats", callback_data="admin_stats"),
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
        ],
        [InlineKeyboardButton("⚠️ Popup", callback_data="admin_popup")],
    ])


async def check_membership(bot, user_id: int) -> bool:
    if not CHANNELS:
        return True

    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception as exc:
            logger.warning("Membership check failed for %s: %s", channel, exc)
            return False
    return True


def join_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for channel in CHANNELS:
        username = channel.lstrip("@")
        rows.append([
            InlineKeyboardButton(
                f"📢 Join @{username}",
                url=f"https://t.me/{username}",
            )
        ])
    rows.append([
        InlineKeyboardButton("✅ I've Joined", callback_data="check_join")
    ])
    return InlineKeyboardMarkup(rows)


async def tmdb_request(endpoint: str, params: dict):
    if not TMDB_API_KEY:
        raise RuntimeError("TMDB_API_KEY missing in config.py")

    url = f"https://api.themoviedb.org/3/{endpoint}"
    request_params = dict(params)
    request_params["api_key"] = TMDB_API_KEY

    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=request_params) as response:
            if response.status != 200:
                logger.error("TMDB HTTP %s for %s", response.status, endpoint)
                return None
            return await response.json()


async def search_movie(query: str):
    data = await tmdb_request(
        "search/multi",
        {
            "query": query,
            "language": "en-US",
            "include_adult": "false",
        },
    )

    if not data:
        return []

    results = []
    for item in data.get("results", []):
        media_type = item.get("media_type")
        if media_type not in ("movie", "tv"):
            continue

        title = item.get("title") or item.get("name") or "Unknown"
        date = item.get("release_date") or item.get("first_air_date") or ""

        results.append({
            "id": item.get("id"),
            "type": media_type,
            "title": title,
            "date": date,
            "poster": item.get("poster_path"),
        })

    return results[:10]


async def get_details(tmdb_id: int, media_type: str):
    endpoint = f"movie/{tmdb_id}" if media_type == "movie" else f"tv/{tmdb_id}"
    return await tmdb_request(endpoint, {"language": "en-US"})


async def get_external_ids(tmdb_id: int, media_type: str):
    endpoint = (
        f"movie/{tmdb_id}/external_ids"
        if media_type == "movie"
        else f"tv/{tmdb_id}/external_ids"
    )
    return await tmdb_request(endpoint, {})


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    add_user(
        user.id,
        user.username,
        user.first_name,
    )

    if not await check_membership(context.bot, user.id):
        await update.message.reply_text(
            "🔐 <b>Join Required</b>\n\n"
            "Bot use karne ke liye required channels join karo.\n\n"
            "Join karne ke baad <b>I've Joined</b> dabao.",
            parse_mode=ParseMode.HTML,
            reply_markup=join_keyboard(),
        )
        return

    await update.message.reply_text(
        f"🎬 <b>{BOT_NAME}</b>\n\n"
        "🔎 Movie / Web Series ka naam bhejo.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await check_membership(context.bot, query.from_user.id):
        await query.answer(
            "❌ Pehle sabhi channels join karo.",
            show_alert=True,
        )
        return

    await query.edit_message_text(
        "✅ Verification successful!\n\n"
        "Ab movie/web-series ka naam bhejo."
    )


async def search_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "🔎 Movie ya Web Series ka exact/partial naam bhejo."
    )


async def text_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message

    if not message or not message.text:
        return

    if not await check_membership(context.bot, user.id):
        await message.reply_text(
            "⚠️ Pehle required channels join karo.",
            reply_markup=join_keyboard(),
        )
        return

    text = message.text.strip()
    if not text:
        return

    status = await message.reply_text("🔎 Searching...")

    try:
        results = await search_movie(text)
    except Exception as exc:
        logger.exception("Search failed: %s", exc)
        await status.edit_text("❌ Search service temporarily unavailable.")
        return

    if not results:
        await status.edit_text(
            "❌ Kuch nahi mila.\n\n"
            "Movie/Web Series ka naam thoda different tarike se try karo."
        )
        return

    SEARCH_CACHE[user.id] = results

    buttons = []
    for index, item in enumerate(results):
        year = item["date"][:4] if item["date"] else ""
        label = f"🎬 {item['title']}"
        if year:
            label += f" ({year})"

        buttons.append([
            InlineKeyboardButton(
                label[:60],
                callback_data=f"movie:{index}",
            )
        ])

    await status.edit_text(
        "🔎 <b>Search Results</b>\n\n"
        "Apni movie/web-series select karo:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def movie_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        index = int(query.data.split(":", 1)[1])
        item = SEARCH_CACHE[query.from_user.id][index]
    except (KeyError, IndexError, ValueError):
        await query.edit_message_text(
            "❌ Search expired. Dobara search karo."
        )
        return

    try:
        details = await get_details(item["id"], item["type"])
        external = await get_external_ids(item["id"], item["type"])
    except Exception as exc:
        logger.exception("Details failed: %s", exc)
        await query.edit_message_text("❌ Details nahi mil paayi.")
        return

    if not details:
        await query.edit_message_text("❌ Details nahi mil paayi.")
        return

    imdb_id = external.get("imdb_id") if external else None
    title = details.get("title") or details.get("name") or item["title"]
    rating = float(details.get("vote_average") or 0)
    overview = details.get("overview") or ""
    release = details.get("release_date") or details.get("first_air_date") or "N/A"
    genres = ", ".join(g.get("name", "") for g in details.get("genres", []))

    if len(overview) > 500:
        overview = overview[:500] + "..."

    text = (
        f"🎬 <b>{title}</b>\n\n"
        f"📅 <b>Release:</b> {release}\n"
        f"⭐ <b>Rating:</b> {rating:.1f}/10\n"
        f"🎭 <b>Genre:</b> {genres or 'N/A'}\n"
    )

    if imdb_id:
        text += (
            f"🔗 <b>IMDb:</b> "
            f"https://www.imdb.com/title/{imdb_id}/\n"
        )

    if overview:
        text += f"\n📝 <b>Overview:</b>\n{overview}\n"

    text += "\n━━━━━━━━━━━━━━━━━━\n📂 <b>Available Files</b>"

    files = get_media_for_tmdb(item["id"])
    buttons = []

    for media in files:
        filename = media["file_name"] or "File"
        buttons.append([
            InlineKeyboardButton(
                f"📥 {filename[:45]}",
                callback_data=f"file:{media['id']}",
            )
        ])

    if not files:
        text += "\n\n⚠️ Abhi koi file available nahi hai."

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
    )


def get_media_for_tmdb(tmdb_id: int):
    conn = sqlite3.connect("bot.db")
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """
            SELECT *
            FROM media
            WHERE tmdb_id = ?
            ORDER BY id DESC
            """,
            (tmdb_id,),
        ).fetchall()
    finally:
        conn.close()


def get_media_by_id(media_id: int):
    conn = sqlite3.connect("bot.db")
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM media WHERE id = ?",
            (media_id,),
        ).fetchone()
    finally:
        conn.close()


async def send_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        media_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("❌ Invalid file.", show_alert=True)
        return

    media = get_media_by_id(media_id)

    if not media:
        await query.answer(
            "❌ File unavailable.",
            show_alert=True,
        )
        return

    user_id = query.from_user.id

    warning = await context.bot.send_message(
        chat_id=user_id,
        text=(
            "⚠️ <b>Deleting in 30s, save quickly…</b>\n\n"
            "💾 File ko apne Saved Messages me forward/save kar lena."
        ),
        parse_mode=ParseMode.HTML,
    )

    file_id = media["file_id"]
    file_type = media["file_type"]
    filename = media["file_name"] or "Media File"

    caption = (
        f"📂 <b>{filename}</b>\n\n"
        "🔊 <b>Tip:</b> VLC Player use karo agar audio/language issue aaye.\n\n"
        "⚠️ File ko delete hone se pehle Saved Messages me save kar lo."
    )

    sent = None

    try:
        if file_type == "video":
            sent = await context.bot.send_video(
                chat_id=user_id,
                video=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
        elif file_type == "audio":
            sent = await context.bot.send_audio(
                chat_id=user_id,
                audio=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
        else:
            sent = await context.bot.send_document(
                chat_id=user_id,
                document=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )

        if SAVE_TUTORIAL_VIDEO_FILE_ID:
            await context.bot.send_video(
                chat_id=user_id,
                video=SAVE_TUTORIAL_VIDEO_FILE_ID,
                caption="💾 <b>File Save Kaise Kare?</b>\nIs video me dekho.",
                parse_mode=ParseMode.HTML,
            )

        await asyncio.sleep(max(1, int(DELETE_AFTER_SECONDS)))

        if sent:
            try:
                await context.bot.delete_message(
                    chat_id=user_id,
                    message_id=sent.message_id,
                )
            except Exception as exc:
                logger.warning("Could not delete media message: %s", exc)

        try:
            await context.bot.delete_message(
                chat_id=user_id,
                message_id=warning.message_id,
            )
        except Exception as exc:
            logger.warning("Could not delete warning: %s", exc)

    except Exception as exc:
        logger.exception("File send failed: %s", exc)
        try:
            await warning.edit_text(
                "❌ File send nahi ho paayi. Dobara try karo."
            )
        except Exception:
            pass


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return

    await update.message.reply_text(
        "🛠 <b>IMDB Movie Robot Admin Panel</b>\n\n"
        "Bot management:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu(),
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    if query.data == "admin_stats":
        await query.answer(
            f"👥 Users: {user_count()}",
            show_alert=True,
        )
        return

    if query.data == "admin_broadcast":
        context.user_data["admin_action"] = "broadcast"
        await query.message.reply_text(
            "📢 <b>Broadcast Mode</b>\n\n"
            "Ab jo message bhejoge woh users ko copy hoga.\n"
            "Cancel: /cancel",
            parse_mode=ParseMode.HTML,
        )
        return

    if query.data == "admin_popup":
        context.user_data["admin_action"] = "popup"
        await query.message.reply_text(
            "⚠️ <b>Popup Mode</b>\n\n"
            "Text message bhejo.\n"
            "Cancel: /cancel",
            parse_mode=ParseMode.HTML,
        )


async def admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    action = context.user_data.get("admin_action")
    if not action:
        return

    if action == "broadcast":
        users = get_all_users()
        success = 0
        failed = 0

        await update.message.reply_text(
            f"📢 Broadcasting to {len(users)} users..."
        )

        for row in users:
            try:
                await context.bot.copy_message(
                    chat_id=row["user_id"],
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id,
                )
                success += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
                try:
                    block_user(row["user_id"])
                except Exception:
                    pass

        context.user_data.pop("admin_action", None)

        await update.message.reply_text(
            f"✅ Broadcast complete\n\n"
            f"📤 Sent: {success}\n"
            f"❌ Failed: {failed}"
        )
        return

    if action == "popup":
        users = get_all_users()
        success = 0

        for row in users:
            try:
                await context.bot.send_message(
                    chat_id=row["user_id"],
                    text=f"⚠️ <b>IMPORTANT</b>\n\n{update.message.text}",
                    parse_mode=ParseMode.HTML,
                )
                success += 1
            except Exception:
                pass

        context.user_data.pop("admin_action", None)

        await update.message.reply_text(
            f"✅ Popup sent to {success} users."
        )


async def save_media_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "/save TMDB_ID | Title\n\n"
            "Example:\n"
            "/save 12345 | Example Movie\n\n"
            "Then video/document/audio bhejo."
        )
        return

    raw = " ".join(context.args)

    if "|" not in raw:
        await update.message.reply_text(
            "Format:\n/save TMDB_ID | Title"
        )
        return

    tmdb_id_text, title = raw.split("|", 1)

    try:
        tmdb_id = int(tmdb_id_text.strip())
    except ValueError:
        await update.message.reply_text("❌ TMDB ID numeric hona chahiye.")
        return

    title = title.strip()
    if not title:
        await update.message.reply_text("❌ Title missing hai.")
        return

    context.user_data["save_media"] = {
        "tmdb_id": tmdb_id,
        "title": title,
    }

    await update.message.reply_text(
        f"📥 Ab <b>{title}</b> ki video/document/audio bhejo.",
        parse_mode=ParseMode.HTML,
    )


async def receive_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    save_data = context.user_data.get("save_media")
    if not save_data:
        return

    file_id = None
    file_type = None
    file_name = ""

    if update.message.video:
        file_id = update.message.video.file_id
        file_type = "video"
        file_name = update.message.video.file_name or "Video"

    elif update.message.document:
        file_id = update.message.document.file_id
        file_type = "document"
        file_name = update.message.document.file_name or "File"

    elif update.message.audio:
        file_id = update.message.audio.file_id
        file_type = "audio"
        file_name = update.message.audio.file_name or "Audio"

    if not file_id:
        return

    add_media(
        tmdb_id=save_data["tmdb_id"],
        title=save_data["title"],
        file_id=file_id,
        file_type=file_type,
        file_name=file_name,
    )

    context.user_data.pop("save_media", None)

    await update.message.reply_text(
        "✅ File successfully saved.\n\n"
        f"🎬 {save_data['title']}\n"
        f"🆔 TMDB: {save_data['tmdb_id']}\n"
        f"📁 {file_name}"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Current action cancelled.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled bot error", exc_info=context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing in config.py")

    if not TMDB_API_KEY:
        raise RuntimeError("TMDB_API_KEY missing in config.py")

    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CommandHandler("save", save_media_command))
    application.add_handler(CommandHandler("cancel", cancel))

    application.add_handler(
        CallbackQueryHandler(check_join, pattern=r"^check_join$")
    )
    application.add_handler(
        CallbackQueryHandler(search_help, pattern=r"^search_help$")
    )
    application.add_handler(
        CallbackQueryHandler(movie_callback, pattern=r"^movie:")
    )
    application.add_handler(
        CallbackQueryHandler(send_file, pattern=r"^file:")
    )
    application.add_handler(
        CallbackQueryHandler(admin_callback, pattern=r"^admin_")
    )

    # Media handler first: admin can save a file after /save.
    application.add_handler(
        MessageHandler(
            filters.VIDEO | filters.Document.ALL | filters.AUDIO,
            receive_media,
        ),
        group=0,
    )

    # Admin text actions are checked before public search.
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            admin_text,
        ),
        group=0,
    )

    # Public movie search.
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_search,
        ),
        group=1,
    )

    application.add_error_handler(error_handler)

    logger.info("IMDB Movie Robot started.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
