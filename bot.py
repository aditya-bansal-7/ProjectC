"""
Project C — X Retweet Bot
Entry point (polling mode).

Startup:
  1. Connect to MongoDB (via db.models)
  2. Seed super-admins from ADMIN_IDS env
  3. Register all handlers
  4. Start background retweet worker thread
  5. Start bot polling
"""

import logging
import sys

from telegram import Bot
from telegram.ext import Application

from config import settings
import db.models as db
from workers.retweet_worker import start_worker
import handlers.admin_setup as admin_setup
import handlers.group_commands as group_commands
import handlers.link_collector as link_collector

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Suppress noisy httpx/httpcore logs from python-telegram-bot
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Startup checks
# ---------------------------------------------------------------------------

def startup():
    logger.info("🚀 Starting Project C — X Retweet Bot")

    # Verify DB connection + seed admins
    try:
        logger.info("📦 Connecting to MongoDB...")
        db.seed_admins(settings.ADMIN_IDS)
        logger.info(f"✅ MongoDB connected. Seeded {len(settings.ADMIN_IDS)} super-admin(s).")
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")
        sys.exit(1)

    # Check Project B connectivity
    from services.project_b import project_b
    if project_b.ping():
        logger.info("✅ Project B is reachable.")
    else:
        logger.warning(
            f"⚠️  Cannot reach Project B at {settings.PROJECT_B_URL}. "
            "Retweet features will fail until it's running."
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    startup()

    app = Application.builder().token(settings.BOT_TOKEN).build()

    # Register handlers (order matters — more specific first)
    admin_setup.register(app)
    group_commands.register(app)
    link_collector.register(app)

    # Start retweet worker thread
    bot: Bot = app.bot
    worker_thread = start_worker(bot)
    logger.info(f"🔧 Retweet worker started (thread: {worker_thread.name})")

    # Run polling
    logger.info("🤖 Bot is running (polling)...")
    app.run_polling(
        poll_interval=1.0,
        timeout=30,
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query", "chat_member", "chat_shared"],
    )


if __name__ == "__main__":
    main()
