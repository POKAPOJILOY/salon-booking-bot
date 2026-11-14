import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MASTER_ID = int(os.getenv("MASTER_ID", "0"))
TZ = ZoneInfo(os.getenv("TZ", "Europe/Moscow"))
DB_PATH = Path(os.getenv("DB_PATH", "salon.db"))
WIDGETS_ENABLED = os.getenv("WIDGETS_ENABLED", "false").lower() == "true"
WEBAPP_PUBLIC_URL = os.getenv("WEBAPP_PUBLIC_URL", "").rstrip("/")
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", "80"))
