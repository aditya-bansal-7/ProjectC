"""
Admin setup wizard — handles private-chat interactions.

Flow:
  /start    → welcome + status
  /setup    → interactive setup menu (inline buttons)
  /addadmin → super-admin only: register a new admin
  /removeadmin → super-admin only: remove an admin

Setup steps (via inline buttons):
  1. Set Group        → tap "Share Group" button (ChatShared) OR type numeric group ID
  2. Create Chrome    → calls POST /browser/create, sends login URL
  3. Mark X Logged In → calls GET /browser/status, verifies loggedIn flag
  4. My Status        → summary of current config

Group identification uses Telegram's ChatShared feature (KeyboardButtonRequestChat).
The bot sends a reply keyboard with a native share-chat button; when the user taps
it Telegram delivers a chat_shared service message containing the group ID directly.
Manual numeric ID entry (e.g. -1001234567890) is kept as a fallback.

The bot enters a "wizard state" per user stored in a simple in-memory dict
(good enough; restarts reset it which is acceptable).
"""

from __future__ import annotations

import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestChat,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

import db.models as db
from services.project_b import project_b
from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------
IDLE = 0
WAITING_FOR_GROUP = 1

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_superadmin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


def _is_admin(user_id: int) -> bool:
    return db.is_admin(user_id)


def _chrome_id_for(user_id: int | str) -> str:
    return f"admin-{user_id}"


def _setup_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Set / Update My Group", callback_data="setup:group")],
        [InlineKeyboardButton("🌐 Create Chrome Profile", callback_data="setup:chrome")],
        [InlineKeyboardButton("✅ I've Logged In to X", callback_data="setup:verify_login")],
        [InlineKeyboardButton("📊 My Status", callback_data="setup:status")],
    ])


def _status_text(admin: dict) -> str:
    group = f"{admin.get('group_title') or 'Not set'} ({admin.get('group_id') or '-'})"
    chrome = admin.get("chrome_id") or "❌ Not created"
    x_status = "✅ Logged in" if admin.get("x_logged_in") else "❌ Not logged in"
    mode = admin.get("retweet_mode", "slow").capitalize()
    session = "🟢 Active" if admin.get("session_active") else "⚫ Inactive"
    return (
        "📋 <b>Your Setup Status</b>\n\n"
        f"👤 User ID: <code>{admin['user_id']}</code>\n"
        f"🏷️ Username: @{admin.get('username') or 'unknown'}\n\n"
        f"📌 Group: {group}\n"
        f"🌐 Chrome Profile: <code>{chrome}</code>\n"
        f"🐦 X Account: {x_status}\n"
        f"⚙️ Retweet Mode: {mode}\n"
        f"📡 Session: {session}\n"
    )


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != "private":
        return  # only respond in private

    if not _is_admin(user.id):
        if _is_superadmin(user.id):
            # seed this super-admin if not yet in DB
            db.upsert_admin(user.id, user.username or "")
            await update.message.reply_text(
                "👋 Welcome, super-admin!\n\nUse /setup to configure your group and X account.",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                "❌ You are not registered as an admin.\n"
                "Ask a super-admin to run: <code>/addadmin {your_user_id} {your_username}</code>",
                parse_mode="HTML",
            )
        return

    admin = db.get_admin(user.id)
    # update username in case it changed
    db.upsert_admin(user.id, user.username or "")

    await update.message.reply_text(
        f"👋 Welcome back, @{user.username or user.first_name}!\n\n"
        + _status_text(admin)
        + "\n\nUse /setup to manage your configuration.",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# /setup — shows inline keyboard
# ---------------------------------------------------------------------------

async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != "private":
        return

    if not _is_admin(user.id):
        await update.message.reply_text("❌ You are not a registered admin.")
        return

    await update.message.reply_text(
        "⚙️ <b>Admin Setup Panel</b>\n\nChoose an action:",
        parse_mode="HTML",
        reply_markup=_setup_keyboard(),
    )
    return IDLE


# ---------------------------------------------------------------------------
# Callback: setup:group
# ---------------------------------------------------------------------------

# Request ID used for the KeyboardButtonRequestChat share button
_SHARE_GROUP_REQUEST_ID = 1


def _share_group_keyboard() -> ReplyKeyboardMarkup:
    """One-time reply keyboard with a native Telegram chat-share button."""
    btn = KeyboardButton(
        text="📌 Share Group",
        request_chat=KeyboardButtonRequestChat(
            request_id=_SHARE_GROUP_REQUEST_ID,
            chat_is_channel=False,  # groups / supergroups only
        ),
    )
    return ReplyKeyboardMarkup(
        [[btn]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def cb_setup_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if not _is_admin(user.id):
        await query.edit_message_text("❌ You are not a registered admin.")
        return IDLE

    context.user_data["wizard"] = "waiting_for_group"

    # First edit the inline-keyboard message (can't attach reply keyboards to edits)
    await query.edit_message_text(
        "📌 <b>Set Your Group</b>\n\n"
        "Tap the <b>📌 Share Group</b> button that just appeared below to pick your group.\n\n"
        "Alternatively, type the numeric group ID manually\n"
        "(e.g. <code>-1001234567890</code>).\n\n"
        "Send /cancel to go back.",
        parse_mode="HTML",
    )
    # Send a separate message carrying the reply keyboard
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="👇 Use the button below or type the group ID:",
        reply_markup=_share_group_keyboard(),
    )
    return WAITING_FOR_GROUP


async def handle_group_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Called when admin taps Share Group (chat_shared) or types a numeric group ID."""
    user = update.effective_user
    wizard = context.user_data.get("wizard")

    if wizard != "waiting_for_group":
        return IDLE

    group_id = None
    group_title = None

    msg = update.message

    # Case 1: Telegram ChatShared service message (from the Share Group button)
    if msg.chat_shared and msg.chat_shared.request_id == _SHARE_GROUP_REQUEST_ID:
        group_id = msg.chat_shared.chat_id
        # chat_shared may optionally carry title if request_title=True was set
        group_title = getattr(msg.chat_shared, "title", None) or ""

    # Case 2: Manual numeric ID typed by the user
    elif msg.text:
        text = msg.text.strip()
        if text.startswith("-") and text.lstrip("-").isdigit():
            group_id = int(text)
            group_title = ""
        elif text.startswith("@"):
            await msg.reply_text(
                "⚠️ Username lookup isn't supported. Please type the numeric group ID\n"
                "(e.g. <code>-1001234567890</code>).\n"
                "To find it: add @userinfobot to your group and send /start there.",
                parse_mode="HTML",
            )
            return WAITING_FOR_GROUP
        elif text == "/cancel":
            # Let the ConversationHandler's cancel command handle it
            return WAITING_FOR_GROUP
        else:
            await msg.reply_text(
                "❌ Couldn't parse that. Please tap <b>📌 Share Group</b> or type the "
                "numeric group ID (e.g. <code>-1001234567890</code>).",
                parse_mode="HTML",
            )
            return WAITING_FOR_GROUP

    if group_id is None:
        await msg.reply_text(
            "❌ Couldn't detect a group. Tap <b>📌 Share Group</b> or type the "
            "numeric group ID (e.g. <code>-1001234567890</code>).",
            parse_mode="HTML",
        )
        return WAITING_FOR_GROUP

    # Check if another admin already owns this group
    existing = db.get_admin_by_group(group_id)
    if existing and str(existing["user_id"]) != str(user.id):
        await msg.reply_text(
            f"❌ That group is already registered to another admin "
            f"(@{existing.get('username') or existing['user_id']}).\n"
            "Each admin can manage only one unique group.",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data.pop("wizard", None)
        return IDLE

    db.set_admin_group(user.id, group_id, group_title)
    context.user_data.pop("wizard", None)

    await msg.reply_text(
        f"✅ Group saved!\n\n"
        f"📌 Group ID: <code>{group_id}</code>\n"
        f"🏷️ Title: {group_title or 'Unknown (you can update later)'}\n\n"
        "Now use /setup → 🌐 Create Chrome Profile to continue.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    # Send the inline setup panel as a follow-up
    await context.bot.send_message(
        chat_id=msg.chat_id,
        text="⚙️ <b>Admin Setup Panel</b>\n\nChoose an action:",
        parse_mode="HTML",
        reply_markup=_setup_keyboard(),
    )
    return IDLE


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("wizard", None)
    await update.message.reply_text(
        "↩️ Cancelled.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⚙️ <b>Admin Setup Panel</b>\n\nChoose an action:",
        parse_mode="HTML",
        reply_markup=_setup_keyboard(),
    )
    return IDLE


# ---------------------------------------------------------------------------
# Callback: setup:chrome
# ---------------------------------------------------------------------------

async def cb_setup_chrome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if not _is_admin(user.id):
        await query.edit_message_text("❌ You are not a registered admin.")
        return IDLE

    admin = db.get_admin(user.id)
    if not admin.get("group_id"):
        await query.edit_message_text(
            "⚠️ Please set your group first (step 1) before creating a Chrome profile.",
            reply_markup=_setup_keyboard(),
        )
        return IDLE

    chrome_id = _chrome_id_for(user.id)

    # Check if Project B is reachable
    if not project_b.ping():
        await query.edit_message_text(
            "❌ Cannot reach Project B service. Make sure it's running and PROJECT_B_URL is correct.",
            reply_markup=_setup_keyboard(),
        )
        return IDLE

    await query.edit_message_text("⏳ Creating Chrome profile, please wait...")

    try:
        result = project_b.create_chrome_profile(chrome_id=chrome_id)
        login_url = result.get("url") or result.get("loginUrl") or ""
        db.set_admin_chrome(user.id, result.get("chromeId", chrome_id))
        db.set_x_logged_in(user.id, False)  # reset login status

        msg = (
            f"✅ <b>Chrome profile created!</b>\n\n"
            f"🆔 Profile ID: <code>{result.get('chromeId', chrome_id)}</code>\n\n"
            f"🌐 <b>Login to X:</b>\n<a href='{login_url}'>{login_url}</a>\n\n"
            "1️⃣ Open the link above\n"
            "2️⃣ Log into your X account\n"
            "3️⃣ Come back here and tap ✅ I've Logged In to X"
        )

        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Open Login Link", url=login_url)],
            [InlineKeyboardButton("✅ I've Logged In to X", callback_data="setup:verify_login")],
            [InlineKeyboardButton("↩️ Back to Setup", callback_data="setup:back")],
        ])

        await query.edit_message_text(msg, parse_mode="HTML", reply_markup=buttons)

    except Exception as e:
        logger.exception("Chrome profile creation failed")
        await query.edit_message_text(
            f"❌ Failed to create Chrome profile:\n<code>{e}</code>\n\n"
            "Make sure Project B is running.",
            parse_mode="HTML",
            reply_markup=_setup_keyboard(),
        )

    return IDLE


# ---------------------------------------------------------------------------
# Callback: setup:verify_login
# ---------------------------------------------------------------------------

async def cb_verify_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if not _is_admin(user.id):
        await query.edit_message_text("❌ Not a registered admin.")
        return IDLE

    admin = db.get_admin(user.id)
    chrome_id = admin.get("chrome_id")

    if not chrome_id:
        await query.edit_message_text(
            "⚠️ No Chrome profile found. Please create one first.",
            reply_markup=_setup_keyboard(),
        )
        return IDLE

    await query.edit_message_text("🔍 Checking your X login status...")

    try:
        status = project_b.get_browser_status(chrome_id)
        logged_in = bool(status.get("loggedIn", False))
        running = bool(status.get("running", False))

        if logged_in:
            db.set_x_logged_in(user.id, True)
            await query.edit_message_text(
                "✅ <b>X Login Verified!</b>\n\n"
                "🎉 Setup is complete. Your bot is ready!\n\n"
                "Now add me to your group and use:\n"
                "• <code>/set</code> — Post open GIF + quote\n"
                "• <code>/open</code> — Start collecting X links\n"
                "• <code>/slow</code> or <code>/fast</code> — Set retweet speed\n"
                "• <code>/stats</code> — Session statistics",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📊 My Status", callback_data="setup:status")],
                ]),
            )
        elif running:
            db.set_x_logged_in(user.id, False)
            # Build retry buttons with login URL if available
            restart_result = project_b.start_browser(chrome_id)
            login_url = restart_result.get("loginUrl") or restart_result.get("url") or ""
            buttons = [
                [InlineKeyboardButton("🔁 Check Again", callback_data="setup:verify_login")],
            ]
            if login_url:
                buttons.insert(0, [InlineKeyboardButton("🔗 Open Login Link", url=login_url)])

            await query.edit_message_text(
                "❌ <b>Not logged in yet.</b>\n\n"
                "The browser is running but X is not logged in.\n"
                "Please complete the login in the browser, then tap <b>Check Again</b>.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        else:
            # Browser not running — try to start it
            await query.edit_message_text(
                "⚠️ Browser is not running. Attempting to start it...",
                parse_mode="HTML",
            )
            try:
                start_result = project_b.start_browser(chrome_id)
                login_url = start_result.get("url") or start_result.get("loginUrl") or ""
                buttons = [
                    [InlineKeyboardButton("🔁 Check Again", callback_data="setup:verify_login")],
                ]
                if login_url:
                    buttons.insert(0, [InlineKeyboardButton("🔗 Open Login Link", url=login_url)])
                await query.edit_message_text(
                    f"🌐 Browser started! Please log into X, then tap Check Again.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(buttons),
                )
            except Exception as e:
                await query.edit_message_text(
                    f"❌ Failed to start browser: <code>{e}</code>",
                    parse_mode="HTML",
                    reply_markup=_setup_keyboard(),
                )

    except Exception as e:
        logger.exception("Login verification failed")
        await query.edit_message_text(
            f"❌ Error checking login status:\n<code>{e}</code>",
            parse_mode="HTML",
            reply_markup=_setup_keyboard(),
        )

    return IDLE


# ---------------------------------------------------------------------------
# Callback: setup:status
# ---------------------------------------------------------------------------

async def cb_setup_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if not _is_admin(user.id):
        await query.edit_message_text("❌ Not a registered admin.")
        return IDLE

    admin = db.get_admin(user.id)
    await query.edit_message_text(
        _status_text(admin),
        parse_mode="HTML",
        reply_markup=_setup_keyboard(),
    )
    return IDLE


# ---------------------------------------------------------------------------
# Callback: setup:back
# ---------------------------------------------------------------------------

async def cb_setup_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚙️ <b>Admin Setup Panel</b>\n\nChoose an action:",
        parse_mode="HTML",
        reply_markup=_setup_keyboard(),
    )
    return IDLE


# ---------------------------------------------------------------------------
# /addadmin — super-admin only
# ---------------------------------------------------------------------------

async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != "private":
        return

    if not _is_superadmin(user.id):
        await update.message.reply_text("❌ Only super-admins can add admins.")
        return

    args = context.args  # [user_id, username]
    if len(args) < 1:
        await update.message.reply_text(
            "Usage: <code>/addadmin &lt;user_id&gt; [username]</code>",
            parse_mode="HTML",
        )
        return

    try:
        new_uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id must be a number.")
        return

    username = args[1].lstrip("@") if len(args) >= 2 else ""
    db.add_admin(new_uid, username)

    await update.message.reply_text(
        f"✅ Admin added!\n"
        f"• User ID: <code>{new_uid}</code>\n"
        f"• Username: @{username or 'unknown'}",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# /removeadmin — super-admin only
# ---------------------------------------------------------------------------

async def cmd_removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != "private":
        return

    if not _is_superadmin(user.id):
        await update.message.reply_text("❌ Only super-admins can remove admins.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: <code>/removeadmin &lt;user_id&gt;</code>",
            parse_mode="HTML",
        )
        return

    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id must be a number.")
        return

    if uid in settings.ADMIN_IDS:
        await update.message.reply_text("❌ Cannot remove a super-admin.")
        return

    db.remove_admin(uid)
    await update.message.reply_text(f"✅ Admin <code>{uid}</code> removed.", parse_mode="HTML")


# ---------------------------------------------------------------------------
# /listadmins — super-admin only
# ---------------------------------------------------------------------------

async def cmd_listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_superadmin(user.id):
        return

    admins = db.list_admins()
    if not admins:
        await update.message.reply_text("No admins registered yet.")
        return

    lines = ["👥 <b>Registered Admins</b>\n"]
    for a in admins:
        x = "✅" if a.get("x_logged_in") else "❌"
        group = a.get("group_title") or a.get("group_id") or "—"
        lines.append(
            f"• <code>{a['user_id']}</code> @{a.get('username') or '?'}  "
            f"| Group: {group}  | X: {x}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Register all handlers
# ---------------------------------------------------------------------------

def register(application):
    """Register all admin-setup handlers on the Application."""
    from telegram.ext import ConversationHandler

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("setup", cmd_setup, filters.ChatType.PRIVATE),
            CallbackQueryHandler(cb_setup_group, pattern="^setup:group$"),
        ],
        states={
            IDLE: [
                CallbackQueryHandler(cb_setup_group, pattern="^setup:group$"),
                CallbackQueryHandler(cb_setup_chrome, pattern="^setup:chrome$"),
                CallbackQueryHandler(cb_verify_login, pattern="^setup:verify_login$"),
                CallbackQueryHandler(cb_setup_status, pattern="^setup:status$"),
                CallbackQueryHandler(cb_setup_back, pattern="^setup:back$"),
            ],
            WAITING_FOR_GROUP: [
                # ChatShared service message (from the Share Group button)
                MessageHandler(
                    filters.StatusUpdate.CHAT_SHARED,
                    handle_group_input,
                ),
                # Manual numeric ID typed by the user
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handle_group_input,
                ),
                CommandHandler("cancel", cmd_cancel),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("setup", cmd_setup, filters.ChatType.PRIVATE),
        ],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    application.add_handler(conv)

    # standalone callbacks (outside conversation — e.g. after bot restart)
    application.add_handler(CallbackQueryHandler(cb_setup_chrome, pattern="^setup:chrome$"))
    application.add_handler(CallbackQueryHandler(cb_verify_login, pattern="^setup:verify_login$"))
    application.add_handler(CallbackQueryHandler(cb_setup_status, pattern="^setup:status$"))
    application.add_handler(CallbackQueryHandler(cb_setup_back, pattern="^setup:back$"))

    # standalone commands
    application.add_handler(CommandHandler("start", cmd_start, filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("addadmin", cmd_addadmin, filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("removeadmin", cmd_removeadmin, filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("listadmins", cmd_listadmins, filters.ChatType.PRIVATE))
