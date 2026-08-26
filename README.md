# IMDB Movie Robot

Telegram media catalog bot for Railway. It uses TMDB for metadata/search and sends **admin-uploaded Telegram files** directly to users.

## Important
Only upload/distribute files you have the rights or permission to distribute. The bot does not scrape or automate third-party movie-download sites.

## Features
- TMDB movie / TV search
- IMDb link when TMDB exposes an IMDb ID
- Direct Telegram file delivery from files uploaded by admin
- 30-second auto-delete warning for delivered files
- Save-to-Saved-Messages instruction
- Force-join channels
- Referral credits
- User stats
- Movie requests
- Admin panel
- Broadcast messages
- Mandatory popup message on /start
- SQLite database (Railway-friendly)
- No start image required

## Railway Variables
Set these in Railway -> Service -> Variables:

- `BOT_TOKEN` — new token from BotFather
- `TMDB_API_KEY` — TMDB API key
- `ADMIN_ID` — your numeric Telegram user ID
- `CHANNELS` — comma-separated usernames, e.g. `@channel1,@channel2`
- `WEB_LINK` — optional web link
- `START_SEARCH` — default `3`
- `REF_BONUS` — default `3`

## Local run
```bash
pip install -r requirements.txt
python bot.py
```

## Admin
Send `/admin` from the configured admin account.

### Add a file
1. Admin -> Add File
2. Enter the TMDB ID
3. Send the Telegram Document or Video
4. Users will see it under that title and can click to receive it.

Telegram bots cannot automatically move a message into a user's Saved Messages. The bot instead sends a short instruction telling the user how to save the file.
