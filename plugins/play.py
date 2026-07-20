import os
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config import Config
from core.player import player_manager
from core.db import is_sudo_user, add_started_user

ROYAL_HEADER = "👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀᴍᴇʀ</b> 👑\n\n"

def register(app: Client):

    @app.on_message(filters.command("start"))
    async def start_command(client: Client, message: Message):
        bot_username = Config.BOT_USERNAME or (await client.get_me()).username
        user_name = message.from_user.first_name if message.from_user else "User"
        
        # Add to database started users list
        if message.from_user:
            add_started_user(
                user_id=message.from_user.id,
                username=message.from_user.username or "",
                first_name=message.from_user.first_name or ""
            )
        
        welcome_text = (
            f"👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀᴍᴇʀ</b> 👑\n\n"
            f"🔥 <b>WELCOME, {user_name.upper()}!</b> 🔥\n\n"
            f"I AM 🎬 <b>GameOver YT Streamer</b>, A PREMIUM HIGH-PERFORMANCE YOUTUBE VIDEO AND AUDIO STREAMING BOT.\n\n"
            f"⚡ <b>SUPPORTED SOURCES:</b>\n"
            f"• <b>YOUTUBE</b> (LOCKED 720P 60 FPS)\n\n"
            f"CLICK THE BUTTONS BELOW TO EXPLORE COMMANDS!"
        )
        
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ ADD ME TO YOUR GROUP", url=f"https://t.me/{bot_username}?startgroup=true", style="success")
            ],
            [
                InlineKeyboardButton("📚 HELP MENU", callback_data="welcome_help", style="primary"),
                InlineKeyboardButton("ℹ️ ABOUT BOT", callback_data="welcome_about", style="primary")
            ]
        ])
        
        # Send start.mp4 video if it exists in the root folder, else fallback to text
        base_dir = Config.PROJECT_ROOT
        video_path = os.path.join(base_dir, "start.mp4")
        if not os.path.exists(video_path):
            video_path = os.path.join(base_dir, "Start.mp4")
            
        from core.media_helper import send_cached_video
        await send_cached_video(
            client=client,
            chat_id=message.chat.id,
            video_path=video_path,
            cache_key_prefix="start_video",
            caption=welcome_text,
            reply_markup=buttons,
            parse_mode=enums.ParseMode.HTML
        )

    @app.on_message(filters.command(["vd", "video"]) & filters.group)
    async def play_command(client: Client, message: Message):
        chat_id = message.chat.id
        if len(message.command) < 2:
            await message.reply_text(
                f"{ROYAL_HEADER}❌ <b>Song name ya YouTube link dein!</b>\n"
                f"Examples:\n"
                f"• <code>/vd blue eyes</code>\n"
                f"• <code>/vd https://youtu.be/B-99Pm--78Y</code>"
            )
            return

        query = " ".join(message.command[1:])
        status_msg = await message.reply_text(f"{ROYAL_HEADER}⏳ <b>Processing... Please wait!</b>")
        
        req_name = message.from_user.first_name if message.from_user else "User"
        req_id = message.from_user.id if message.from_user else 0
        
        asyncio.create_task(player_manager.play(chat_id, query, mode="video", status_msg=status_msg, requested_by=req_name, requested_by_id=req_id))

    @app.on_message(filters.command(["audio", "ad"]) & filters.group)
    async def audio_command(client: Client, message: Message):
        chat_id = message.chat.id
        if len(message.command) < 2:
            await message.reply_text(
                f"{ROYAL_HEADER}❌ <b>Song name ya YouTube link dein!</b>\n"
                f"Examples:\n"
                f"• <code>/ad blue eyes</code>\n"
                f"• <code>/ad https://youtu.be/B-99Pm--78Y</code>"
            )
            return

        query = " ".join(message.command[1:])
        status_msg = await message.reply_text(f"{ROYAL_HEADER}⏳ <b>Processing... Please wait!</b>")
        
        req_name = message.from_user.first_name if message.from_user else "User"
        req_id = message.from_user.id if message.from_user else 0
        
        asyncio.create_task(player_manager.play(chat_id, query, mode="audio", status_msg=status_msg, requested_by=req_name, requested_by_id=req_id))

    @app.on_message(filters.command(["skip", "next"]) & filters.group)
    async def skip_command(client: Client, message: Message):
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        active_req_id = player_manager.active_requester_id.get(chat_id, 0)

        # Check if anything is playing
        if chat_id not in player_manager.active_calls:
            await message.reply_text(f"{ROYAL_HEADER}⚠️ <b>Abhi kuch bhi play nahi ho raha!</b>")
            return

        # Permission check: requester / owner / sudo / group admin can skip
        is_allowed = False
        if user_id in (Config.OWNER_ID, active_req_id) or is_sudo_user(user_id):
            is_allowed = True
        else:
            try:
                member = await client.get_chat_member(chat_id, user_id)
                if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                    is_allowed = True
            except Exception:
                pass

        if not is_allowed:
            await message.reply_text("⚠️ Only the requester or an Admin can skip!")
            return

        skipped = await player_manager.skip(chat_id)
        if not skipped:
            await message.reply_text(f"{ROYAL_HEADER}⏹ <b>Queue empty! Playback stopped.</b>")

    @app.on_message(filters.command("stop") & filters.group)
    async def stop_command(client: Client, message: Message):
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        active_req_id = player_manager.active_requester_id.get(chat_id, 0)
        
        is_allowed = False
        if user_id in (Config.OWNER_ID, active_req_id) or is_sudo_user(user_id):
            is_allowed = True
        else:
            try:
                member = await client.get_chat_member(chat_id, user_id)
                if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                    is_allowed = True
            except Exception:
                pass
                
        if not is_allowed:
            await message.reply_text("⚠️ Only the requester or an Admin can stop playback!")
            return
            
        await player_manager.stop(chat_id)
        await message.reply_text(f"{ROYAL_HEADER}⏹ <b>Playback stopped!</b>")

    @app.on_callback_query(filters.regex(r"^play_"))
    async def player_callbacks(client: Client, query: CallbackQuery):
        data = query.data.split("|")
        action = data[0]

        def _perm_check(user_id, chat_id, requested_by_id):
            if user_id in (Config.OWNER_ID, requested_by_id) or is_sudo_user(user_id):
                return True
            return False  # async admin check done inline below

        if action in ("play_stop", "play_skip", "play_pause", "play_resume"):
            chat_id = int(data[1])
            requested_by_id = int(data[2]) if len(data) > 2 else 0
            user_id = query.from_user.id if query.from_user else 0

            is_allowed = _perm_check(user_id, chat_id, requested_by_id)
            if not is_allowed:
                try:
                    member = await client.get_chat_member(chat_id, user_id)
                    if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                        is_allowed = True
                except Exception:
                    pass

            if not is_allowed:
                await query.answer("⚠️ Only the requester or an Admin can control playback!", show_alert=True)
                return

            if action == "play_stop":
                await player_manager.stop(chat_id)
                try:
                    await query.message.delete()
                except Exception:
                    pass
                await query.answer("⏹ Stopped!")
            elif action == "play_skip":
                await query.answer("⏭ Skipping...")
                skipped = await player_manager.skip(chat_id)
                if not skipped:
                    try:
                        await query.message.delete()
                    except Exception:
                        pass
            elif action == "play_pause":
                ok = await player_manager.pause(chat_id)
                if ok:
                    await query.answer("⏸ Paused!")
                else:
                    await query.answer("❌ Stream not active or cannot pause!", show_alert=True)
            elif action == "play_resume":
                ok = await player_manager.resume(chat_id)
                if ok:
                    await query.answer("▶ Resumed!")
                else:
                    await query.answer("❌ Stream not active or cannot resume!", show_alert=True)

        elif action == "play_close":
            try:
                await query.message.delete()
            except Exception:
                pass
            try:
                await query.answer()
            except Exception:
                pass

    @app.on_callback_query(filters.regex(r"^welcome_"))
    async def welcome_callbacks(client: Client, query: CallbackQuery):
        data = query.data
        chat_id = query.message.chat.id
        message_id = query.message.id
        is_video = bool(query.message.video or query.message.animation or query.message.document)
        user_name = query.from_user.first_name if query.from_user else "User"
        bot_username = Config.BOT_USERNAME or (await client.get_me()).username
        
        from bot import edit_styled
        
        if data == "welcome_help":
            help_text = (
                f"👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀᴍᴇʀ</b> 👑\n\n"
                f"📚 <b>HELP & COMMANDS MENU</b>\n\n"
                f"Aap in commands ke zariye voice chat mein high-quality stream kar sakte hain:\n\n"
                f"🎬 <b>Video Stream:</b>\n"
                f"• <code>/vd [YouTube Link/Search Query]</code>\n"
                f"• <code>/video [YouTube Link/Search Query]</code>\n\n"
                f"🎵 <b>Audio Stream:</b>\n"
                f"• <code>/ad [YouTube Link/Search Query]</code>\n"
                f"• <code>/audio [YouTube Link/Search Query]</code>\n\n"
                f"⏹ <b>Controls:</b>\n"
                f"• <code>/stop</code> - Stop playback and leave voice chat.\n"
                f"• <code>/admin</code> - Open interactive admin control panel."
            )
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 BACK", callback_data="welcome_back", style="primary")
            ]])
            await edit_styled(chat_id, help_text, markup, message_id=message_id, is_video=is_video)
            await query.answer()
            
        elif data == "welcome_about":
            about_text = (
                f"👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀᴍᴇʀ</b> 👑\n\n"
                f"I AM A PREMIUM HIGH-PERFORMANCE YOUTUBE BOT DESIGNED TO STREAM BOTH VIDEO AND AUDIO LIVE IN TELEGRAM GROUP VOICE CHATS.\n\n"
                f"Designed and maintained by the 👑 <b>GameOver Team</b>."
            )
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 BACK", callback_data="welcome_back", style="primary")
            ]])
            await edit_styled(chat_id, about_text, markup, message_id=message_id, is_video=is_video)
            await query.answer()
            
        elif data == "welcome_back":
            welcome_text = (
                f"👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀᴍᴇʀ</b> 👑\n\n"
                f"🔥 <b>WELCOME, {user_name.upper()}!</b> 🔥\n\n"
                f"I AM 🎬 <b>GameOver YT Streamer</b>, A PREMIUM HIGH-PERFORMANCE YOUTUBE VIDEO AND AUDIO STREAMING BOT.\n\n"
                f"⚡ <b>SUPPORTED SOURCES:</b>\n"
                f"• <b>YOUTUBE</b> (LOCKED 720P 60 FPS)\n\n"
                f"CLICK THE BUTTONS BELOW TO EXPLORE COMMANDS!"
            )
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("➕ ADD ME TO YOUR GROUP", url=f"https://t.me/{bot_username}?startgroup=true", style="success")
                ],
                [
                    InlineKeyboardButton("📚 HELP MENU", callback_data="welcome_help", style="primary"),
                    InlineKeyboardButton("ℹ️ ABOUT BOT", callback_data="welcome_about", style="primary")
                ]
            ])
            await edit_styled(chat_id, welcome_text, buttons, message_id=message_id, is_video=is_video)
            await query.answer()
