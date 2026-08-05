"""
👋 GameOver YT Streamer — Welcome Plugin
Welcomes new group members with a styled Roman Urdu card and welcome video from disk.
Caches welcome.mp4 file_id in SQLite, auto re-uploading if disk file changes.
"""

import os
import time
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import Config
from core.db import get_setting, set_setting, is_group_welcome_enabled, set_group_welcome_enabled, is_group_start_enabled, set_group_start_enabled
from bot import make_card

ROYAL_HEADER = "👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀᴍᴇʀ</b> 👑\n\n"

def register(app: Client):

    @app.on_message(filters.group, group=-1)
    async def auto_track_active_group(client: Client, message: Message):
        if message.chat and message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            from core.db import update_group_info
            update_group_info(message.chat.id, message.chat.title or "Group")
        message.continue_propagation()

    @app.on_message(filters.left_chat_member & filters.group)
    async def group_left_handler(client: Client, message: Message):
        me = await client.get_me()
        if message.left_chat_member and message.left_chat_member.id == me.id:
            chat_id = message.chat.id
            from core.db import remove_group_info
            remove_group_info(chat_id)
            print(f"[Welcome] Bot left/kicked from group {chat_id}. Purged from broadcast DB.")
            try:
                alert_text = make_card(
                    "🗑 <b>Bot Removed from Group</b>\n\n"
                    f"📌 <b>Group Name:</b> <code>{message.chat.title}</code>\n"
                    f"🆔 <b>Group ID:</b> <code>{chat_id}</code>"
                )
                await client.send_message(Config.OWNER_ID, alert_text, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

    @app.on_message(filters.command(["welcome"]) & filters.group)
    async def welcome_toggle_command(client: Client, message: Message):
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0

        # Admin Permission Check
        is_admin = False
        try:
            member = await client.get_chat_member(chat_id, user_id)
            if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER) or user_id in (Config.OWNER_ID,):
                is_admin = True
        except Exception:
            pass

        if not is_admin:
            await message.reply_text(
                make_card("⚠️ <b>Only Group Admins can change welcome settings!</b>"),
                parse_mode=enums.ParseMode.HTML
            )
            return

        args = message.command[1:] if len(message.command) > 1 else []
        if not args:
            current = is_group_welcome_enabled(chat_id)
            status_str = "🟢 <b>ACTIVE (ON)</b>" if current else "🔴 <b>DISABLED (OFF)</b>"
            await message.reply_text(
                make_card(
                    f"{ROYAL_HEADER}"
                    f"👋 <b>Group Welcome Card Settings</b>\n\n"
                    f"Current Status: {status_str}\n\n"
                    f"<b>Usage:</b>\n"
                    f"👉 <code>/welcome on</code> - Enable welcome card\n"
                    f"👉 <code>/welcome off</code> - Disable welcome card"
                ),
                parse_mode=enums.ParseMode.HTML
            )
            return

        sub = args[0].lower()
        if sub in ("on", "enable", "true", "active", "1"):
            set_group_welcome_enabled(chat_id, True)
            await message.reply_text(
                make_card(
                    f"{ROYAL_HEADER}"
                    f"✅ <b>Group Welcome Card ENABLED (ON)!</b>\n\n"
                    f"New members will now receive a welcome card when joining."
                ),
                parse_mode=enums.ParseMode.HTML
            )
        elif sub in ("off", "disable", "false", "deactive", "0"):
            set_group_welcome_enabled(chat_id, False)
            await message.reply_text(
                make_card(
                    f"{ROYAL_HEADER}"
                    f"🛑 <b>Group Welcome Card DISABLED (OFF)!</b>\n\n"
                    f"Welcome cards will no longer be sent when new members join."
                ),
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await message.reply_text(
                make_card("❌ Invalid argument! Use <code>/welcome on</code> or <code>/welcome off</code>."),
                parse_mode=enums.ParseMode.HTML
            )

    @app.on_message(filters.command(["start"]) & filters.group)
    async def start_group_command(client: Client, message: Message):
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0

        # If user passed arguments like /start on or /start off
        args = message.command[1:] if len(message.command) > 1 else []
        if args:
            is_admin = False
            try:
                member = await client.get_chat_member(chat_id, user_id)
                if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER) or user_id == Config.OWNER_ID:
                    is_admin = True
            except Exception:
                pass

            if not is_admin:
                await message.reply_text(
                    make_card("⚠️ <b>Only Group Admins can change start settings!</b>"),
                    parse_mode=enums.ParseMode.HTML
                )
                return

            sub = args[0].lower()
            if sub in ("on", "enable", "true", "active", "1"):
                set_group_start_enabled(chat_id, True)
                await message.reply_text(
                    make_card(
                        f"{ROYAL_HEADER}"
                        f"✅ <b>Group Start Intro Card ENABLED (ON)!</b>\n\n"
                        f"Bot will now respond to <code>/start</code> in this group."
                    ),
                    parse_mode=enums.ParseMode.HTML
                )
            elif sub in ("off", "disable", "false", "deactive", "0"):
                set_group_start_enabled(chat_id, False)
                await message.reply_text(
                    make_card(
                        f"{ROYAL_HEADER}"
                        f"🛑 <b>Group Start Intro Card DISABLED (OFF)!</b>\n\n"
                        f"Bot will no longer respond to <code>/start</code> in this group."
                    ),
                    parse_mode=enums.ParseMode.HTML
                )
            else:
                await message.reply_text(
                    make_card("❌ Invalid argument! Use <code>/start on</code> or <code>/start off</code>."),
                    parse_mode=enums.ParseMode.HTML
                )
            return

        # If /start is typed without arguments in group: check if start is enabled for this group
        if not is_group_start_enabled(chat_id):
            return

        user_name = message.from_user.first_name if message.from_user else "User"
        bot_username = Config.BOT_USERNAME or (await client.get_me()).username

        start_text = make_card(
            f"{ROYAL_HEADER}"
            f"🎮 <b>ɢᴀṁᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀṁᴇʀ is Active!</b>\n\n"
            f"👋 Hello {user_name}!\n"
            "Group voice chat me High-Quality Video (720p 60fps) + Bass Audio stream karne ke liye niche diye commands use karein:\n\n"
            "👉 <code>/vd [song/link]</code> - Stream Video\n"
            "👉 <code>/ad [song/link]</code> - Stream Audio"
        )
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("ADD ME TO YOUR GROUP 👑", url=f"https://t.me/{bot_username}?startgroup=true", style="success")]
        ])
        await message.reply_text(start_text, reply_markup=buttons, parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command(["start"]) & filters.private)
    async def start_private_command(client: Client, message: Message):
        user = message.from_user
        username_str = f"@{user.username}" if user and user.username else "None"
        user_name = user.first_name if user else "User"

        # Record user in SQLite DB
        if user:
            from core.db import add_pm_user
            add_pm_user(user.id, user_name, user.username)

        # Owner alert on PM /start (Sends 2 Messages: Event Details + Live Stats Overview)
        try:
            if user and user.id != Config.OWNER_ID:
                from core.db import get_total_pm_users, get_total_groups_count
                total_users = get_total_pm_users()
                total_groups = get_total_groups_count()
                total_combined = total_users + total_groups

                # Message 1: Event Card
                alert_text = make_card(
                    "👤 <b>New User Started Bot!</b>\n\n"
                    f"• <b>Name:</b> {user_name}\n"
                    f"• <b>Username:</b> {username_str}\n"
                    f"• <b>User ID:</b> <code>{user.id}</code>"
                )
                await client.send_message(Config.OWNER_ID, alert_text, parse_mode=enums.ParseMode.HTML)

                # Message 2: Live Stats Overview
                stats_text = make_card(
                    "📊 <b>Bot Live Reach Overview</b>\n\n"
                    f"👤 <b>Total PM Users:</b> <code>{total_users}</code>\n"
                    f"👥 <b>Total Active Groups:</b> <code>{total_groups}</code>\n"
                    f"🌐 <b>Total Combined Reach:</b> <code>{total_combined} chats</code>"
                )
                await client.send_message(Config.OWNER_ID, stats_text, parse_mode=enums.ParseMode.HTML)
        except Exception as e:
            print(f"[Welcome] Start owner notification note: {e}")

        start_text = make_card(
            f"{ROYAL_HEADER}"
            f"👋 <b>WELCOME, {user_name.upper()}!</b> 🔥\n\n"
            "I am <b>GameOver YT Streamer</b> — A PREMIUM HIGH-PERFORMANCE YOUTUBE VIDEO AND AUDIO STREAMING BOT.\n\n"
            "⚡ <b>SUPPORTED SOURCES:</b>\n"
            "• <b>YOUTUBE</b> (LOCKED 1080P 60 FPS / STUDIO 320KBPS STEREO)\n\n"
            "CLICK THE BUTTONS BELOW TO EXPLORE COMMANDS!"
        )
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ ADD ME TO YOUR GROUP 👑", url=f"https://t.me/{Config.BOT_USERNAME}?startgroup=true", style="success")
            ],
            [
                InlineKeyboardButton("📚 HELP & COMMANDS", callback_data="cb_help", style="primary"),
                InlineKeyboardButton("ℹ️ ABOUT BOT", callback_data="cb_about", style="primary")
            ],
            [
                InlineKeyboardButton("🎵 PLAY COMMANDS", callback_data="cb_play_cmds", style="success"),
                InlineKeyboardButton("👑 ADMIN PANEL", callback_data="cb_admin_cmds", style="danger")
            ]
        ])
        await message.reply_text(start_text, reply_markup=buttons, parse_mode=enums.ParseMode.HTML)

    @app.on_callback_query(filters.regex(r"^cb_"))
    async def welcome_callbacks(client: Client, query: CallbackQuery):
        data = query.data
        user_name = query.from_user.first_name if query.from_user else "User"

        if data == "cb_help":
            await query.answer("Opening Help & Commands...")
            text = make_card(
                f"{ROYAL_HEADER}"
                f"📚 <b>ɢᴀᴍᴇᴏᴠᴇʀ Cᴏᴍᴍᴀɴᴅs Dᴀsʜʙᴏᴀʀᴅ</b> 📚\n\n"
                f"🎵 <b>USER PLAY COMMANDS:</b>\n"
                f"👉 <code>/vd [song/link]</code> - Stream 1080p Video in Group VC\n"
                f"👉 <code>/ad [song/link]</code> - Stream 320kbps Audio in Group VC\n"
                f"👉 <code>/dw [yt link]</code> - Direct Download Video to Telegram Chat\n"
                f"👉 <code>/skip</code> - Skip to next song in queue\n"
                f"👉 <code>/pause</code> - Pause current playback\n"
                f"👉 <code>/resume</code> - Resume paused stream\n"
                f"👉 <code>/stop</code> - Stop playback & clear queue\n"
                f"👉 <code>/queue</code> - View track queue list\n\n"
                f"👑 <b>ADMIN CONTROL COMMANDS:</b>\n"
                f"👉 <code>/admin</code> - Open Full Interactive Control Panel\n"
                f"👉 <code>/approvecontrol</code> - Reply to user to grant bot control\n"
                f"👉 <code>/broadcast</code> - Broadcast announcement to groups\n"
            )
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎵 PLAY COMMANDS", callback_data="cb_play_cmds", style="success"),
                    InlineKeyboardButton("👑 ADMIN COMMANDS", callback_data="cb_admin_cmds", style="danger")
                ],
                [
                    InlineKeyboardButton("🔙 BACK TO MAIN MENU", callback_data="cb_back_start", style="primary"),
                    InlineKeyboardButton("❌ CLOSE", callback_data="cb_close", style="danger")
                ]
            ])
            try:
                await query.message.edit_text(text, reply_markup=markup, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

        elif data == "cb_about":
            await query.answer("Opening About Info...")
            text = make_card(
                f"{ROYAL_HEADER}"
                f"ℹ️ <b>Aʙᴏᴜᴛ GᴀᴍᴇOᴠᴇʀ YT Sᴛʀᴇᴀᴍᴇʀ</b> ℹ️\n\n"
                f"• <b>Bot Version:</b> <code>v3.0 Ultra High Performance</code>\n"
                f"• <b>Architecture:</b> <code>2-Tier Engine (nskmedia.net + Playwright Loader)</code>\n"
                f"• <b>Cookie Status:</b> <code>100% PURGED (Zero Cookies / Zero Captchas)</code>\n"
                f"• <b>Audio Quality:</b> <code>320kbps Studio Stereo Sound</code>\n"
                f"• <b>Video Target:</b> <code>1080p 60FPS / 2K Supported</code>\n\n"
                f"👑 <b>Developed & Powered by GameOver Automation Team</b>"
            )
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔙 BACK TO MAIN MENU", callback_data="cb_back_start", style="primary"),
                    InlineKeyboardButton("❌ CLOSE", callback_data="cb_close", style="danger")
                ]
            ])
            try:
                await query.message.edit_text(text, reply_markup=markup, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

        elif data == "cb_play_cmds":
            await query.answer("Opening Play Guide...")
            text = make_card(
                f"{ROYAL_HEADER}"
                f"🎵 <b>Pʟᴀʏ Cᴏᴍᴍᴀɴᴅs Gᴜɪᴅᴇ</b> 🎵\n\n"
                f"Group Voice Chat me high-speed playback ke liye Commands:\n\n"
                f"🎬 <b>VIDEO MODE (1080p 60FPS):</b>\n"
                f"• <code>/vd [song name]</code>\n"
                f"• <code>/vd https://youtube.com/watch?v=...</code>\n\n"
                f"🎵 <b>AUDIO MODE (320kbps Studio):</b>\n"
                f"• <code>/ad [song name]</code>\n"
                f"• <code>/ad https://youtu.be/...</code>\n\n"
                f"📥 <b>DIRECT CHAT DOWNLOAD:</b>\n"
                f"• <code>/dw [youtube link]</code>"
            )
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔙 BACK TO MENU", callback_data="cb_help", style="primary"),
                    InlineKeyboardButton("❌ CLOSE", callback_data="cb_close", style="danger")
                ]
            ])
            try:
                await query.message.edit_text(text, reply_markup=markup, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

        elif data == "cb_admin_cmds":
            await query.answer("Opening Admin Guide...")
            text = make_card(
                f"{ROYAL_HEADER}"
                f"👑 <b>Aᴅᴍɪɴ Cᴏɴᴛʀᴏʟ Gᴜɪᴅᴇ</b> 👑\n\n"
                f"Owner & Approved Sudo Users ke Control Commands:\n\n"
                f"⚡ <code>/admin</code> - Interactive Control Dashboard (Video Quality, FPS, File Cache, Speed Test)\n"
                f"👥 <code>/approvecontrol</code> - Reply to a user's message in group to grant them bot commands control\n"
                f"📢 <code>/broadcast</code> - Send announcement card to all active group chats\n"
                f"📡 <code>/nst</code> - Run 5-worker Cloudflare speed test on VPS"
            )
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔙 BACK TO MENU", callback_data="cb_help", style="primary"),
                    InlineKeyboardButton("❌ CLOSE", callback_data="cb_close", style="danger")
                ]
            ])
            try:
                await query.message.edit_text(text, reply_markup=markup, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

        elif data == "cb_back_start":
            await query.answer("Back to Menu...")
            text = make_card(
                f"{ROYAL_HEADER}"
                f"👋 <b>WELCOME, {user_name.upper()}!</b> 🔥\n\n"
                "I am <b>GameOver YT Streamer</b> — A PREMIUM HIGH-PERFORMANCE YOUTUBE VIDEO AND AUDIO STREAMING BOT.\n\n"
                "⚡ <b>SUPPORTED SOURCES:</b>\n"
                "• <b>YOUTUBE</b> (LOCKED 1080P 60 FPS / STUDIO 320KBPS STEREO)\n\n"
                "CLICK THE BUTTONS BELOW TO EXPLORE COMMANDS!"
            )
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("➕ ADD ME TO YOUR GROUP 👑", url=f"https://t.me/{Config.BOT_USERNAME}?startgroup=true", style="success")
                ],
                [
                    InlineKeyboardButton("📚 HELP & COMMANDS", callback_data="cb_help", style="primary"),
                    InlineKeyboardButton("ℹ️ ABOUT BOT", callback_data="cb_about", style="primary")
                ],
                [
                    InlineKeyboardButton("🎵 PLAY COMMANDS", callback_data="cb_play_cmds", style="success"),
                    InlineKeyboardButton("👑 ADMIN PANEL", callback_data="cb_admin_cmds", style="danger")
                ]
            ])
            try:
                await query.message.edit_text(text, reply_markup=buttons, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

        elif data == "cb_close":
            await query.answer("Closing...")
            try:
                await query.message.delete()
            except Exception:
                pass

    @app.on_message(filters.command(["dw", "download"]))
    async def download_command(client: Client, message: Message):
        chat_id = message.chat.id
        args = message.command[1:] if len(message.command) > 1 else []
        if not args:
            await message.reply_text(
                make_card(
                    f"{ROYAL_HEADER}"
                    f"📥 <b>DIRECT MEDIA DOWNLOADER</b>\n\n"
                    f"Send YouTube Link to download video/audio file directly to this chat!\n\n"
                    f"<b>Usage:</b>\n"
                    f"👉 <code>/dw https://youtu.be/agXAuW9qG70</code>\n"
                    f"👉 <code>/dw Blue Eyes Yo Yo Honey Singh</code>"
                ),
                parse_mode=enums.ParseMode.HTML
            )
            return

        query_str = " ".join(args)
        status_msg = await message.reply_text(
            make_card(
                f"{ROYAL_HEADER}"
                f"⚡ <b>Resolving & Downloading Media File...</b>\n"
                f"📌 <b>Query:</b> <code>{query_str[:40]}</code>\n"
                f"⏳ <i>Executing 2-Tier Engine... Please wait!</i>"
            ),
            parse_mode=enums.ParseMode.HTML
        )

        from core.scrapers import resolve_query_to_url, extract_video_id
        from core.player import download_song_ytdlp, get_cached_item
        import os

        yt_url = await resolve_query_to_url(query_str)
        if not yt_url:
            await status_msg.edit_text(make_card("❌ <b>Could not resolve YouTube link!</b>"), parse_mode=enums.ParseMode.HTML)
            return

        video_id = extract_video_id(yt_url)
        dest_path = os.path.join(Config.DOWNLOADS_DIR, f"{video_id}_video.mp4")

        # Download via Tier 2 Playwright / Loader
        ok = await download_song_ytdlp(yt_url, dest_path, "video")
        if not ok or not os.path.exists(dest_path):
            await status_msg.edit_text(make_card("❌ <b>Media download failed!</b>"), parse_mode=enums.ParseMode.HTML)
            return

        cached = get_cached_item(video_id, "video") or {}
        title = cached.get("title") or "YouTube Video"

        sz_bytes = os.path.getsize(dest_path)
        sz_mb = sz_bytes / (1024 * 1024)

        await status_msg.edit_text(
            make_card(
                f"{ROYAL_HEADER}"
                f"📤 <b>Uploading Media ({sz_mb:.1f} MB) to Telegram Chat...</b>\n"
                f"📌 <b>Title:</b> <code>{title}</code>"
            ),
            parse_mode=enums.ParseMode.HTML
        )

        dl_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📹 VIDEO FILE ({sz_mb:.1f} MB)", callback_data="cb_close", style="success")]
        ])

        caption_text = (
            f"👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ Dᴏᴡɴʟᴏᴀᴅᴇʀ</b> 👑\n\n"
            f"📌 <b>Title:</b> <b>{title}</b>\n"
            f"📦 <b>Size:</b> <code>{sz_mb:.1f} MB</code>\n"
            f"⚡ <b>Engine:</b> 2-Tier Playwright Engine\n"
            f"🔗 <b>Link:</b> <a href=\"{yt_url}\">Watch on YouTube</a>"
        )

        try:
            # Telegram Bot limit for video player is 50MB. Send as document if > 50MB!
            if sz_bytes > 50 * 1024 * 1024:
                await client.send_document(
                    chat_id=chat_id,
                    document=dest_path,
                    caption=caption_text,
                    reply_markup=dl_markup,
                    parse_mode=enums.ParseMode.HTML
                )
            else:
                await client.send_video(
                    chat_id=chat_id,
                    video=dest_path,
                    supports_streaming=True,
                    caption=caption_text,
                    reply_markup=dl_markup,
                    parse_mode=enums.ParseMode.HTML
                )
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit_text(make_card(f"❌ Failed to send media file: {e}"), parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.new_chat_members & filters.group)
    async def welcome_new_members(client: Client, message: Message):
        chat_id = message.chat.id
        
        # Avoid welcoming the bot itself or other bots
        me = await client.get_me()
        new_members = message.new_chat_members
        
        target_members = []
        for m in new_members:
            if m.id == me.id:
                # Send Owner Instant PM Alert (2 Messages) when Bot is Added to a New Group
                try:
                    added_by = message.from_user
                    added_by_str = f"{added_by.first_name} (@{added_by.username})" if added_by and added_by.username else (added_by.first_name if added_by else "Unknown")
                    group_title = message.chat.title or "Unknown Group"
                    group_username = f"@{message.chat.username}" if message.chat.username else "Private Group"
                    
                    from core.db import update_group_info, get_total_pm_users, get_total_groups_count
                    update_group_info(chat_id, group_title)

                    total_users = get_total_pm_users()
                    total_groups = get_total_groups_count()
                    total_combined = total_users + total_groups

                    # Message 1: Event Card
                    alert_msg = make_card(
                        "🎉 <b>Bot Added to New Group!</b>\n\n"
                        f"📌 <b>Group Name:</b> <code>{group_title}</code>\n"
                        f"🆔 <b>Group ID:</b> <code>{chat_id}</code>\n"
                        f"🔗 <b>Username/Link:</b> {group_username}\n"
                        f"👤 <b>Added By:</b> {added_by_str}"
                    )
                    await client.send_message(Config.OWNER_ID, alert_msg, parse_mode=enums.ParseMode.HTML)

                    # Message 2: Live Stats Overview
                    stats_msg = make_card(
                        "📊 <b>Bot Live Reach Overview</b>\n\n"
                        f"👤 <b>Total PM Users:</b> <code>{total_users}</code>\n"
                        f"👥 <b>Total Active Groups:</b> <code>{total_groups}</code>\n"
                        f"🌐 <b>Total Combined Reach:</b> <code>{total_combined} chats</code>"
                    )
                    await client.send_message(Config.OWNER_ID, stats_msg, parse_mode=enums.ParseMode.HTML)
                except Exception as owner_alert_err:
                    print(f"[Welcome] Owner group add alert note: {owner_alert_err}")

                # Bot itself joined a group - send intro message
                intro_text = make_card(
                    f"{ROYAL_HEADER}"
                    "🎮 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀṁᴇʀ is here!</b>\n\n"
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
        
        welcome_text = make_card(
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
