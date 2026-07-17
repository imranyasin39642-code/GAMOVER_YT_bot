"""
👋 GameOver YT Streamer — Welcome Plugin
Welcomes new group members with a styled Roman Urdu card and welcome video from disk.
Caches welcome.mp4 file_id in SQLite, auto re-uploading if disk file changes.
"""

import os
import time
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import Config
from core.db import get_setting, set_setting, is_group_welcome_enabled

ROYAL_HEADER = "👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀᴍᴇʀ</b> 👑\n\n"

def register(app: Client):

    @app.on_message(filters.new_chat_members & filters.group)
    async def welcome_new_members(client: Client, message: Message):
        chat_id = message.chat.id
        
        # Avoid welcoming the bot itself or other bots
        me = await client.get_me()
        new_members = message.new_chat_members
        
        target_members = []
        for m in new_members:
            if m.id == me.id:
                # Bot itself joined a group - send intro message
                intro_text = (
                    f"{ROYAL_HEADER}"
                    "🎮 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀᴍᴇʀ is here!</b>\n\n"
                    "Main group voice chat mein <b>High-Quality Video + Bass Equalized Audio</b> stream kar sakta hoon.\n\n"
                    "🎬 <b>Video Playback start karne ke liye:</b>\n"
                    "👉 <code>/vd [song name/link]</code> ya <code>/video [song name/link]</code>\n\n"
                    "🎵 <b>Audio Playback start karne ke liye:</b>\n"
                    "👉 <code>/audio [song name/link]</code> ya <code>/ad [song name/link]</code>"
                )
                await message.reply_text(intro_text, parse_mode=enums.ParseMode.HTML)
                return
            if not m.is_bot:
                target_members.append(m)
                
        if not target_members:
            return
            
        # Check if welcome is enabled for this group
        if not is_group_welcome_enabled(chat_id):
            return
            
        # Format user mentions
        mentions_str = ", ".join(m.mention for m in target_members)
        group_name = message.chat.title
        
        welcome_text = (
            f"👑 <b>Welcome to {group_name}!</b> 👑\n\n"
            f"👋 Swagat hai, {mentions_str}!\n\n"
            f"🎬 <b>Video Playback start karne ke liye:</b>\n"
            f"👉 <code>/vd [song name/link]</code> ya <code>/video [song name/link]</code>\n\n"
            f"🎵 <b>Audio Playback start karne ke liye:</b>\n"
            f"👉 <code>/audio [song name/link]</code> ya <code>/ad [song name/link]</code>\n"
        )
        
        # Add quick access buttons
        welcome_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("ADD ME TO YOUR GROUP 👑", url=f"https://t.me/{Config.BOT_USERNAME}?startgroup=true", style="success")]
        ])
        
        # Retrieve or Upload Welcome Video from root folder (case-insensitive check)
        base_dir = Config.PROJECT_ROOT
        video_path = os.path.join(base_dir, "welcome.mp4")
        if not os.path.exists(video_path):
            video_path = os.path.join(base_dir, "Welcome.mp4")
        
        from core.media_helper import send_cached_video
        await send_cached_video(
            client=client,
            chat_id=chat_id,
            video_path=video_path,
            cache_key_prefix="welcome_video",
            caption=welcome_text,
            reply_markup=welcome_markup,
            parse_mode=enums.ParseMode.HTML
        )
