import os
import sys
import asyncio
from pyrogram import Client, idle, enums
from pyrogram.types import BotCommand, InlineKeyboardMarkup
from config import Config
from core.player import player_manager

# ─── Native Colored Button Support (Telegram Bot API 9.4) ────────────────────
import pyrogram.types
_orig_btn_init = pyrogram.types.InlineKeyboardButton.__init__
def _patched_btn_init(self, *args, **kwargs):
    style = kwargs.pop("style", None)
    _orig_btn_init(self, *args, **kwargs)
    self.style = style  # always store, even if None
pyrogram.types.InlineKeyboardButton.__init__ = _patched_btn_init

def _markup_to_bot_api_json(markup: InlineKeyboardMarkup) -> list:
    """Convert Pyrogram InlineKeyboardMarkup → Bot API JSON with style support."""
    rows = []
    for row in markup.inline_keyboard:
        btn_row = []
        for btn in row:
            obj = {"text": btn.text}
            if btn.callback_data is not None:
                obj["callback_data"] = btn.callback_data
            elif btn.url is not None:
                obj["url"] = btn.url
            if getattr(btn, "style", None):
                obj["style"] = btn.style
            btn_row.append(obj)
        rows.append(btn_row)
    return rows

def make_card(text: str, expandable: bool = False) -> str:
    """Wrap text inside Telegram HTML Blockquote tag for global Card UI."""
    if not text:
        return ""
    clean = text.strip()
    if "<blockquote" in clean:
        return clean
    tag = "<blockquote expandable>" if expandable else "<blockquote>"
    return f"{tag}{clean}</blockquote>"

async def send_styled(chat_id: int, text: str, markup: InlineKeyboardMarkup = None, parse_mode: str = "HTML", message_id: int = None, expandable: bool = False, disable_preview: bool = True) -> dict:
    """
    Send or edit a message using Bot HTTP API so that native button 'style'
    (success/danger/primary) is preserved — Telegram Bot API 9.4+.
    Automatically wraps text in blockquote card format.
    """
    import aiohttp, json
    token = Config.BOT_TOKEN
    endpoint = f"https://api.telegram.org/bot{token}/"
    card_text = make_card(text, expandable=expandable)
    payload = {
        "chat_id": chat_id,
        "text": card_text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview
    }
    if markup:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": _markup_to_bot_api_json(markup)
        })
    method = "editMessageText" if message_id else "sendMessage"
    if message_id:
        payload["message_id"] = message_id
    try:
        timeout = aiohttp.ClientTimeout(total=8.0)
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.post(endpoint + method, json=payload) as resp:
                return await resp.json()
    except Exception:
        return {}

async def edit_styled(chat_id: int, text: str, markup: InlineKeyboardMarkup = None, parse_mode: str = "HTML", message_id: int = None, is_video: bool = False, expandable: bool = False, disable_preview: bool = True) -> dict:
    """
    Edit text or caption of a video message using Bot HTTP API so that native button 'style'
    is preserved. Automatically wraps text in blockquote card format.
    """
    import aiohttp, json
    token = Config.BOT_TOKEN
    endpoint = f"https://api.telegram.org/bot{token}/"
    
    card_text = make_card(text, expandable=expandable)
    method = "editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "parse_mode": parse_mode
    }
    
    if is_video:
        method = "editMessageCaption"
        payload["caption"] = card_text
    else:
        payload["text"] = card_text
        payload["disable_web_page_preview"] = disable_preview
        
    if markup:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": _markup_to_bot_api_json(markup)
        })
        
    try:
        timeout = aiohttp.ClientTimeout(total=8.0)
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.post(endpoint + method, json=payload) as resp:
                return await resp.json()
    except Exception:
        return {}

async def edit_reply_markup_styled(chat_id: int, message_id: int, markup: InlineKeyboardMarkup = None) -> dict:
    """Edit reply_markup of a message using Bot HTTP API so native button 'style' is preserved."""
    import aiohttp, json
    token = Config.BOT_TOKEN
    endpoint = f"https://api.telegram.org/bot{token}/editMessageReplyMarkup"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id
    }
    if markup:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": _markup_to_bot_api_json(markup)
        })
    try:
        timeout = aiohttp.ClientTimeout(total=8.0)
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.post(endpoint, json=payload) as resp:
                return await resp.json()
    except Exception:
        return {}

# Ensure config validation
Config.validate()

bot = Client(
    "gameover_yt_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    workdir=Config.PROJECT_ROOT,
    in_memory=True,
    proxy=Config.get_proxy_config()
)

assistant = Client(
    "gameover_yt_assistant",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    session_string=Config.STRING_SESSION,
    workdir=Config.PROJECT_ROOT,
    in_memory=True,
    proxy=Config.get_proxy_config()
)

async def main():
    print("[Bot] Starting clients...")
    await bot.start()
    await assistant.start()
    
    # Save bot username to Config dynamically
    me = await bot.get_me()
    Config.BOT_USERNAME = me.username
    print(f"[Bot] Started as @{me.username}")

    # Initialize PyTgCalls Player Manager
    await player_manager.init(assistant, bot)

    # Set Telegram native menu button commands
    try:
        await bot.set_bot_commands([
            BotCommand("vd", "Stream YouTube video on voice chat (720p 60fps)"),
            BotCommand("ad", "Stream YouTube high-quality audio"),
            BotCommand("list", "Play YouTube playlist in video mode"),
            BotCommand("la", "Play YouTube playlist in audio mode"),
            BotCommand("plresume", "Resume saved playlist from last song"),
            BotCommand("playlists", "View & resume saved group playlists history"),
            BotCommand("skip", "Skip to the next queued track"),
            BotCommand("pause", "Pause the active stream"),
            BotCommand("resume", "Resume the paused stream"),
            BotCommand("stop", "Stop playback and leave voice chat"),
            BotCommand("queue", "View upcoming songs in queue"),
            BotCommand("help", "Show help and commands guide"),
        ])
        print("[Bot] Native menu commands registered successfully!")
    except Exception as e:
        print(f"[Bot] Failed to set native menu commands: {e}")

    # Register plugins
    from plugins import play, welcome, admin
    play.register(bot)
    welcome.register(bot)
    admin.register(bot)
    
    print("[Bot] Bot is fully active and listening for group commands! Press Ctrl+C to stop.")
    await idle()

    # Stop clients on exit
    try:
        await asyncio.wait_for(asyncio.gather(
            player_manager.close(),
            bot.stop(),
            assistant.stop(),
            return_exceptions=True
        ), timeout=3.0)
    except:
        pass
    finally:
        import os
        os._exit(0)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\n[Bot] KeyboardInterrupt detected. Gracefully stopping clients...")
        try:
            loop.run_until_complete(asyncio.wait_for(asyncio.gather(
                player_manager.close(),
                bot.stop(),
                assistant.stop(),
                return_exceptions=True
            ), timeout=3.0))
        except:
            pass
        finally:
            import os
            os._exit(0)
    finally:
        try:
            loop.close()
        except:
            pass
