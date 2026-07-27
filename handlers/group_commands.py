"""
Group command handlers.

Commands (group-only, admin of that group only):
  /set    — Post open GIF + random quote in group
  /open   — Start a retweet session (collect X links)
  /slow   — Switch to slow mode (1 link per 60s)
  /fast   — Switch to fast mode (3 links per 60s)
  /stats  — Show session statistics
  /close  — Stop session, flush remaining queue
"""

from __future__ import annotations

import logging
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, filters

import db.models as db
from services.project_b import project_b
from utils.quotes import get_random_quote
from utils.open_gifs import get_random_gif, get_gif_type

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Guard helpers
# ---------------------------------------------------------------------------

async def _get_verified_admin(update: Update) -> dict | None:
    """
    Returns admin doc if the message sender is the admin for this group.
    Sends an error reply and returns None otherwise.
    """
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ("group", "supergroup"):
        return None  # silently ignore non-group

    admin = db.get_admin_by_group(chat.id)
    if not admin:
        return None  # bot is in a group with no registered admin — ignore

    if str(admin["user_id"]) != str(user.id):
        # Not the admin for this group — silently ignore
        return None

    if not admin.get("x_logged_in"):
        await update.message.reply_text(
            "❌ Your X account is not verified.\n"
            "Go to the bot DM → /setup → ✅ I've Logged In to X",
        )
        return None

    return admin


async def _try_start_session(update: Update, admin: dict, chat) -> bool:
    """
    Validates Chrome profile, browser status, and login state.
    Starts the session in the DB if everything is OK.
    Returns True if session was successfully started, False otherwise.
    """
    if admin.get("session_active"):
        await update.message.reply_text(
            "⚠️ A session is already active.\n"
            "Use /stats to check progress or /close to end it."
        )
        return False

    chrome_id = admin.get("chrome_id")
    if not chrome_id:
        await update.message.reply_text(
            "❌ No Chrome profile found. Please run /setup in the bot DM first."
        )
        return False

    # Verify browser is running and logged in
    status = project_b.get_browser_status(chrome_id)
    if not status.get("running"):
        # Try to start it
        try:
            project_b.start_browser(chrome_id)
        except Exception:
            await update.message.reply_text(
                "❌ Browser profile is not running and could not be started.\n"
                "Go to bot DM → /setup → ✅ I've Logged In to X"
            )
            return False

    # Use check-login for definitive login status (evaluates live page DOM)
    if not project_b.is_logged_in(chrome_id):
        await update.message.reply_text(
            "❌ X account is not logged in.\n"
            "Go to bot DM → /setup → ✅ I've Logged In to X"
        )
        return False

    mode = admin.get("retweet_mode", "slow")
    db.start_session(admin["user_id"], chat.id, chrome_id, mode)
    return True



# ---------------------------------------------------------------------------
# /set — Post open GIF + quote
# ---------------------------------------------------------------------------

async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = await _get_verified_admin(update)
    if not admin:
        return

    if not await _try_start_session(update, admin, update.effective_chat):
        return

    quote = get_random_quote()
    gif_path = get_random_gif()

    speed = "🐢 Slow" if admin.get("retweet_mode", "slow") == "slow" else "⚡ Fast"
    caption = (
        f"🟢 <b>Session is OPEN!</b> [{speed}]\n\n"
        f"💬 {quote}\n\n"
        f"👇 Drop your X links below!"
    )

    try:
        if gif_path:
            ext = gif_path.suffix.lower()
            with open(gif_path, "rb") as f:
                if ext == ".gif":
                    await update.message.reply_animation(
                        animation=f,
                        caption=caption,
                        parse_mode="HTML",
                    )
                else:  # .mp4 / .webm
                    await update.message.reply_video(
                        video=f,
                        caption=caption,
                        parse_mode="HTML",
                    )
        else:
            # No GIF file — send text only
            await update.message.reply_text(
                "🟢 <b>Session is OPEN!</b>\n\n"
                f"💬 {quote}\n\n"
                "👇 Drop your X links below!",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.exception("/set failed")
        await update.message.reply_text(
            f"⚠️ Could not send GIF: {e}\n\n"
            f"🟢 Session is OPEN!\n{quote}",
        )


# ---------------------------------------------------------------------------
# /open — Start retweet session
# ---------------------------------------------------------------------------

async def cmd_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = await _get_verified_admin(update)
    if not admin:
        return

    chat = update.effective_chat

    if not await _try_start_session(update, admin, chat):
        return

    mode = admin.get("retweet_mode", "slow")
    speed = "🐢 Slow (1 link / 60s)" if mode == "slow" else "⚡ Fast (3 links / 60s)"
    await update.message.reply_text(
        f"✅ <b>Session opened!</b>\n\n"
        f"⚙️ Mode: {speed}\n\n"
        f"👇 Users, drop your X links now!\n\n"
        f"<i>Use /slow or /fast to change speed. Use /close to stop.</i>",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# /slow — Switch to slow mode
# ---------------------------------------------------------------------------

async def cmd_slow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = await _get_verified_admin(update)
    if not admin:
        return

    if not admin.get("session_active"):
        await update.message.reply_text("⚠️ No active session. Use /open first.")
        return

    db.set_retweet_mode(admin["user_id"], "slow")
    await update.message.reply_text("🐢 Switched to <b>Slow mode</b> — 1 link per 60 seconds.", parse_mode="HTML")


# ---------------------------------------------------------------------------
# /fast — Switch to fast mode
# ---------------------------------------------------------------------------

async def cmd_fast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = await _get_verified_admin(update)
    if not admin:
        return

    if not admin.get("session_active"):
        await update.message.reply_text("⚠️ No active session. Use /open first.")
        return

    db.set_retweet_mode(admin["user_id"], "fast")
    await update.message.reply_text("⚡ Switched to <b>Fast mode</b> — 3 links per 60 seconds.", parse_mode="HTML")


# ---------------------------------------------------------------------------
# /stats — Session statistics
# ---------------------------------------------------------------------------

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = await _get_verified_admin(update)
    if not admin:
        return

    stats = db.get_session_stats(admin["user_id"])
    if not stats:
        await update.message.reply_text("📊 No active session. Use /open to start one.")
        return

    mode_icon = "🐢 Slow" if stats["mode"] == "slow" else "⚡ Fast"

    text = (
        f"📊 <b>Session Stats</b>  [{mode_icon}]\n\n"
        f"🔗 Links Received : <b>{stats['links_received']}</b>\n"
        f"✅ Done          : <b>{stats['links_done']}</b>\n"
        f"❌ Failed        : <b>{stats['links_failed']}</b>\n"
        f"⏳ In Queue      : <b>{stats['in_queue']}</b>\n"
    )

    if stats["failed_links"]:
        text += "\n\n<b>❌ Failed Links:</b>\n"
        for item in stats["failed_links"][-10:]:  # show last 10 failures
            url = item.get("url", "unknown")
            reason = item.get("reason", "Unknown error")
            text += (
                f"\n🔴 <b>FAILED</b>\n"
                f"Link:\n<code>{url}</code>\n"
                f"Reason:\n{reason}\n"
            )

    await update.message.reply_text(text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# /close — End session
# ---------------------------------------------------------------------------

async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = await _get_verified_admin(update)
    if not admin:
        return

    if not admin.get("session_active"):
        await update.message.reply_text("⚠️ No active session to close.")
        return

    # Show final stats before closing
    stats = db.get_session_stats(admin["user_id"])
    db.end_session(admin["user_id"])

    if stats:
        await update.message.reply_text(
            f"🔴 <b>Session Closed</b>\n\n"
            f"📊 Final Stats:\n"
            f"🔗 Received : {stats['links_received']}\n"
            f"✅ Done     : {stats['links_done']}\n"
            f"❌ Failed   : {stats['links_failed']}\n"
            f"⏳ Dropped  : {stats['in_queue']} (remaining in queue)\n\n"
            f"<i>Use /open to start a new session.</i>",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text("🔴 Session closed.")


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

def register(application):
    group_filter = filters.ChatType.GROUPS

    application.add_handler(CommandHandler("set", cmd_set, group_filter))
    application.add_handler(CommandHandler("open", cmd_open, group_filter))
    application.add_handler(CommandHandler("slow", cmd_slow, group_filter))
    application.add_handler(CommandHandler("fast", cmd_fast, group_filter))
    application.add_handler(CommandHandler("stats", cmd_stats, group_filter))
    application.add_handler(CommandHandler("close", cmd_close, group_filter))
