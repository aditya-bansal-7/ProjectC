"""
Link collector handler.

Listens for text messages in groups where an admin has an active session.
Extracts X/Twitter post URLs and adds them to the session queue.

Supported URL formats:
  - https://x.com/username/status/1234567890
  - https://twitter.com/username/status/1234567890
  - https://x.com/i/web/status/1234567890
"""

from __future__ import annotations

import re
import logging
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

import db.models as db

logger = logging.getLogger(__name__)

# Regex to extract X/Twitter post URLs from text
X_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:x\.com|twitter\.com)/\S+/status/\d+"
    r"|https?://(?:www\.)?x\.com/i/web/status/\d+",
    re.IGNORECASE,
)


def extract_x_urls(text: str) -> list[str]:
    """Extract all valid X post URLs from a text message."""
    return X_URL_PATTERN.findall(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Called for every text message in groups.
    Only processes if an active session exists for this group.
    """
    chat = update.effective_chat
    message = update.message

    if not message or not message.text:
        return

    if chat.type not in ("group", "supergroup"):
        return

    # Find admin for this group
    admin = db.get_admin_by_group(chat.id)
    if not admin:
        return  # no admin registered for this group

    if not admin.get("session_active"):
        return  # session not active

    # Extract X URLs from message
    urls = extract_x_urls(message.text)
    if not urls:
        return

    for url in urls:
        db.add_link_to_queue(admin["user_id"], url, message.message_id)
        logger.info(
            f"[LinkCollector] Queued: {url} | msg={message.message_id} | admin={admin['user_id']} | group={chat.id}"
        )


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

def register(application):
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )
