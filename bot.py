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

async def send_styled(chat_id: int, text: str, markup: InlineKeyboardMarkup = None, parse_mode: str = "HTML", message_id: int = None) -> dict:
    """
    Send or edit a message using Bot HTTP API so that native button 'style'
    (success/danger/primary) is preserved — Telegram Bot API 9.4+.
    Returns the response JSON dict.
    """
    import aiohttp, json
    token = Config.BOT_TOKEN
    endpoint = f"https://api.telegram.org/bot{token}/"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    if markup:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": _markup_to_bot_api_json(markup)
        })
    method = "editMessageText" if message_id else "sendMessage"
    if message_id:
        payload["message_id"] = message_id
    try:
        timeout = aiohttp.ClientTimeout(total=10.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(endpoint + method, json=payload) as resp:
                return await resp.json()
    except Exception as e:
        print(f"[BotAPI] send_styled error: {e}")
        return {}

async def edit_styled(chat_id: int, text: str, markup: InlineKeyboardMarkup = None, parse_mode: str = "HTML", message_id: int = None, is_video: bool = False) -> dict:
    """
    Edit text or caption of a video message using Bot HTTP API so that native button 'style'
    is preserved.
    """
    import aiohttp, json
    token = Config.BOT_TOKEN
    endpoint = f"https://api.telegram.org/bot{token}/"
    
    method = "editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "parse_mode": parse_mode
    }
    
    if is_video:
        method = "editMessageCaption"
        payload["caption"] = text
    else:
        payload["text"] = text
        payload["disable_web_page_preview"] = True
        
    if markup:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": _markup_to_bot_api_json(markup)
        })
        
    try:
        timeout = aiohttp.ClientTimeout(total=10.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(endpoint + method, json=payload) as resp:
                return await resp.json()
    except Exception as e:
        print(f"[BotAPI] edit_styled error: {e}")
        return {}

# Ensure config validation
Config.validate()

bot = Client(
    "gameover_yt_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    workdir=Config.PROJECT_ROOT
)

assistant = Client(
    "gameover_yt_assistant",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    session_string=Config.STRING_SESSION,
    workdir=Config.PROJECT_ROOT
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
            BotCommand("video", "Stream YouTube video on voice chat (720p 60fps)"),
            BotCommand("audio", "Stream YouTube audio on voice chat"),
            BotCommand("ad", "Stream YouTube audio on voice chat"),
            BotCommand("stop", "Stop playback and leave voice chat"),
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
