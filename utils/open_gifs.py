"""
Picks a random open GIF/MP4/WEBM from the gifs/ folder.
"""

import os
import random
from pathlib import Path

GIFS_DIR = Path(__file__).parent.parent / "gifs"
SUPPORTED_EXTS = {".gif", ".mp4", ".webm"}


def get_random_gif() -> Path | None:
    """
    Returns the path to a random supported media file from the gifs/ folder.
    Returns None if the folder is empty or has no supported files.
    """
    if not GIFS_DIR.is_dir():
        return None

    files = [
        f for f in GIFS_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS
    ]
    if not files:
        return None

    return random.choice(files)


def get_gif_type(path: Path) -> str:
    """Return 'animation' for mp4/webm, 'animation' for gif too (Telegram handles both)."""
    ext = path.suffix.lower()
    if ext == ".gif":
        return "gif"
    return "animation"   # mp4/webm sent as video/animation
