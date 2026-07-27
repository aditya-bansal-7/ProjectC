"""
Retweet worker — background thread that processes the queue.

Logic:
  - Polls every second for active sessions
  - For each active session, respects the interval based on mode:
      slow: 1 link per 60 seconds
      fast: 1 link per 20 seconds (= ~3 per minute)
  - Calls Project B /retweet for each URL
  - On success: increments links_done
  - On failure: increments links_failed, sends failure message to group
  - Periodically checks loggedIn status; if false → stops session and alerts group
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from telegram import Bot
from telegram.error import TelegramError

import db.models as db
from services.project_b import project_b

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timing constants
# ---------------------------------------------------------------------------

SLOW_INTERVAL = 60      # seconds per link in slow mode
FAST_INTERVAL = 20      # seconds per link in fast mode (~3 per 60s)
POLL_SLEEP = 2          # how often (seconds) the worker checks all sessions
LOGIN_CHECK_EVERY = 120  # check login status every N seconds per session

# ---------------------------------------------------------------------------
# Per-session state (in-memory — tracks last retweet time per admin_id)
# ---------------------------------------------------------------------------

_last_retweet: dict[str, float] = {}     # admin_id → timestamp of last retweet
_last_login_check: dict[str, float] = {} # admin_id → timestamp of last login check


def _interval_for_mode(mode: str) -> float:
    return SLOW_INTERVAL if mode == "slow" else FAST_INTERVAL


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

def _worker_loop(bot: Bot):
    """Main worker loop — runs in a background thread."""
    logger.info("[Worker] Retweet worker started.")

    while True:
        try:
            sessions = db.get_all_active_sessions()
            now = time.time()

            for session in sessions:
                admin_id = session["admin_id"]
                chrome_id = session.get("chrome_id", "")
                group_id = session.get("group_id", "")
                mode = session.get("mode", "slow")
                interval = _interval_for_mode(mode)

                # ---- Periodic login check ----
                last_check = _last_login_check.get(admin_id, 0)
                if now - last_check >= LOGIN_CHECK_EVERY:
                    _last_login_check[admin_id] = now
                    try:
                        status = project_b.get_browser_status(chrome_id)
                        if not status.get("loggedIn"):
                            logger.warning(f"[Worker] Admin {admin_id} — X session lost. Stopping.")
                            db.end_session(admin_id)
                            db.set_x_logged_in(admin_id, False)
                            _last_retweet.pop(admin_id, None)
                            _last_login_check.pop(admin_id, None)
                            _send_group_message(
                                bot, group_id,
                                "❌ <b>BOT STOPPED</b>\n\n"
                                "Reason: Invalid cookies / X session lost.\n\n"
                                "Fix the login in the bot DM → /setup, then send /open again.",
                            )
                            continue
                    except Exception as e:
                        logger.warning(f"[Worker] Login check failed for {admin_id}: {e}")

                # ---- Rate limiting ----
                last_rt = _last_retweet.get(admin_id, 0)
                if now - last_rt < interval:
                    continue  # not yet time for next retweet

                # ---- Pop next link from queue ----
                url = db.pop_link_from_queue(admin_id)
                if not url:
                    continue  # queue empty

                # ---- Retweet ----
                try:
                    result = project_b.retweet(chrome_id, url)
                    queued = result.get("queued", False)

                    if queued:
                        db.mark_link_done(admin_id)
                        logger.info(f"[Worker] ✅ Retweeted: {url} (admin={admin_id})")
                    else:
                        reason = result.get("message") or result.get("error") or "Unexpected response from Project B"
                        db.mark_link_failed(admin_id, url, reason)
                        logger.warning(f"[Worker] ❌ Retweet failed: {url} — {reason}")
                        _send_failure_message(bot, group_id, url, reason)

                    _last_retweet[admin_id] = time.time()

                except Exception as e:
                    reason = str(e) or "Tweet not opened / error"
                    db.mark_link_failed(admin_id, url, reason)
                    logger.error(f"[Worker] ❌ Exception retweeting {url}: {e}")
                    _send_failure_message(bot, group_id, url, reason)
                    _last_retweet[admin_id] = time.time()

        except Exception as e:
            logger.error(f"[Worker] Unexpected error in worker loop: {e}", exc_info=True)

        time.sleep(POLL_SLEEP)


# ---------------------------------------------------------------------------
# Telegram messaging helpers
# ---------------------------------------------------------------------------

def _send_group_message(bot: Bot, group_id: str, text: str):
    try:
        bot.send_message(
            chat_id=int(group_id),
            text=text,
            parse_mode="HTML",
        )
    except TelegramError as e:
        logger.error(f"[Worker] Failed to send message to group {group_id}: {e}")
    except Exception as e:
        logger.error(f"[Worker] Unexpected error sending message: {e}")


def _send_failure_message(bot: Bot, group_id: str, url: str, reason: str):
    text = (
        "❌ <b>FAILED</b>\n\n"
        f"Link:\n<code>{url}</code>\n\n"
        f"Reason:\n{reason}"
    )
    _send_group_message(bot, group_id, text)


# ---------------------------------------------------------------------------
# Start worker thread
# ---------------------------------------------------------------------------

def start_worker(bot: Bot) -> threading.Thread:
    """Start the retweet worker in a daemon background thread."""
    t = threading.Thread(target=_worker_loop, args=(bot,), daemon=True, name="RetweetWorker")
    t.start()
    return t
