# IMPORTANT: keep secrets in Railway Variables, not in GitHub.
import os

BOT_TOKEN = os.getenv("8990984656:AAHQoDujHrKtEDGuR5wRJRRsfXv5V5eI36Y", "")
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")

ADMIN_ID = int(os.getenv("7702942505", "0"))

# Comma-separated Telegram usernames, e.g. @channel1,@channel2
CHANNELS = [x.strip() for x in os.getenv("CHANNELS", "").split(",") if x.strip()]

# Optional public web link shown by your own UI if you add it later.
WEB_LINK = os.getenv("https://t.me/+vRmZOpfrrYFjOGU1", "")

START_SEARCH = int(os.getenv("START_SEARCH", "3"))
REF_BONUS = int(os.getenv("REF_BONUS", "3"))
