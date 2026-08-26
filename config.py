import os

BOT_TOKEN = os.getenv("8990984656:AAHQoDujHrKtEDGuR5wRJRRsfXv5V5eI36Y", "")
TMDB_API_KEY = os.getenv("", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

CHANNELS = [
    x.strip()
    for x in os.getenv("CHANNELS", "").split(",")
    if x.strip()
]

WEB_LINK = os.getenv("WEB_LINK", "")

START_SEARCH = int(os.getenv("START_SEARCH", "3"))
REF_BONUS = int(os.getenv("REF_BONUS", "3"))

DB_FILE = os.getenv("DB_FILE", "bot.db")
