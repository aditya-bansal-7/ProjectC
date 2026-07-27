import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # Telegram
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    # MongoDB
    MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    MONGO_DB: str = os.getenv("MONGO_DB", "projectc")

    # Project B
    PROJECT_B_URL: str = os.getenv("PROJECT_B_URL", "http://localhost:3000").rstrip("/")
    PROJECT_B_SECRET: str = os.getenv("PROJECT_B_SECRET", "")

    # Super-admins (can register/remove admins via /addadmin)
    ADMIN_IDS: list[int] = field(
        default_factory=lambda: [
            int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
        ]
    )


settings = Settings()

if not settings.BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN is missing in .env")

if not settings.MONGODB_URI:
    raise RuntimeError("❌ MONGODB_URI is missing in .env")
