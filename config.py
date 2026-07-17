import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_ID: int = int(os.getenv("API_ID", 0))
    API_HASH: str = os.getenv("API_HASH", "")
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    STRING_SESSION: str = os.getenv("STRING_SESSION", "")
    OWNER_ID: int = int(os.getenv("OWNER_ID", 0))

    DOWNLOADS_DIR: str = os.getenv("DOWNLOADS_DIR", "downloads")
    PROJECT_ROOT: str = os.path.dirname(os.path.abspath(__file__))

    BOT_NAME: str = "🎬 GameOver YT Streamer"
    BOT_USERNAME: str = ""

    @staticmethod
    def validate():
        missing = []
        if not Config.API_ID:
            missing.append("API_ID")
        if not Config.API_HASH:
            missing.append("API_HASH")
        if not Config.BOT_TOKEN:
            missing.append("BOT_TOKEN")
        if not Config.STRING_SESSION:
            missing.append("STRING_SESSION")

        if missing:
            raise ValueError(
                f"\n\n❌ .env file mein ye fields khali hain:\n" +
                "\n".join(f"  - {m}" for m in missing) +
                "\n\nPehle .env file setup karein phir bot run karein!\n"
            )
