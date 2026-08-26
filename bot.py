import asyncio
import logging
import aiohttp

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.constants import ParseMode

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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
    get_media,
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

SEARCH_CACHE = {}


# ==========================================
# BASIC HELPERS
# ==========================================

def is_admin(user_id):
    return user_id == ADMIN_ID


def main_menu():
    buttons = [
        [
            InlineKeyboardButton(
                "🔎 Search Movie",
                callback_data="search_help"
            )
        ],
        [
            InlineKeyboardButton(
                "📢 Updates Channel",
                url="https://t.me/webSeriesUpdater"
            )
        ],
    ]

    if WEB_LINK:
        buttons.append([
            InlineKeyboardButton(
                "🌐 Web Link",
                url=WEB_LINK
            )
        ])

    return InlineKeyboardMarkup(buttons)


def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 Stats",
                callback_data="admin_stats"
            ),
            InlineKeyboardButton(
                "📢 Broadcast",
                callback_data="admin_broadcast"
            ),
        ],
        [
            InlineKeyboardButton(
                "⚠️ Popup",
                callback_data="admin_popup"
            ),
        ],
    ])


# ==========================================
# FORCE JOIN
# ==========================================

async def check_membership(bot, user_id):

    if not CHANNELS:
        return True

    for channel in CHANNELS:

        try:
            member = await bot.get_chat_member(
                chat_id=channel,
                user_id=user_id
            )

            if member.status in (
                "left",
                "kicked"
            ):
                return False

        except Exception as e:
            logger.warning(
                "Membership check failed for %s: %s",
                channel,
                e
            )

            return False

    return True


def join_keyboard():

    buttons = []

    for channel in CHANNELS:
        username = channel.replace("@", "")

        buttons.append([
            InlineKeyboardButton(
                f"📢 Join @{username}",
                url=f"https://t.me/{username}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "✅ I've Joined",
            callback_data="check_join"
        )
    ])

    return InlineKeyboardMarkup(buttons)


# ==========================================
# TMDB
# ==========================================

async def tmdb_request(endpoint, params):

    url = f"https://api.themoviedb.org/3/{endpoint}"

    params = dict(params)
    params["api_key"] = TMDB_API_KEY

    async with aiohttp.ClientSession() as session:

        async with session.get(
            url,
            params=params,
            timeout=20
        ) as response:

            if response.status != 200:
                logger.error(
                    "TMDB error: %s",
                    response.status
                )
                return None

            return await response.json()


async def search_movie(query):

    data = await tmdb_request(
        "search/multi",
        {
            "query": query,
            "language": "en-US",
            "include_adult": "false",
        }
    )

    if not data:
        return []

    results = []

    for item in data.get("results", []):

        media_type = item.get("media_type")

        if media_type not in ("movie", "tv"):
            continue

        title = (
            item.get("title")
            or item.get("name")
            or "Unknown"
        )

        results.append({
            "id": item.get("id"),
            "type": media_type,
            "title": title,
            "date": (
                item.get("release_date")
                or item.get("first_air_date")
                or ""
            ),
            "poster": item.get("poster_path"),
        })

    return results[:10]


async def get_details(tmdb_id, media_type):

    endpoint = (
        f"movie/{tmdb_id}"
        if media_type == "movie"
        else f"tv/{tmdb_id}"
    )

    return await tmdb_request(
        endpoint,
        {
            "language": "en-US"
        }
    )


async def get_external_ids(tmdb_id, media_type):

    endpoint = (
        f"movie/{tmdb_id}/external_ids"
        if media_type == "movie"
        else f"tv/{tmdb_id}/external_ids"
    )

    return await tmdb_request(
        endpoint,
        {}
    )


# ==========================================
# START
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    add_user(
        user.id,
        user.username,
        user.first_name
    )

    joined = await check_membership(
        context.bot,
        user.id
    )

    if not joined:

        await update.message.reply_text(
            "🔐 <b>Join Required</b>\n\n"
            "Bot use karne ke liye pehle required channels join karo.\n\n"
            "Join karne ke baad <b>I've Joined</b> dabao.",
            parse_mode=ParseMode.HTML,
            reply_markup=join_keyboard()
        )

        return

    await update.message.reply_text(
        f"🎬 <b>{BOT_NAME}</b>\n\n"
        "🔎 Movie / Web Series ka naam bhejo.\n\n"
        "Main available information aur files dikha dunga.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu()
    )


# ==========================================
# JOIN CHECK
# ==========================================

async def check_join(update, context):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    joined = await check_membership(
        context.bot,
        user_id
    )

    if not joined:

        await query.answer(
            "❌ Pehle sabhi channels join karo.",
            show_alert=True
        )

        return

    await query.edit_message_text(
        "✅ Verification successful!\n\n"
        "Ab movie/web-series ka naam bhejo."
    )


# ==========================================
# SEARCH
# ==========================================

async def text_search(update, context):

    user = update.effective_user

    if not update.message:
        return

    text = update.message.text.strip()

    if text.startswith("/"):
        return

    joined = await check_membership(
        context.bot,
        user.id
    )

    if not joined:

        await update.message.reply_text(
            "⚠️ Pehle required channels join karo.",
            reply_markup=join_keyboard()
        )

        return

    msg = await update.message.reply_text(
        "🔎 Searching..."
    )

    results = await search_movie(text)

    if not results:

        await msg.edit_text(
            "❌ Kuch nahi mila.\n\n"
            "Movie/Web Series ka naam thoda different "
            "tarike se try karo."
        )

        return

    SEARCH_CACHE[user.id] = results

    buttons = []

    for index, item in enumerate(results):

        title = item["title"]

        year = item["date"][:4] if item["date"] else ""

        label = f"🎬 {title}"

        if year:
            label += f" ({year})"

        buttons.append([
            InlineKeyboardButton(
                label[:60],
                callback_data=f"movie:{index}"
            )
        ])

    await msg.edit_text(
        "🔎 <b>Search Results</b>\n\n"
        "Apni movie/web-series select karo:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ==========================================
# MOVIE DETAILS
# ==========================================

async def movie_callback(update, context):

    query = update.callback_query

    await query.answer()

    if not query.data.startswith("movie:"):
        return

    user_id = query.from_user.id

    try:
        index = int(
            query.data.split(":")[1]
        )

        item = SEARCH_CACHE[user_id][index]

    except Exception:

        await query.edit_message_text(
            "❌ Search expired. Dobara search karo."
        )

        return

    details = await get_details(
        item["id"],
        item["type"]
    )

    if not details:

        await query.edit_message_text(
            "❌ Details nahi mil paayi."
        )

        return

    external = await get_external_ids(
        item["id"],
        item["type"]
    )

    imdb_id = (
        external.get("imdb_id")
        if external
        else None
    )

    title = (
        details.get("title")
        or details.get("name")
        or item["title"]
    )

    rating = details.get(
        "vote_average",
        0
    )

    overview = details.get(
        "overview",
        ""
    )

    if len(overview) > 500:
        overview = overview[:500] + "..."

    genres = details.get(
        "genres",
        []
    )

    genre_text = ", ".join(
        g["name"] for g in genres
    )

    release = (
        details.get("release_date")
        or details.get("first_air_date")
        or "N/A"
    )

    text = (
        f"🎬 <b>{title}</b>\n\n"
        f"📅 <b>Release:</b> {release}\n"
        f"⭐ <b>Rating:</b> {rating:.1f}/10\n"
        f"🎭 <b>Genre:</b> {genre_text or 'N/A'}\n"
    )

    if imdb_id:

        text += (
            f"🔗 <b>IMDb:</b> "
            f"https://www.imdb.com/title/{imdb_id}/\n"
        )

    if overview:

        text += (
            f"\n📝 <b>Overview:</b>\n"
            f"{overview}\n"
        )

    text += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "📂 <b>Available Files</b>"
    )

    files = get_media(item["id"])

    buttons = []

    for media in files:

        filename = media["file_name"] or "File"

        buttons.append([
            InlineKeyboardButton(
                f"📥 {filename[:45]}",
                callback_data=f"file:{media['id']}"
            )
        ])

    if not files:

        text += (
            "\n\n⚠️ Abhi koi file available nahi hai."
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=(
            InlineKeyboardMarkup(buttons)
            if buttons
            else None
        )
    )


# ==========================================
# FILE DELIVERY
# ==========================================

async def send_file(update, context):

    query = update.callback_query

    await query.answer()

    try:
        media_id = int(
            query.data.split(":")[1]
        )

    except Exception:

        return

    rows = get_media_by_id(media_id)

    if not rows:

        await query.answer(
            "❌ File unavailable.",
            show_alert=True
        )

        return

    media = rows

    warning = await context.bot.send_message(
        chat_id=query.from_user.id,
        text=(
            "⚠️ <b>Deleting in 30s, save quickly…</b>\n\n"
            "📌 File ko apne Saved Messages me "
            "forward/save kar lena."
        ),
        parse_mode=ParseMode.HTML
    )

    file_type = media["file_type"]
    file_id = media["file_id"]
    filename = media["file_name"]

    caption = (
        f"📂 <b>{filename or 'Media File'}</b>\n\n"
        "🔊 <b>Tip:</b> VLC Player use karo "
        "agar audio/language issue aaye.\n\n"
        "⚠️ File ko delete hone se pehle "
        "Saved Messages me save kar lo."
    )

    try:

        if file_type == "video":

            sent = await context.bot.send_video(
                chat_id=query.from_user.id,
                video=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML
            )

        elif file_type == "audio":

            sent = await context.bot.send_audio(
                chat_id=query.from_user.id,
                audio=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML
            )

        else:

            sent = await context.bot.send_document(
                chat_id=query.from_user.id,
                document=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML
            )

        if SAVE_TUTORIAL_VIDEO_FILE_ID:

            await context.bot.send_video(
                chat_id=query.from_user.id,
                video=SAVE_TUTORIAL_VIDEO_FILE_ID,
                caption=(
                    "💾 <b>File Save Kaise Kare?</b>\n"
                    "Is video me dekho."
                ),
                parse_mode=ParseMode.HTML
            )

        await asyncio.sleep(
            DELETE_AFTER_SECONDS
        )

        try:
            await context.bot.delete_message(
                chat_id=query.from_user.id,
                message_id=sent.message_id
            )
        except Exception:
            pass

        try:
            await warning.delete()
        except Exception:
            pass

    except Exception as e:

        logger.exception(
            "File sending failed: %s",
            e
        )

        await query.message.reply_text(
            "❌ File send nahi ho paayi."
        )


def get_media_by_id(media_id):

    import sqlite3

    conn = sqlite3.connect("bot.db")
    conn.row_factory = sqlite3.Row

    try:

        row = conn.execute(
            "SELECT * FROM media WHERE id=?",
            (media_id,)
        ).fetchone()

        return row

    finally:

        conn.close()


# ==========================================
# ADMIN PANEL
# ==========================================

async def admin(update, context):

    user = update.effective_user

    if not is_admin(user.id):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    await update.message.reply_text(
        "🛠 <b>IMDB Movie Robot Admin Panel</b>\n\n"
        "Yahan se bot manage kar sakte ho.",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu()
    )


# ==========================================
# ADMIN CALLBACK
# ==========================================

async def admin_callback(update, context):

    query = update.callback_query

    await query.answer()

    if not is_admin(query.from_user.id):
        return

    if query.data == "admin_stats":

        count = user_count()

        await query.answer(
            f"👥 Users: {count}",
            show_alert=True
        )

    elif query.data == "admin_broadcast":

        context.user_data["admin_action"] = "broadcast"

        await query.message.reply_text(
            "📢 <b>Broadcast Mode</b>\n\n"
            "Ab jo message bhejoge woh users ko broadcast hoga.\n\n"
            "Cancel karne ke liye /cancel",
            parse_mode=ParseMode.HTML
        )

    elif query.data == "admin_popup":

        context.user_data["admin_action"] = "popup"

        await query.message.reply_text(
            "⚠️ <b>Popup Mode</b>\n\n"
            "Popup message bhejo.\n\n"
            "Cancel: /cancel",
            parse_mode=ParseMode.HTML
        )


# ==========================================
# ADMIN TEXT ACTIONS
# ==========================================

async def admin_text(update, context):

    user = update.effective_user

    if not is_admin(user.id):
        return

    action = context.user_data.get(
        "admin_action"
    )

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
                    message_id=update.message.message_id
                )

                success += 1

                await asyncio.sleep(0.05)

            except Exception:

                failed += 1

                try:
                    block_user(row["user_id"])
                except Exception:
                    pass

        context.user_data.pop(
            "admin_action",
            None
        )

        await update.message.reply_text(
            f"✅ Broadcast complete\n\n"
            f"📤 Sent: {success}\n"
            f"❌ Failed: {failed}"
        )

    elif action == "popup":

        users = get_all_users()

        success = 0

        for row in users:

            try:

                await context.bot.send_message(
                    chat_id=row["user_id"],
                    text=(
                        "⚠️ <b>IMPORTANT</b>\n\n"
                        f"{update.message.text}"
                    ),
                    parse_mode=ParseMode.HTML
                )

                success += 1

            except Exception:
                pass

        context.user_data.pop(
            "admin_action",
            None
        )

        await update.message.reply_text(
            f"✅ Popup sent to {success} users."
        )


# ==========================================
# ADMIN MEDIA SAVE
# ==========================================

async def save_media(update, context):

    user = update.effective_user

    if not is_admin(user.id):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n\n"
            "/save TMDB_ID | Title\n\n"
            "Example:\n"
            "/save 12345 | Example Movie\n\n"
            "Then immediately send the video/document."
        )

        return

    raw = " ".join(context.args)

    if "|" not in raw:

        await update.message.reply_text(
            "Format:\n"
            "/save TMDB_ID | Title"
        )

        return

    tmdb_id, title = raw.split(
        "|",
        1
    )

    tmdb_id = tmdb_id.strip()
    title = title.strip()

    context.user_data["save_media"] = {
        "tmdb_id": int(tmdb_id),
        "title": title
    }

    await update.message.reply_text(
        "📥 Ab video/document bhejo."
    )


async def receive_media(update, context):

    user = update.effective_user

    if not is_admin(user.id):
        return

    save_data = context.user_data.get(
        "save_media"
    )

    if not save_data:
        return

    file_id = None
    file_type = "document"
    file_name = ""

    if update.message.video:

        file_id = update.message.video.file_id
        file_type = "video"

        file_name = (
            update.message.video.file_name
            or "Video"
        )

    elif update.message.document:

        file_id = update.message.document.file_id
        file_type = "document"

        file_name = (
            update.message.document.file_name
            or "File"
        )

    elif update.message.audio:

        file_id = update.message.audio.file_id
        file_type = "audio"

        file_name = (
            update.message.audio.file_name
            or "Audio"
        )

    if not file_id:
        return

    add_media(
        tmdb_id=save_data["tmdb_id"],
        title=save_data["title"],
        file_id=file_id,
        file_type=file_type,
        file_name=file_name
    )

    context.user_data.pop(
        "save_media",
        None
