import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_ID: int = int(os.getenv("API_ID", 0))
    API_HASH: str = os.getenv("API_HASH", "")
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    STRING_SESSION: str = os.getenv("STRING_SESSION", "")
    OWNER_ID: int = int(os.getenv("OWNER_ID", 0))
    OWNER_USERNAME: str = os.getenv("OWNER_USERNAME", "")
    LOG_GROUP_ID: int = int(os.getenv("LOG_GROUP_ID", "-1003975646434"))
    LOG_CHANNEL_LINK: str = os.getenv("LOG_CHANNEL_LINK", "https://t.me/+aRRNo19DcGE3MzQ0")

    @classmethod
    def get_owner_url(cls) -> str:
        if cls.OWNER_USERNAME:
            uname = cls.OWNER_USERNAME.replace("@", "").strip()
            return f"https://t.me/{uname}"
        if cls.OWNER_ID:
            return f"tg://user?id={cls.OWNER_ID}"
        return "https://t.me"

    DOWNLOADS_DIR: str = os.getenv("DOWNLOADS_DIR", "downloads")
    PROJECT_ROOT: str = os.path.dirname(os.path.abspath(__file__))

    BOT_NAME: str = "🎬 GameOver YT Streamer"
    BOT_USERNAME: str = ""

    # ── Proxy Configuration (Cloudflare WARP Local Proxy / SOCKS5 / HTTP) ──
    USE_PROXY: bool = os.getenv("USE_PROXY", "False").lower() == "true"
    PROXY_SCHEME: str = os.getenv("PROXY_SCHEME", "http")
    PROXY_HOSTNAME: str = os.getenv("PROXY_HOSTNAME", "127.0.0.1")
    PROXY_PORT: int = int(os.getenv("PROXY_PORT", 4001))
    PROXY_USERNAME: str = os.getenv("PROXY_USERNAME", "")
    PROXY_PASSWORD: str = os.getenv("PROXY_PASSWORD", "")

    @classmethod
    def get_proxy_config(cls) -> dict or None:
        if not cls.USE_PROXY:
            return None
        cfg = {
            "scheme": cls.PROXY_SCHEME,
            "hostname": cls.PROXY_HOSTNAME,
            "port": cls.PROXY_PORT
        }
        if cls.PROXY_USERNAME:
            cfg["username"] = cls.PROXY_USERNAME
        if cls.PROXY_PASSWORD:
            cfg["password"] = cls.PROXY_PASSWORD
        return cfg

    @classmethod
    def get_proxy_url(cls) -> str or None:
        if not cls.USE_PROXY:
            return None
        if cls.PROXY_USERNAME and cls.PROXY_PASSWORD:
            return f"{cls.PROXY_SCHEME}://{cls.PROXY_USERNAME}:{cls.PROXY_PASSWORD}@{cls.PROXY_HOSTNAME}:{cls.PROXY_PORT}"
        return f"{cls.PROXY_SCHEME}://{cls.PROXY_HOSTNAME}:{cls.PROXY_PORT}"

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
