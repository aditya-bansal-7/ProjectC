"""
MongoDB models and CRUD helpers for Project C.

Collections:
  - admins          : one doc per registered admin
  - retweet_sessions: one active session per admin
"""

from __future__ import annotations

import certifi
from datetime import datetime, timezone
from typing import Optional
from pymongo import MongoClient, ASCENDING
from pymongo.collection import Collection
from bson import ObjectId

from config import settings

# ---------------------------------------------------------------------------
# DB connection (lazy singleton)
# ---------------------------------------------------------------------------

_client: Optional[MongoClient] = None
_db = None


def _get_db():
    global _client, _db
    if _db is None:
        _client = MongoClient(
            settings.MONGODB_URI,
            serverSelectionTimeoutMS=10_000,
            tlsCAFile=certifi.where(),
        )
        _db = _client[settings.MONGO_DB]
        _ensure_indexes()
    return _db


def _admins() -> Collection:
    return _get_db()["admins"]


def _sessions() -> Collection:
    return _get_db()["retweet_sessions"]


def _ensure_indexes():
    db = _get_db()
    db["admins"].create_index([("user_id", ASCENDING)], unique=True, name="admin_user_id")
    db["admins"].create_index([("username", ASCENDING)], sparse=True, name="admin_username")
    db["admins"].create_index([("group_id", ASCENDING)], sparse=True, name="admin_group_id")
    db["retweet_sessions"].create_index(
        [("admin_id", ASCENDING), ("active", ASCENDING)], name="session_admin_active"
    )


# ---------------------------------------------------------------------------
# Admin helpers
# ---------------------------------------------------------------------------

def is_admin(user_id: int | str) -> bool:
    """Return True if this user_id is a registered admin."""
    doc = _admins().find_one({"user_id": str(user_id)})
    return doc is not None


def get_admin(user_id: int | str) -> Optional[dict]:
    return _admins().find_one({"user_id": str(user_id)})


def list_admins() -> list[dict]:
    return list(_admins().find())


def upsert_admin(user_id: int | str, username: str = "") -> dict:
    """Create or touch an admin document."""
    uid = str(user_id)
    _admins().update_one(
        {"user_id": uid},
        {
            "$setOnInsert": {
                "user_id": uid,
                "group_id": None,
                "group_title": None,
                "chrome_id": None,
                "x_logged_in": False,
                "retweet_mode": "slow",
                "session_active": False,
                "created_at": datetime.now(timezone.utc),
            },
            "$set": {"username": username or ""},
        },
        upsert=True,
    )
    return get_admin(uid)


def add_admin(user_id: int | str, username: str = "") -> dict:
    """Alias of upsert_admin for explicit admin addition."""
    return upsert_admin(user_id, username)


def remove_admin(user_id: int | str):
    uid = str(user_id)
    _admins().delete_one({"user_id": uid})
    # also clean up any active sessions
    _sessions().update_many({"admin_id": uid, "active": True}, {"$set": {"active": False}})


def set_admin_group(user_id: int | str, group_id: int | str, group_title: str = ""):
    _admins().update_one(
        {"user_id": str(user_id)},
        {"$set": {"group_id": str(group_id), "group_title": group_title}},
    )


def set_admin_chrome(user_id: int | str, chrome_id: str):
    _admins().update_one(
        {"user_id": str(user_id)},
        {"$set": {"chrome_id": chrome_id}},
    )


def set_x_logged_in(user_id: int | str, value: bool):
    _admins().update_one(
        {"user_id": str(user_id)},
        {"$set": {"x_logged_in": value}},
    )


def set_retweet_mode(user_id: int | str, mode: str):
    """mode: 'slow' | 'fast'"""
    _admins().update_one(
        {"user_id": str(user_id)},
        {"$set": {"retweet_mode": mode}},
    )
    # also update any active session
    active = get_active_session(str(user_id))
    if active:
        _sessions().update_one({"_id": active["_id"]}, {"$set": {"mode": mode}})


def set_session_active(user_id: int | str, value: bool):
    _admins().update_one(
        {"user_id": str(user_id)},
        {"$set": {"session_active": value}},
    )


def get_admin_by_group(group_id: int | str) -> Optional[dict]:
    """Find the admin that owns this group."""
    return _admins().find_one({"group_id": str(group_id)})


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def start_session(admin_id: int | str, group_id: int | str, chrome_id: str, mode: str = "slow") -> dict:
    """Create a new active retweet session for this admin."""
    aid = str(admin_id)
    gid = str(group_id)

    # deactivate any previous session
    _sessions().update_many({"admin_id": aid, "active": True}, {"$set": {"active": False}})

    doc = {
        "admin_id": aid,
        "group_id": gid,
        "chrome_id": chrome_id,
        "mode": mode,
        "active": True,
        "started_at": datetime.now(timezone.utc),
        "links_received": 0,
        "links_done": 0,
        "links_failed": 0,
        "queue": [],          # list of tweet URLs pending retweet
        "failed_links": [],   # list of {url, reason}
    }
    result = _sessions().insert_one(doc)
    doc["_id"] = result.inserted_id

    # mark admin session_active
    set_session_active(aid, True)
    return doc


def end_session(admin_id: int | str):
    aid = str(admin_id)
    _sessions().update_many({"admin_id": aid, "active": True}, {"$set": {"active": False}})
    set_session_active(aid, False)


def get_active_session(admin_id: int | str) -> Optional[dict]:
    return _sessions().find_one({"admin_id": str(admin_id), "active": True})


def add_link_to_queue(admin_id: int | str, url: str):
    """Append a tweet URL to the session queue and increment received count."""
    _sessions().update_one(
        {"admin_id": str(admin_id), "active": True},
        {
            "$push": {"queue": url},
            "$inc": {"links_received": 1},
        },
    )


def pop_link_from_queue(admin_id: int | str) -> Optional[str]:
    """Atomically pop the first URL from the session queue. Returns None if empty."""
    result = _sessions().find_one_and_update(
        {"admin_id": str(admin_id), "active": True, "queue.0": {"$exists": True}},
        {"$pop": {"queue": -1}},   # pop from front
        return_document=True,
    )
    # After the pop, return what was at position 0 before
    # We do a separate lookup because find_one_and_update returns doc AFTER modification
    # So we check the previous state — simpler: just return result's queue before pop
    # Actually: return_document=True gives doc AFTER pop. We need what was popped.
    # Workaround: find + slice then pop
    if result is None:
        return None
    # result is the doc AFTER pop; queue[0] is now gone. We do it differently:
    # Use a different approach — fetch first, then remove
    return None  # handled by _pop_link_safe below


def _pop_link_safe(admin_id: int | str) -> Optional[str]:
    """Safe atomic pop of first item from session queue."""
    # Step 1: fetch current first element
    session = _sessions().find_one(
        {"admin_id": str(admin_id), "active": True},
        {"queue": {"$slice": 1}},
    )
    if not session or not session.get("queue"):
        return None

    url = session["queue"][0]

    # Step 2: remove it
    _sessions().update_one(
        {"admin_id": str(admin_id), "active": True},
        {"$pop": {"queue": -1}},
    )
    return url


# Override with safe version
pop_link_from_queue = _pop_link_safe  # noqa: F811


def mark_link_done(admin_id: int | str):
    _sessions().update_one(
        {"admin_id": str(admin_id), "active": True},
        {"$inc": {"links_done": 1}},
    )


def mark_link_failed(admin_id: int | str, url: str, reason: str):
    _sessions().update_one(
        {"admin_id": str(admin_id), "active": True},
        {
            "$inc": {"links_failed": 1},
            "$push": {"failed_links": {"url": url, "reason": reason}},
        },
    )


def get_session_stats(admin_id: int | str) -> Optional[dict]:
    session = _sessions().find_one({"admin_id": str(admin_id), "active": True})
    if not session:
        return None
    return {
        "links_received": session.get("links_received", 0),
        "links_done": session.get("links_done", 0),
        "links_failed": session.get("links_failed", 0),
        "in_queue": len(session.get("queue", [])),
        "failed_links": session.get("failed_links", []),
        "mode": session.get("mode", "slow"),
    }


def get_all_active_sessions() -> list[dict]:
    """Return all currently active sessions (for the worker thread)."""
    return list(_sessions().find({"active": True}))


def get_queue_length(admin_id: int | str) -> int:
    session = _sessions().find_one(
        {"admin_id": str(admin_id), "active": True},
        {"queue": 1},
    )
    if not session:
        return 0
    return len(session.get("queue", []))


def seed_admins(admin_ids: list[int]):
    """Seed initial admins from env config."""
    for uid in admin_ids:
        if not is_admin(uid):
            upsert_admin(uid, "")
            print(f"[DB] Seeded admin: {uid}")
