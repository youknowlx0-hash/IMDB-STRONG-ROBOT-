# IMPORTANT: keep secrets in Railway Variables, not in GitHub.
import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Comma-separated Telegram usernames, e.g. @channel1,@channel2
CHANNELS = [x.strip() for x in os.getenv("CHANNELS", "").split(",") if x.strip()]

# Optional public web link shown by your own UI if you add it later.
WEB_LINK = os.getenv("WEB_LINK", "")

START_SEARCH = int(os.getenv("START_SEARCH", "3"))
REF_BONUS = int(os.getenv("REF_BONUS", "3"))
