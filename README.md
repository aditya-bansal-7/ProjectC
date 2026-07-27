# Project C — X Retweet Bot

A Telegram bot that manages X (Twitter) retweet sessions using **Project B** as the browser automation backend.

---

## Prerequisites

- **Project B** must be running (Node.js service). Configure its URL in `.env`.
- **Python 3.11+**
- **MongoDB** (Atlas or local)

---

## Setup

### 1. Install dependencies

```bash
cd ProjectC
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token (from @BotFather) |
| `MONGODB_URI` | MongoDB connection string |
| `MONGO_DB` | Database name (default: `projectc`) |
| `PROJECT_B_URL` | Project B service URL (e.g. `http://localhost:3000`) |
| `PROJECT_B_SECRET` | API secret configured in Project B |
| `ADMIN_IDS` | Comma-separated Telegram user IDs of super-admins |

### 3. Add GIFs

Place 10–15 open GIF/MP4/WEBM files in the `gifs/` folder. These are used by the `/set` command.

### 4. Run the bot

```bash
python bot.py
```

---

## Admin Setup Flow (Private Chat)

1. Send `/start` to the bot in private chat
2. Send `/setup` to open the setup wizard
3. **Step 1**: Set your group (send the group's numeric ID or forward a group message)
4. **Step 2**: Create Chrome profile → opens X login link
5. **Step 3**: Log in to X in the browser, then click **✅ I've Logged In to X**
6. Setup complete! Add the bot to your group.

---

## Group Commands

> Only the admin who registered that group can run these commands.

| Command | Description |
|---|---|
| `/set` | Posts an open GIF + random quote in the group |
| `/open` | Starts a retweet session — users drop X links |
| `/slow` | Switch to slow mode: 1 link retweeted per 60s |
| `/fast` | Switch to fast mode: 3 links retweeted per 60s |
| `/stats` | Show session statistics (received / done / failed / queue) |
| `/close` | End the session |

---

## Super-Admin Commands (Private Chat)

| Command | Description |
|---|---|
| `/addadmin <user_id> [username]` | Register a new admin |
| `/removeadmin <user_id>` | Remove an admin |
| `/listadmins` | List all registered admins |

---

## Architecture

```
bot.py              ← Polling entry point
config.py           ← Settings from .env
db/models.py        ← MongoDB CRUD (admins, sessions)
services/project_b.py  ← HTTP client for Project B API
handlers/
  admin_setup.py    ← Private chat wizard
  group_commands.py ← /set /open /slow /fast /stats /close
  link_collector.py ← Listens for X links in group
workers/
  retweet_worker.py ← Background thread processing queue
utils/
  quotes.py         ← Random open quotes
  open_gifs.py      ← Random GIF picker from gifs/
gifs/               ← Place your GIF/MP4/WEBM files here
```

---

## Session Flow

```
Admin sends /open
     ↓
Users drop X links (https://x.com/user/status/...)
     ↓
Link collector adds URLs to queue in MongoDB
     ↓
Retweet worker (background thread) pops URLs from queue
 - slow: 1 per 60s
 - fast: 3 per 60s
     ↓
Project B /retweet API retweets each link
     ↓
On success → links_done++
On failure → links_failed++, bot sends ❌ FAILED message to group
     ↓
If X session expires → bot sends ❌ BOT STOPPED, session ends
```
