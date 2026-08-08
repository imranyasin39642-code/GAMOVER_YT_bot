import os
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config import Config
from core.player import player_manager
from core.db import is_sudo_user, add_started_user, update_group_info, is_group_bot_active
from bot import make_card

ROYAL_HEADER = "👑 <b>ɢᴀṁᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀṁᴇʀ</b> 👑\n\n"

def build_effects_markup(selected_effect: str, chat_id: int, requested_by_id: int) -> InlineKeyboardMarkup:
    effects_data = [
        ("normal",    "🎵", "NORMAL"),
        ("bassboost", "🔊", "BASS BOOST"),
        ("nightcore", "⚡", "NIGHTCORE"),
        ("slowed",    "🐢", "SLOWED"),
        ("lofi",      "☕", "LOFI"),
        ("8d",        "🎧", "8D"),
        ("classic",   "🎼", "CLASSIC"),
        ("jack",      "🎸", "JACK"),
    ]

    buttons = []
    row = []
    for key, icon, label in effects_data:
        if key == selected_effect:
            btn_text = f"✅ {icon} {label}"
            btn_style = "success"
        else:
            btn_text = f"❌ {icon} {label}"
            btn_style = "danger"
        row.append(InlineKeyboardButton(btn_text, callback_data=f"fx_set|{key}|{chat_id}|{requested_by_id}", style=btn_style))
        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("BACK", callback_data=f"fx_back|{chat_id}|{requested_by_id}", style="primary")])
    return InlineKeyboardMarkup(buttons)

def cmd(cmds):
    if isinstance(cmds, str):
        cmds = [cmds]
    bot_name = Config.BOT_USERNAME or "Gameover_Music_bot"
    all_cmds = []
    for c in cmds:
        c_clean = c.lstrip("/")
        all_cmds.append(c_clean.lower())
        all_cmds.append(f"{c_clean.lower()}@{bot_name.lower()}")
        all_cmds.append(f"{c_clean.lower()}@{bot_name}")
    return filters.command(all_cmds, prefixes=["/", "!", "."])

def register(app: Client):

    @app.on_message(filters.group, group=-1)
    async def auto_register_group(client: Client, message: Message):
        if message.chat and message.chat.id:
            title = message.chat.title or "Group Chat"
            update_group_info(message.chat.id, title)

    @app.on_message(cmd(["start"]))
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
        
        is_group = message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP)
        
        if is_group:
            welcome_text = (
                f"Hey <b>{user_name}</b>,\n"
                f"This is <b>GameOver YT Streamer</b> !\n\n"
                f"A music player bot with some awesome and useful features.\n\n"
                f"<i>Click on the button below to add me to your group!</i>"
            )
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Add me to your group", url=f"https://t.me/{bot_username}?startgroup=true", style="success")
                ]
            ])
        else:
            welcome_text = (
                f"Hey <b>{user_name}</b>,\n"
                f"This is <b>GameOver YT Streamer</b> !\n\n"
                f"A music player bot with some awesome and useful features.\n\n"
                f"<i>Click on the buttons below to get information about my commands.</i>"
            )
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Add me to your group", url=f"https://t.me/{bot_username}?startgroup=true", style="success")
                ],
                [
                    InlineKeyboardButton("Help", callback_data="welcome_help", style="primary"),
                    InlineKeyboardButton("Owner", url=Config.get_owner_url(), style="primary")
                ],
                [
                    InlineKeyboardButton("About", callback_data="welcome_about", style="danger")
                ]
            ])
        
        base_dir = Config.PROJECT_ROOT
        media_path = None
        for fn in ["start.mp4", "Start.mp4", "start.jpg", "Start.jpg", "start.png", "Start.png", "start.jpeg"]:
            p = os.path.join(base_dir, fn)
            if os.path.exists(p):
                media_path = p
                break
            
        if media_path and (media_path.endswith(".jpg") or media_path.endswith(".png") or media_path.endswith(".jpeg")):
            try:
                await client.send_photo(
                    chat_id=message.chat.id,
                    photo=media_path,
                    caption=welcome_text,
                    reply_markup=buttons,
                    parse_mode=enums.ParseMode.HTML
                )
                return
            except Exception as e:
                print(f"[Start] Error sending start photo: {e}")

        from core.media_helper import send_cached_video
        await send_cached_video(
            client=client,
            chat_id=message.chat.id,
            video_path=media_path or os.path.join(base_dir, "start.mp4"),
            cache_key_prefix="start_video",
            caption=welcome_text,
            reply_markup=buttons,
            parse_mode=enums.ParseMode.HTML
        )

async def send_search_status(client: Client, chat_id: int, query: str) -> Message:
    """Send animated searching sticker or clean searching status card."""
    # List of high quality Telegram animated searching sticker IDs
    sticker_ids = [
        "CAACAgUAAxkBAAEC3_Fl89wzS-Wk4Y7QG...", 
        "CAACAgIAAxkBAAIFNmW0x0_..."
    ]
    for st in sticker_ids:
        try:
            return await client.send_sticker(chat_id, st)
        except Exception:
            pass
            
    # Fallback to elegant searching card
    return await client.send_message(
        chat_id,
        make_card(
            f"👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀᴍᴇʀ</b> 👑\n\n"
            f"🔍 <b>S E A R C H I N G   Y O U T U B E...</b>\n"
            f"📌 <b>Track:</b> <code>{query}</code>\n\n"
            f"⚡ <i>Resolving media stream in 2 seconds...</i>"
        )
    )

    @app.on_message(cmd(["vd", "video"]))
    async def play_command(client: Client, message: Message):
        if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            return
        chat_id = message.chat.id
        query = " ".join(message.command[1:]).strip() if len(message.command) > 1 else ""
        print(f"[Command] Received /vd in group {chat_id} | Query: '{query}'")

        if not query:
            await message.reply_text(
                make_card(
                    f"{ROYAL_HEADER}❌ <b>Please specify a track name or YouTube URL!</b>\n\n"
                    f"👉 <b>Click to Copy Examples:</b>\n"
                    f"• <code>/vd blue eyes</code>\n"
                    f"• <code>/vd https://youtu.be/B-99Pm--78Y</code>"
                )
            )
            return

        status_msg = await send_search_status(client, chat_id, query)
        req_name = message.from_user.first_name if message.from_user else "User"
        req_id = message.from_user.id if message.from_user else 0
        asyncio.create_task(player_manager.play(chat_id, query, mode="video", status_msg=status_msg, requested_by=req_name, requested_by_id=req_id))

    @app.on_message(cmd(["audio", "ad"]))
    async def audio_command(client: Client, message: Message):
        if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            return
        chat_id = message.chat.id
        query = " ".join(message.command[1:]).strip() if len(message.command) > 1 else ""
        print(f"[Command] Received /ad in group {chat_id} | Query: '{query}'")

        if not query:
            await message.reply_text(
                make_card(
                    f"{ROYAL_HEADER}❌ <b>Please specify a track name or YouTube URL!</b>\n\n"
                    f"👉 <b>Click to Copy Examples:</b>\n"
                    f"• <code>/ad blue eyes</code>\n"
                    f"• <code>/ad https://youtu.be/B-99Pm--78Y</code>"
                )
            )
            return

        status_msg = await send_search_status(client, chat_id, query)
        req_name = message.from_user.first_name if message.from_user else "User"
        req_id = message.from_user.id if message.from_user else 0
        asyncio.create_task(player_manager.play(chat_id, query, mode="audio", status_msg=status_msg, requested_by=req_name, requested_by_id=req_id))

    @app.on_message(cmd(["playlist", "list"]))
    async def playlist_command(client: Client, message: Message):
        if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            return
        chat_id = message.chat.id
        query = " ".join(message.command[1:]).strip() if len(message.command) > 1 else ""
        print(f"[Command] Received /list in group {chat_id} | Query: '{query}'")

        if query:
            status_msg = await message.reply_text(make_card(f"{ROYAL_HEADER}⏳ <b>Processing Playlist... Please wait!</b>"))
            req_name = message.from_user.first_name if message.from_user else "User"
            req_id = message.from_user.id if message.from_user else 0
            asyncio.create_task(player_manager.play(
                chat_id=chat_id,
                youtube_url=query,
                mode="video",
                status_msg=status_msg,
                requested_by=req_name,
                requested_by_id=req_id
            ))
            return

        # Empty command handling: check for saved playlist resume
        from core.db import get_playlist_state
        state = get_playlist_state(chat_id, "video") or get_playlist_state(chat_id, "audio")
        if state and state.get("playlist_id"):
            last_idx = state.get("last_index", 0)
            mode = state.get("mode", "video")
            card_text = (
                f"{ROYAL_HEADER}📜 <b>SAVED PLAYLIST FOUND!</b>\n\n"
                f"📌 <b>Last Played:</b> <code>Song #{last_idx + 1}</code>\n"
                f"🎧 <b>Mode:</b> <code>{mode.title()}</code>\n\n"
                f"<i>Resume saved playlist or start over from Song #1:</i>"
            )
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(f"▶️ RESUME (Song #{last_idx + 1})", callback_data=f"pl_resume|{chat_id}|{mode}"),
                    InlineKeyboardButton("🔄 RESTART (#1)", callback_data=f"pl_restart|{chat_id}|{mode}")
                ],
                [InlineKeyboardButton("🗑 CLOSE", callback_data="play_close", style="danger")]
            ])
            await message.reply_text(make_card(card_text), reply_markup=buttons)
            return

        await message.reply_text(
            make_card(
                f"{ROYAL_HEADER}❌ <b>YouTube playlist link dein!</b>\n\n"
                f"👉 <b>Click to Copy Example:</b>\n"
                f"• <code>/list https://www.youtube.com/playlist?list=RDMM</code>"
            )
        )

    @app.on_message(cmd(["playlistaudio", "listaudio", "la"]))
    async def playlist_audio_command(client: Client, message: Message):
        if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            return
        chat_id = message.chat.id
        query = " ".join(message.command[1:]).strip() if len(message.command) > 1 else ""
        print(f"[Command] Received /la in group {chat_id} | Query: '{query}'")

        if query:
            status_msg = await message.reply_text(make_card(f"{ROYAL_HEADER}⏳ <b>Processing Audio Playlist... Please wait!</b>"))
            req_name = message.from_user.first_name if message.from_user else "User"
            req_id = message.from_user.id if message.from_user else 0
            asyncio.create_task(player_manager.play(
                chat_id=chat_id,
                youtube_url=query,
                mode="audio",
                status_msg=status_msg,
                requested_by=req_name,
                requested_by_id=req_id
            ))
            return

        from core.db import get_playlist_state
        state = get_playlist_state(chat_id, "audio") or get_playlist_state(chat_id, "video")
        if state and state.get("playlist_id"):
            last_idx = state.get("last_index", 0)
            mode = state.get("mode", "audio")
            card_text = (
                f"{ROYAL_HEADER}📜 <b>SAVED AUDIO PLAYLIST FOUND!</b>\n\n"
                f"📌 <b>Last Played:</b> <code>Song #{last_idx + 1}</code>\n"
                f"🎧 <b>Mode:</b> <code>{mode.title()}</code>\n\n"
                f"<i>Resume saved audio playlist or start over:</i>"
            )
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(f"▶️ RESUME (Song #{last_idx + 1})", callback_data=f"pl_resume|{chat_id}|{mode}"),
                    InlineKeyboardButton("🔄 RESTART (#1)", callback_data=f"pl_restart|{chat_id}|{mode}")
                ],
                [InlineKeyboardButton("🗑 CLOSE", callback_data="play_close", style="danger")]
            ])
            await message.reply_text(make_card(card_text), reply_markup=buttons)
            return

        await message.reply_text(
            make_card(
                f"{ROYAL_HEADER}❌ <b>YouTube playlist link dein!</b>\n\n"
                f"👉 <b>Click to Copy Example:</b>\n"
                f"• <code>/la https://www.youtube.com/playlist?list=RDMM</code>"
            )
        )

    @app.on_message(cmd(["plresume", "playlistresume", "resumeplaylist"]))
    async def pl_resume_command(client: Client, message: Message):
        if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            return
        chat_id = message.chat.id
        if not is_group_bot_active(chat_id):
            return
        
        from core.db import get_playlist_state
        state = get_playlist_state(chat_id, "video") or get_playlist_state(chat_id, "audio")
        if not state or not state.get("playlist_id"):
            await message.reply_text(make_card(f"{ROYAL_HEADER}⚠️ <b>Iss group me koi saved playlist state nahi mili!</b>\nPehle koi playlist play karein."))
            return

        pl_id = state["playlist_id"]
        mode = state["mode"]
        last_idx = state["last_index"]

        status_msg = await message.reply_text(make_card(f"{ROYAL_HEADER}⏳ <b>Resuming Playlist from Song #{last_idx + 1}... Please wait!</b>"))

        req_name = message.from_user.first_name if message.from_user else "User"
        req_id = message.from_user.id if message.from_user else 0

        playlist_url = f"https://www.youtube.com/playlist?list={pl_id}" if not pl_id.startswith("http") else pl_id

        # Ensure pending_playlists is populated if bot was restarted
        if chat_id not in player_manager.pending_playlists:
            from core.scrapers import extract_youtube_playlist
            entries = await extract_youtube_playlist(playlist_url)
            if entries:
                player_manager.pending_playlists[chat_id] = {
                    "url": playlist_url,
                    "pl_id": pl_id,
                    "mode": mode,
                    "entries": entries,
                    "requested_by": req_name,
                    "requested_by_id": req_id
                }

        if chat_id in player_manager.pending_playlists:
            asyncio.create_task(player_manager.execute_playlist(
                chat_id=chat_id,
                start_from_index=last_idx,
                mode=mode,
                status_msg=status_msg
            ))
        else:
            try:
                await status_msg.edit_text(make_card("❌ <b>Unable to load playlist! Please provide a valid playlist link.</b>"))
            except Exception:
                pass

    @app.on_message(cmd(["playlists", "myplaylists", "savedplaylists", "plhistory"]))
    async def group_playlists_history_command(client: Client, message: Message):
        if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            return
        chat_id = message.chat.id
        if not is_group_bot_active(chat_id):
            return
        
        from core.db import get_all_playlist_states
        states = get_all_playlist_states(chat_id)
        if not states:
            await message.reply_text(make_card(
                f"{ROYAL_HEADER}⚠️ <b>Iss group me koi saved playlists history nahi hai!</b>\n\n"
                f"Pehle group me koi YouTube Playlist link play karein (e.g. <code>/list [URL]</code>)."
            ))
            return

        lines = []
        buttons = []

        for idx, st in enumerate(states, start=1):
            pl_id = st["playlist_id"]
            mode_label = "🎥 Video" if st["mode"] == "video" else "🎧 Audio"
            last_idx = st["last_index"]
            tot = st["total_tracks"]
            song_num = last_idx + 1 if last_idx is not None else 1
            pl_title = st.get("title") or f"Playlist ID: {pl_id[:16]}..."

            lines.append(
                f"<b>{idx}. {pl_title}</b>\n"
                f"   └ 📍 <b>Last Position:</b> Song #{song_num} of {tot} ({mode_label})"
            )

            buttons.append([
                InlineKeyboardButton(
                    f"▶ Resume #{idx}: Song #{song_num}",
                    callback_data=f"pl_hist_res|{chat_id}|{pl_id}|{st['mode']}|{last_idx}",
                    style="success"
                ),
                InlineKeyboardButton(
                    f"🔄 Start Over",
                    callback_data=f"pl_hist_res|{chat_id}|{pl_id}|{st['mode']}|0",
                    style="primary"
                )
            ])

        buttons.append([InlineKeyboardButton("🗑 Close", callback_data="play_close")])

        card_text = (
            f"👑 <b>ɢᴀṁᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀṁᴇʀ</b> 👑\n\n"
            f"📋 <b>SAVED PLAYLISTS HISTORY IN THIS GROUP:</b>\n\n"
            + "\n\n".join(lines) +
            f"\n\n⚡ <i>Niche diye gaye button par click karke apni manpasand playlist wahi song position se resume karein!</i>"
        )

        from bot import send_styled
        await send_styled(
            chat_id=chat_id,
            text=card_text,
            markup=InlineKeyboardMarkup(buttons)
        )

    @app.on_callback_query(filters.regex(r"^pl_hist_res\|"))
    async def pl_history_resume_callback(client: Client, query: CallbackQuery):
        chat_id = query.message.chat.id
        parts = query.data.split("|")
        # format: pl_hist_res|chat_id|pl_id|mode|start_index
        pl_id = parts[2]
        mode = parts[3]
        start_idx = int(parts[4])

        await query.answer(f"▶ Resuming playlist from Song #{start_idx + 1}...")

        req_name = query.from_user.first_name if query.from_user else "User"
        req_id = query.from_user.id if query.from_user else 0
        playlist_url = f"https://www.youtube.com/playlist?list={pl_id}" if not pl_id.startswith("http") else pl_id

        from bot import edit_styled
        await edit_styled(
            chat_id=chat_id,
            text=f"{ROYAL_HEADER}⏳ <b>Loading &amp; Resuming Playlist from Song #{start_idx + 1}... Please wait!</b>",
            message_id=query.message.id
        )

        from core.scrapers import extract_youtube_playlist
        entries = await extract_youtube_playlist(playlist_url)
        if not entries:
            await edit_styled(
                chat_id=chat_id,
                text=f"{ROYAL_HEADER}❌ <b>Playlist load nahi ho saki ya private hai!</b>",
                message_id=query.message.id
            )
            return

        player_manager.pending_playlists[chat_id] = {
            "url": playlist_url,
            "pl_id": pl_id,
            "mode": mode,
            "entries": entries,
            "requested_by": req_name,
            "requested_by_id": req_id
        }

        asyncio.create_task(player_manager.execute_playlist(
            chat_id=chat_id,
            start_from_index=start_idx,
            mode=mode,
            status_msg=query.message
        ))

    @app.on_message(cmd(["pause", "cpause"]))
    async def pause_command(client: Client, message: Message):
        if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            return
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        active_req_id = player_manager.active_requester_id.get(chat_id, 0)
        from core.db import is_user_approved
        
        is_allowed = False
        if user_id in (Config.OWNER_ID, active_req_id) or is_sudo_user(user_id) or is_user_approved(chat_id, user_id):
            is_allowed = True
        else:
            try:
                member = await client.get_chat_member(chat_id, user_id)
                if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                    is_allowed = True
            except Exception:
                pass
                
        if not is_allowed:
            await message.reply_text(make_card("⚠️ Only the requester, an Admin, or an Approved User can pause!"))
            return

        ok = await player_manager.pause(chat_id)
        if ok:
            await message.reply_text(make_card(f"{ROYAL_HEADER}⏸ <b>Playback Paused!</b>"))
        else:
            await message.reply_text(make_card(f"{ROYAL_HEADER}⚠️ <b>Abhi kuch bhi play nahi ho raha!</b>"))

    @app.on_message(cmd(["resume", "cresume"]))
    async def resume_command(client: Client, message: Message):
        if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            return
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        active_req_id = player_manager.active_requester_id.get(chat_id, 0)
        from core.db import is_user_approved
        
        is_allowed = False
        if user_id in (Config.OWNER_ID, active_req_id) or is_sudo_user(user_id) or is_user_approved(chat_id, user_id):
            is_allowed = True
        else:
            try:
                member = await client.get_chat_member(chat_id, user_id)
                if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                    is_allowed = True
            except Exception:
                pass
                
        if not is_allowed:
            await message.reply_text(make_card("⚠️ Only the requester, an Admin, or an Approved User can resume!"))
            return

        ok = await player_manager.resume(chat_id)
        if ok:
            await message.reply_text(make_card(f"{ROYAL_HEADER}▶ <b>Playback Resumed!</b>"))
        else:
            await message.reply_text(make_card(f"{ROYAL_HEADER}⚠️ <b>Kuch bhi paused nahi hai!</b>"))

    @app.on_message(cmd(["skip", "cskip", "next", "cnext", "seek", "cseek"]))
    async def skip_command(client: Client, message: Message):
        if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            return
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        active_req_id = player_manager.active_requester_id.get(chat_id, 0)
        from core.db import is_user_approved

        if chat_id not in player_manager.active_calls:
            await message.reply_text(make_card(f"{ROYAL_HEADER}⚠️ <b>Abhi kuch bhi play nahi ho raha!</b>"))
            return

        is_allowed = False
        if user_id in (Config.OWNER_ID, active_req_id) or is_sudo_user(user_id) or is_user_approved(chat_id, user_id):
            is_allowed = True
        else:
            try:
                member = await client.get_chat_member(chat_id, user_id)
                if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                    is_allowed = True
            except Exception:
                pass

        if not is_allowed:
            await message.reply_text(make_card("⚠️ Only the requester, an Admin, or an Approved User can skip/seek!"))
            return

        parts = (message.text or message.caption or "").split()
        args = parts[1:] if len(parts) > 1 else []
        cmd_name = parts[0][1:].lower() if parts else ""

        if args or cmd_name in ("seek", "cseek"):
            if not args:
                await message.reply_text(
                    make_card(
                        f"{ROYAL_HEADER}❌ <b>Time duration specify karein!</b>\n\n"
                        f"👉 <b>Examples:</b>\n"
                        f"• <code>/seek 10s</code>\n"
                        f"• <code>/seek 1m</code>\n"
                        f"• <code>/skip 30s</code>"
                    )
                )
                return

            def _parse_time(time_str: str) -> int:
                import re
                time_str = time_str.strip().lower()
                if time_str.isdigit():
                    return int(time_str)
                total = 0
                matches = re.findall(r'(\d+)\s*([smh])?', time_str)
                for num_s, unit in matches:
                    n = int(num_s)
                    if unit == 'm':
                        total += n * 60
                    elif unit == 'h':
                        total += n * 3600
                    else:
                        total += n
                return total

            secs = _parse_time(args[0])
            if secs <= 0:
                await message.reply_text(make_card("❌ Invalid time! E.g. <code>/seek 10s</code> or <code>/seek 1m</code>."))
                return

            user_name = message.from_user.first_name if message.from_user else "User"
            user_link = f"<a href=\"tg://user?id={user_id}\">{user_name}</a>" if user_id > 0 else f"<b>{user_name}</b>"

            ok = await player_manager.seek(chat_id, secs)
            if ok:
                from bot import send_styled
                await send_styled(
                    chat_id=chat_id,
                    text=f"⏩ <b>Stream seeked forward by {secs}s by:</b> {user_link}"
                )
            else:
                await message.reply_text(make_card("❌ Seek failed or offset exceeds stream length!"))
            return

        skipped = await player_manager.skip(chat_id)
        if not skipped:
            await message.reply_text(make_card(f"{ROYAL_HEADER}⏹ <b>Queue empty! Playback stopped.</b>"))

    @app.on_message(cmd(["stop", "cstop", "end", "cend"]))
    async def stop_command(client: Client, message: Message):
        if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            return
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        active_req_id = player_manager.active_requester_id.get(chat_id, 0)
        from core.db import is_user_approved
        
        is_allowed = False
        if user_id in (Config.OWNER_ID, active_req_id) or is_sudo_user(user_id) or is_user_approved(chat_id, user_id):
            is_allowed = True
        else:
            try:
                member = await client.get_chat_member(chat_id, user_id)
                if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                    is_allowed = True
            except Exception:
                pass
                
        if not is_allowed:
            await message.reply_text(make_card("⚠️ Only the requester, an Admin, or an Approved User can stop playback!"))
            return
            
        user_name = message.from_user.first_name if message.from_user else "User"
        user_link = f"<a href=\"tg://user?id={user_id}\">{user_name}</a>" if user_id > 0 else f"<b>{user_name}</b>"
        await player_manager.stop(chat_id)
        await message.reply_text(
            make_card(f"{ROYAL_HEADER}⏹ <b>ᴘʟᴀʏʙᴀᴄᴋ sᴛᴏᴘᴘᴇᴅ ʙʏ:</b> {user_link}")
        )

    # ── Owner-Only Approved Control Commands ────────────────────────────────
    @app.on_message(cmd(["approvecontrol", "approvedcontrol", "approvecontroll", "aprovedcontroll", "aprovedcontrol", "approve", "approved"]))
    async def approve_control_command(client: Client, message: Message):
        user_id = message.from_user.id if message.from_user else 0
        if user_id != Config.OWNER_ID and not is_sudo_user(user_id):
            await message.reply_text(make_card(f"{ROYAL_HEADER}⚠️ <b>Sirf Bot Owner / Sudo hi Approved Control grant kar sakta hai!</b>"))
            return

        target_user = None
        if message.reply_to_message and message.reply_to_message.from_user:
            target_user = message.reply_to_message.from_user
        elif len(message.command) > 1:
            query = message.command[1].strip()
            try:
                target_user = await client.get_users(query)
            except Exception:
                pass

        if not target_user:
            await message.reply_text(
                make_card(
                    f"{ROYAL_HEADER}❌ <b>Target User specify karein!</b>\n"
                    f"Kisi user ke message par <b>reply</b> karke <code>/approvecontrol</code> chalayein ya <code>/approve @username</code> dein."
                )
            )
            return

        chat_id = message.chat.id
        from core.db import add_approved_user
        add_approved_user(chat_id, target_user.id, target_user.first_name, user_id)

        target_link = f"<a href=\"tg://user?id={target_user.id}\">{target_user.first_name}</a>"
        card = make_card(
            f"👑 <b>ɢᴀṁᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀṁᴇʀ</b> 👑\n\n"
            f"✅ <b>CONTROL PERMISSION GRANTED!</b>\n\n"
            f"👤 <b>User:</b> {target_link} [<code>{target_user.id}</code>]\n"
            f"⚡ <i>Ab aap is group me buttons (▷, II, ➕, ▢) aur commands (/pause, /resume, /skip, /stop) control kar sakte hain!</i>"
        )
        await message.reply_text(card)

    @app.on_message(cmd(["unapprovecontrol", "unapprovedcontrol", "unapprovecontroll", "unaprovedcontroll", "unaprovedcontrol", "unapprove", "unapproved"]))
    async def unapprove_control_command(client: Client, message: Message):
        user_id = message.from_user.id if message.from_user else 0
        if user_id != Config.OWNER_ID and not is_sudo_user(user_id):
            await message.reply_text(make_card(f"{ROYAL_HEADER}⚠️ <b>Sirf Bot Owner / Sudo hi Approved Control revoke kar sakta hai!</b>"))
            return

        target_user = None
        if message.reply_to_message and message.reply_to_message.from_user:
            target_user = message.reply_to_message.from_user
        elif len(message.command) > 1:
            query = message.command[1].strip()
            try:
                target_user = await client.get_users(query)
            except Exception:
                pass

        if not target_user:
            await message.reply_text(
                make_card(
                    f"{ROYAL_HEADER}❌ <b>Target User specify karein!</b>\n"
                    f"Kisi user ke message par <b>reply</b> karke <code>/unapprovecontrol</code> chalayein."
                )
            )
            return

        chat_id = message.chat.id
        from core.db import remove_approved_user
        remove_approved_user(chat_id, target_user.id)

        target_link = f"<a href=\"tg://user?id={target_user.id}\">{target_user.first_name}</a>"
        card = make_card(
            f"👑 <b>ɢᴀṁᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀṁᴇʀ</b> 👑\n\n"
            f"❌ <b>CONTROL PERMISSION REVOKED!</b>\n\n"
            f"👤 <b>User:</b> {target_link} [<code>{target_user.id}</code>]\n"
            f"⚡ <i>Ab aap player controls use nahi kar sakte.</i>"
        )
        await message.reply_text(card)

    @app.on_message(cmd(["approvedusers", "approvelist"]))
    async def approved_users_command(client: Client, message: Message):
        chat_id = message.chat.id
        from core.db import get_approved_users
        import time
        users = get_approved_users(chat_id)

        if not users:
            await message.reply_text(make_card(f"{ROYAL_HEADER}👥 <b>Iss group me koi approved control user nahi hai!</b>"))
            return

        from datetime import datetime
        lines = []
        buttons_list = []
        for i, u in enumerate(users, start=1):
            uid = u["user_id"]
            uname = u["user_name"] or f"User {uid}"
            by_id = u.get("approved_by", 0)
            t_str = datetime.fromtimestamp(u.get("added_at", time.time())).strftime("%d %b %Y, %I:%M %p")
            lines.append(
                f"<b>{i}.</b> <a href=\"tg://user?id={uid}\">{uname}</a> [<code>{uid}</code>]\n"
                f"   📅 <i>Approved On: {t_str}</i>\n"
                f"   👑 <i>Approved By: <code>{by_id}</code></i>\n"
            )
            buttons_list.append([InlineKeyboardButton(f"❌ Revoke: {uname[:16]}", callback_data=f"unapprove_user|{chat_id}|{uid}")])

        buttons_list.append([InlineKeyboardButton("🗑 Close", callback_data="play_close")])

        users_text = (
            f"👑 <b>ɢᴀṁᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀṁᴇʀ</b> 👑\n\n"
            f"👥 <b>TOTAL APPROVED CONTROL USERS:</b> <code>{len(users)}</code>\n\n" +
            "\n".join(lines)
        )
        await message.reply_text(make_card(users_text), reply_markup=InlineKeyboardMarkup(buttons_list))

    @app.on_message(filters.command("reset"))
    async def reset_system_command(client: Client, message: Message):
        user_id = message.from_user.id if message.from_user else 0
        if user_id != Config.OWNER_ID and not is_sudo_user(user_id):
            await message.reply_text(make_card(f"{ROYAL_HEADER}⚠️ <b>Sirf Bot Owner hi /reset command chala sakta hai!</b>"))
            return

        status_msg = await message.reply_text(make_card(f"{ROYAL_HEADER}⏳ <b>Executing Owner System Reset... Please wait!</b>"))

        result = await player_manager.full_reset()

        reset_card = make_card(
            f"👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀᴍᴇʀ</b> 👑\n\n"
            f"✅ <b>SYSTEM RESET COMPLETE!</b>\n\n"
            f"📦 <b>Deleted Downloaded Files:</b> <code>{result['deleted_files']} files</code>\n"
            f"🛑 <b>Stopped Active Calls:</b> <code>{result['stopped_calls']} calls</code>\n"
            f"🧹 <b>Database &amp; Playlist States:</b> <code>Wiped Clean</code>\n\n"
            f"⚡ <i>All downloaded videos/audios, queues, and playlist states have been fully reset!</i>"
        )
        try:
            await status_msg.edit_text(reset_card)
        except Exception:
            await message.reply_text(reset_card)

    @app.on_message(filters.command(["reload", "restart", "reloadbot"]))
    async def reload_system_command(client: Client, message: Message):
        user_id = message.from_user.id if message.from_user else 0
        if user_id != Config.OWNER_ID and not is_sudo_user(user_id):
            await message.reply_text(make_card(f"{ROYAL_HEADER}⚠️ <b>Sirf Bot Owner hi /reload command chala sakta hai!</b>"))
            return

        status_msg = await message.reply_text(
            make_card(
                f"👑 <b>ɢᴀṁᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀṁᴇʀ</b> 👑\n\n"
                f"🔄 <b>RELOADING BOT PROCESS...</b>\n\n"
                f"⚡ <i>Stopping active streams &amp; refreshing process terminal... Please wait a few seconds!</i>"
            )
        )

        try:
            await player_manager.close()
        except Exception as e:
            print(f"[Reload] Error closing calls: {e}")

        import sys
        import os
        print("[System] Owner initiated process reload...")
        os._exit(0)

    @app.on_message(cmd(["shuffle", "cshuffle"]))
    async def shuffle_command(client: Client, message: Message):
        chat_id = message.chat.id
        ok = player_manager.shuffle_queue(chat_id)
        if ok:
            next_t = player_manager.queues[chat_id][0]['title']
            await message.reply_text(
                make_card(
                    f"{ROYAL_HEADER}🔀 <b>UPCOMING QUEUE SHUFFLED!</b>\n\n"
                    f"⏭ <b>Next Track:</b> <code>{next_t}</code>\n"
                    f"📦 Total queued: <code>{len(player_manager.queues[chat_id])} tracks</code>"
                )
            )
        else:
            await message.reply_text(
                make_card(
                    f"{ROYAL_HEADER}⚠️ <b>Queue me minimum 2 songs hone chahiye shuffle karne ke liye!</b>"
                )
            )

    @app.on_message(cmd(["autoplays", "automode", "ap", "autoplay"]))
    async def autoplay_command(client: Client, message: Message):
        chat_id = message.chat.id
        user_name = message.from_user.first_name if message.from_user else "User"
        user_id = message.from_user.id if message.from_user else 0
        user_link = f"<a href=\"tg://user?id={user_id}\">{user_name}</a>" if user_id else f"<b>{user_name}</b>"

        if chat_id in player_manager.autoplay_chats:
            player_manager.autoplay_chats.remove(chat_id)
            await message.reply_text(
                make_card(
                    f"{ROYAL_HEADER}"
                    f"<b>Smart Auto-Play Mode Disabled!</b>\n\n"
                    f"• <b>Status:</b> <code>OFF</code>\n"
                    f"• <b>Toggled By:</b> {user_link}\n\n"
                    f"<i>Playback will stop when queue finishes.</i>"
                )
            )
        else:
            player_manager.autoplay_chats.add(chat_id)
            await message.reply_text(
                make_card(
                    f"{ROYAL_HEADER}"
                    f"<b>Smart Auto-Play Mode Enabled!</b>\n\n"
                    f"• <b>Status:</b> <code>ON</code>\n"
                    f"• <b>Toggled By:</b> {user_link}\n\n"
                    f"<i>YouTube recommendations will automatically play when queue finishes.</i>"
                )
            )

    @app.on_message(cmd(["queue", "cqueue", "recent"]))
    async def queue_command(client: Client, message: Message):
        chat_id = message.chat.id
        if chat_id not in player_manager.active_calls:
            await message.reply_text(make_card(f"{ROYAL_HEADER}⚠️ <b>Abhi kuch bhi play nahi ho raha!</b>"))
            return
            
        current_title = player_manager.stream_title.get(chat_id, "Unknown Title")
        queued_songs = player_manager.queues.get(chat_id, [])
        ap_status = "ON" if chat_id in player_manager.autoplay_chats else "OFF"
        
        text = f"{ROYAL_HEADER}<b>Now Playing:</b>\n• <code>{current_title}</code>\n\n"
        text += f"<b>Auto-Play:</b> <code>{ap_status}</code>\n\n"
        
        if queued_songs:
            q_lines = []
            for i, song in enumerate(queued_songs, start=1):
                t = song['title']
                t_short = (t[:32] + "...") if len(t) > 32 else t
                q_lines.append(f"{i}. {t_short}")
            q_str = "\n".join(q_lines)
            text += f"<b>Upcoming Queue:</b>\n<blockquote expandable>{q_str}</blockquote>"
        else:
            text += "<b>Queue is empty!</b>"
            
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("SHUFFLE QUEUE", callback_data=f"cb_shuffle|{chat_id}", style="success"),
                InlineKeyboardButton(f"AUTOPLAY ({'ON' if chat_id in player_manager.autoplay_chats else 'OFF'})", callback_data=f"cb_autoplay|{chat_id}", style="primary")
            ],
            [InlineKeyboardButton("CLOSE", callback_data="play_close", style="danger")]
        ])
        await message.reply_text(make_card(text), reply_markup=buttons)

    @app.on_message(cmd(["help", "helpmenu"]))
    async def help_command(client: Client, message: Message):
        help_text = (
            f"Click the buttons below to get information about my commands.\n\n"
            f"<i>Note: All commands can be used with /</i>"
        )
        grid_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Admins", callback_data="help_cat|admins", style="primary"),
                InlineKeyboardButton("Auth", callback_data="help_cat|auth", style="primary"),
                InlineKeyboardButton("Blacklist", callback_data="help_cat|blacklist", style="primary")
            ],
            [
                InlineKeyboardButton("Language", callback_data="help_cat|language", style="primary"),
                InlineKeyboardButton("Ping", callback_data="help_cat|ping", style="primary"),
                InlineKeyboardButton("Play", callback_data="help_cat|play", style="primary")
            ],
            [
                InlineKeyboardButton("Queue", callback_data="help_cat|queue", style="primary"),
                InlineKeyboardButton("Stats", callback_data="help_cat|stats", style="primary"),
                InlineKeyboardButton("Sudoers", callback_data="help_cat|sudoers", style="primary")
            ],
            [
                InlineKeyboardButton("Close", callback_data="play_close", style="danger")
            ]
        ])
        await message.reply_text(help_text, reply_markup=grid_buttons)

    @app.on_callback_query(filters.regex(r"^cb_"))
    async def queue_extra_callbacks(client: Client, query: CallbackQuery):
        parts = query.data.split("|")
        action = parts[0]
        chat_id = int(parts[1])

        if action == "cb_shuffle":
            ok = player_manager.shuffle_queue(chat_id)
            if ok:
                await query.answer("🔀 Queue Shuffled successfully!", show_alert=True)
            else:
                await query.answer("⚠️ Minimum 2 queued songs needed to shuffle!", show_alert=True)

        elif action == "cb_autoplay":
            if chat_id in player_manager.autoplay_chats:
                player_manager.autoplay_chats.remove(chat_id)
                await query.answer("🛑 Auto-Play Disabled!", show_alert=True)
            else:
                player_manager.autoplay_chats.add(chat_id)
                await query.answer("🔀 Auto-Play Enabled! YouTube recommendations will auto-play.", show_alert=True)

        current_title = player_manager.stream_title.get(chat_id, "Unknown Title")
        queued_songs = player_manager.queues.get(chat_id, [])
        ap_status = "ENABLED 🟢" if chat_id in player_manager.autoplay_chats else "DISABLED 🔴"
        
        text = f"{ROYAL_HEADER}🎵 <b>Now Playing:</b>\n• <code>{current_title}</code>\n\n"
        text += f"🔀 <b>Auto-Play:</b> <code>{ap_status}</code>\n\n"
        
        if queued_songs:
            q_lines = [f"{i}. {(s['title'][:32] + '...') if len(s['title']) > 32 else s['title']}" for i, s in enumerate(queued_songs, start=1)]
            text += f"📣 <b>Upcoming Queue:</b>\n<blockquote expandable>{'\n'.join(q_lines)}</blockquote>"
        else:
            text += "📣 <b>Queue is empty!</b>"
            
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔀 SHUFFLE QUEUE", callback_data=f"cb_shuffle|{chat_id}", style="success"),
                InlineKeyboardButton(f"🔄 AUTOPLAY ({'ON' if chat_id in player_manager.autoplay_chats else 'OFF'})", callback_data=f"cb_autoplay|{chat_id}", style="primary")
            ],
            [InlineKeyboardButton("🗑 CLOSE", callback_data="play_close", style="danger")]
        ])
        try:
            from bot import edit_styled
            await edit_styled(chat_id=chat_id, text=text, markup=buttons, message_id=query.message.id)
        except Exception:
            pass

    @app.on_callback_query(filters.regex(r"^play_"))
    async def player_callbacks(client: Client, query: CallbackQuery):
        data = query.data.split("|")
        action = data[0]

        def _perm_check(user_id, chat_id, requested_by_id):
            if user_id in (Config.OWNER_ID, requested_by_id) or is_sudo_user(user_id):
                return True
            from core.db import is_user_approved
            if is_user_approved(chat_id, user_id):
                return True
            return False

        if action in ("play_stop", "play_skip", "play_pause", "play_resume", "play_loop", "play_delete"):
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

            user_name = query.from_user.first_name if query.from_user else "User"
            user_link = f"<a href=\"tg://user?id={user_id}\">{user_name}</a>" if user_id > 0 else f"<b>{user_name}</b>"
            from bot import send_styled

            if action == "play_stop":
                await player_manager.stop(chat_id)
                try:
                    await query.message.delete()
                except Exception:
                    pass
                await send_styled(
                    chat_id=chat_id,
                    text=f"⏹ <b>Stream stopped by:</b> {user_link}"
                )
                await query.answer("⏹ Stream Stopped!")
            elif action == "play_skip":
                await query.answer("⏭ Skipping track...")
                skipped = await player_manager.skip(chat_id)
                await send_styled(
                    chat_id=chat_id,
                    text=f"⏭ <b>Track skipped by:</b> {user_link}"
                )
            elif action == "play_pause":
                ok = await player_manager.pause(chat_id)
                if ok:
                    await send_styled(
                        chat_id=chat_id,
                        text=f"⏸ <b>Stream paused by:</b> {user_link}"
                    )
                    await query.answer("⏸ Stream Paused!")
                else:
                    await query.answer("❌ Stream is not active or cannot be paused!", show_alert=True)
            elif action == "play_resume":
                ok = await player_manager.resume(chat_id)
                if ok:
                    await send_styled(
                        chat_id=chat_id,
                        text=f"▶ <b>Stream resumed by:</b> {user_link}"
                    )
                    await query.answer("▶ Stream Resumed!")
                else:
                    await query.answer("❌ Stream is not active or cannot be resumed!", show_alert=True)
            elif action == "play_loop":
                await query.answer("🔁 Loop Toggled!")
                await send_styled(
                    chat_id=chat_id,
                    text=f"🔁 <b>Loop toggled by:</b> {user_link}"
                )
            elif action == "play_delete":
                await query.answer("🗑 Deleting song card...")
                try:
                    await query.message.delete()
                except Exception:
                    pass

        elif action == "play_effects":
            chat_id = int(data[1]) if len(data) > 1 else query.message.chat.id
            requested_by_id = int(data[2]) if len(data) > 2 else 0
            player_manager.in_effects_menu.add(chat_id)
            await query.answer("🎛 Opening Effects Menu...")
            effects_markup = build_effects_markup("normal", chat_id, requested_by_id)
            try:
                from bot import edit_reply_markup_styled
                await edit_reply_markup_styled(chat_id, query.message.id, effects_markup)
            except Exception:
                pass

        elif action == "play_close":
            chat_id = query.message.chat.id if query.message and query.message.chat else 0
            if chat_id:
                player_manager.in_effects_menu.discard(chat_id)
            try:
                await query.message.delete()
            except Exception:
                pass
            try:
                await query.answer()
            except Exception:
                pass

    @app.on_callback_query(filters.regex(r"^fx_"))
    async def effects_callbacks(client: Client, query: CallbackQuery):
        data = query.data.split("|")
        action = data[0]

        if action == "fx_back":
            chat_id = int(data[1]) if len(data) > 1 else query.message.chat.id
            requested_by_id = int(data[2]) if len(data) > 2 else 0
            player_manager.in_effects_menu.discard(chat_id)
            await query.answer("Back to Player")
            local_path = player_manager.active_files.get(chat_id, "")
            mode = "audio" if not (local_path.endswith(".mp4") or local_path.endswith(".mkv")) else "video"
            import time
            start = player_manager.stream_start_time.get(chat_id, time.time())
            total = player_manager.stream_duration.get(chat_id, 0)
            elapsed = int(time.time() - start)
            try:
                from bot import edit_reply_markup_styled
                markup = player_manager._build_play_card_markup(chat_id, requested_by_id, elapsed, total, mode)
                await edit_reply_markup_styled(chat_id, query.message.id, markup)
            except Exception:
                pass

        elif action == "fx_set":
            effect = data[1] if len(data) > 1 else "normal"
            chat_id = int(data[2]) if len(data) > 2 else query.message.chat.id
            requested_by_id = int(data[3]) if len(data) > 3 else 0
            
            # Apply real-time FFmpeg audio filter on PyTgCalls stream!
            await player_manager.set_audio_effect(chat_id, effect)

            await query.answer(f"🎛 Effect: {effect.upper()} Applied!")
            effects_markup = build_effects_markup(effect, chat_id, requested_by_id)
            try:
                from bot import edit_reply_markup_styled
                await edit_reply_markup_styled(chat_id, query.message.id, effects_markup)
            except Exception:
                pass

    @app.on_callback_query(filters.regex(r"^unapprove_user\|"))
    async def unapprove_user_callback(client: Client, query: CallbackQuery):
        user_id = query.from_user.id if query.from_user else 0
        if user_id != Config.OWNER_ID and not is_sudo_user(user_id):
            await query.answer("⚠️ Only Bot Owner / Sudo can revoke approved users!", show_alert=True)
            return

        parts = query.data.split("|")
        chat_id = int(parts[1])
        target_uid = int(parts[2])

        from core.db import remove_approved_user, get_approved_users
        remove_approved_user(chat_id, target_uid)
        await query.answer("❌ Permission Revoked!")

        users = get_approved_users(chat_id)
        if not users:
            try:
                await query.message.edit_text(make_card(f"{ROYAL_HEADER}👥 <b>Iss group me ab koi approved control user nahi hai!</b>"))
            except Exception:
                pass
            return

        lines = []
        buttons_list = []
        for u in users:
            uid = u["user_id"]
            uname = u["user_name"] or f"User {uid}"
            lines.append(f"• <a href=\"tg://user?id={uid}\">{uname}</a> [<code>{uid}</code>]")
            buttons_list.append([InlineKeyboardButton(f"❌ Revoke: {uname}", callback_data=f"unapprove_user|{chat_id}|{uid}")])

        buttons_list.append([InlineKeyboardButton("🗑 Close", callback_data="play_close")])

        users_text = (
            f"👑 <b>ɢᴀṁᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀṁᴇʀ</b> 👑\n\n"
            f"👥 <b>APPROVED CONTROL USERS ({len(users)}):</b>\n\n" +
            "\n".join(lines)
        )
        try:
            await query.message.edit_text(make_card(users_text), reply_markup=InlineKeyboardMarkup(buttons_list))
        except Exception:
            pass

    @app.on_callback_query(filters.regex(r"^pl_do_"))
    async def playlist_resume_callbacks(client: Client, query: CallbackQuery):
        data = query.data.split("|")
        action = data[0]
        pl_id = data[1]
        mode = data[2]
        chat_id = query.message.chat.id

        req_name = query.from_user.first_name if query.from_user else "User"
        req_id = query.from_user.id if query.from_user else 0

        playlist_url = f"https://www.youtube.com/playlist?list={pl_id}" if not pl_id.startswith("http") else pl_id

        if action == "pl_do_start":
            start_idx = int(data[3]) if len(data) > 3 else 0
            await query.answer("▶ Starting Playlist...")
            try:
                await query.message.edit_text(make_card(f"{ROYAL_HEADER}⏳ <b>Starting Playlist... Please wait!</b>"))
            except Exception:
                pass

            asyncio.create_task(player_manager.execute_playlist(
                chat_id=chat_id,
                start_from_index=start_idx,
                mode=mode,
                status_msg=query.message
            ))
        elif action == "pl_do_resume":
            start_idx = int(data[3]) if len(data) > 3 else 0
            await query.answer(f"🟢 Resuming from track #{start_idx + 1}...")
            
            try:
                await query.message.edit_text(make_card(f"{ROYAL_HEADER}⏳ <b>Resuming Playlist from Song #{start_idx + 1}... Please wait!</b>"))
            except Exception:
                pass

            asyncio.create_task(player_manager.execute_playlist(
                chat_id=chat_id,
                start_from_index=start_idx,
                mode=mode,
                status_msg=query.message
            ))
        elif action == "pl_do_restart":
            from core.db import clear_playlist_state
            clear_playlist_state(chat_id, mode)
            await query.answer("🔴 Starting Over from Song #1...")

            try:
                await query.message.edit_text(make_card(f"{ROYAL_HEADER}⏳ <b>Starting Playlist from Song #1... Please wait!</b>"))
            except Exception:
                pass

            asyncio.create_task(player_manager.execute_playlist(
                chat_id=chat_id,
                start_from_index=0,
                mode=mode,
                status_msg=query.message
            ))

    @app.on_callback_query(filters.regex(r"^(welcome_|help_cat\|)"))
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
                f"Click the buttons below to get information about my commands.\n\n"
                f"<i>Note: All commands can be used with /</i>"
            )
            grid_buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Admins", callback_data="help_cat|admins", style="primary"),
                    InlineKeyboardButton("Auth", callback_data="help_cat|auth", style="primary"),
                    InlineKeyboardButton("Blacklist", callback_data="help_cat|blacklist", style="primary")
                ],
                [
                    InlineKeyboardButton("Language", callback_data="help_cat|language", style="primary"),
                    InlineKeyboardButton("Ping", callback_data="help_cat|ping", style="primary"),
                    InlineKeyboardButton("Play", callback_data="help_cat|play", style="primary")
                ],
                [
                    InlineKeyboardButton("Queue", callback_data="help_cat|queue", style="primary"),
                    InlineKeyboardButton("Stats", callback_data="help_cat|stats", style="primary"),
                    InlineKeyboardButton("Sudoers", callback_data="help_cat|sudoers", style="primary")
                ],
                [
                    InlineKeyboardButton("Back", callback_data="welcome_back", style="primary")
                ]
            ])
            await edit_styled(chat_id, help_text, grid_buttons, message_id=message_id, is_video=is_video)
            await query.answer()

        elif data.startswith("help_cat|"):
            cat = data.split("|")[1]
            cat_map = {
                "admins": (
                    "👑 <b>ADMIN COMMANDS:</b>\n\n"
                    "• <code>/pause</code> - Pause playback\n"
                    "• <code>/resume</code> - Resume playback\n"
                    "• <code>/skip</code> - Skip current track\n"
                    "• <code>/stop</code> - Stop playback & leave VC\n"
                    "• <code>/seek 10s</code> / <code>/seek 1m</code> - Seek stream forward\n"
                    "• <code>/reset</code> - Perform full system reset\n"
                    "• <code>/reload</code> - Reload bot process"
                ),
                "auth": (
                    "👥 <b>APPROVED CONTROLS:</b>\n\n"
                    "• <code>/approvecontrol</code> - Grant control permission to reply user\n"
                    "• <code>/unapprovecontrol</code> - Revoke control permission\n"
                    "• <code>/approvedusers</code> - View all approved users in group"
                ),
                "blacklist": (
                    "🛡 <b>BOT SETTINGS:</b>\n\n"
                    "• <code>/welcome on</code> - Enable group welcome card\n"
                    "• <code>/welcome off</code> - Disable group welcome card\n"
                    "• <code>/start on</code> - Enable start intro card\n"
                    "• <code>/start off</code> - Disable start intro card"
                ),
                "language": (
                    "⚙️ <b>STREAM QUALITY & FPS PREFERENCES:</b>\n\n"
                    "• <code>/quality 1080p</code> - Set 1080p video quality\n"
                    "• <code>/quality 720p</code> - Set 720p video quality\n"
                    "• <code>/fps 60</code> - Set 60 FPS framerate\n"
                    "• <code>/fps 30</code> - Set 30 FPS framerate"
                ),
                "ping": (
                    "⚡ <b>SYSTEM & PING:</b>\n\n"
                    "• <code>/ping</code> - Check bot response speed\n"
                    "• <code>/sysstats</code> - View VPS CPU, RAM & Uptime stats"
                ),
                "play": (
                    "🎬 <b>PLAYBACK COMMANDS:</b>\n\n"
                    "• <code>/vd</code> <i>[song/link]</i> - Stream Video (720p 60fps)\n"
                    "• <code>/ad</code> <i>[song/link]</i> - Stream HQ Studio Audio\n"
                    "• <code>/list</code> <i>[playlist link]</i> - Play Video Playlist\n"
                    "• <code>/la</code> <i>[playlist link]</i> - Play Audio Playlist\n"
                    "• <code>/plresume</code> - Resume saved playlist from last song"
                ),
                "queue": (
                    "🔀 <b>QUEUE & AUTOPLAY:</b>\n\n"
                    "• <code>/queue</code> - View upcoming queued tracks\n"
                    "• <code>/shuffle</code> - Shuffle upcoming queued tracks\n"
                    "• <code>/autoplays</code> - Toggle Smart Auto-Play mode (ON/OFF)\n"
                    "• <code>/automode</code> - Toggle Auto-Play mode"
                ),
                "stats": (
                    "📊 <b>GROUP STATS & HISTORY:</b>\n\n"
                    "• <code>/stats</code> - View bot global stats\n"
                    "• <code>/myplaylists</code> - View saved playlists history in group"
                ),
                "sudoers": (
                    "👑 <b>SUDO & OWNER COMMANDS:</b>\n\n"
                    "• <code>/addsudo</code> - Add a new sudo user\n"
                    "• <code>/delsudo</code> - Remove a sudo user\n"
                    "• <code>/sudolist</code> - View all sudo users\n"
                    "• <code>/broadcast</code> - Broadcast message to all groups"
                )
            }
            cat_text = cat_map.get(cat, "<b>Help Category</b>")
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("Back", callback_data="welcome_help", style="primary")
            ]])
            await edit_styled(chat_id, cat_text, markup, message_id=message_id, is_video=is_video)
            await query.answer()

        elif data == "welcome_about":
            about_text = (
                f"Hey <b>{user_name}</b>,\n\n"
                f"This is <b>GameOver YT Streamer</b> !\n\n"
                f"A premium high-performance YouTube video & audio streaming bot.\n\n"
                f"Developed and maintained by <b>GameOver Team</b>."
            )
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Owner", url=Config.get_owner_url(), style="primary"),
                    InlineKeyboardButton("Back", callback_data="welcome_back", style="primary")
                ]
            ])
            await edit_styled(chat_id, about_text, markup, message_id=message_id, is_video=is_video)
            await query.answer()
            
        elif data == "welcome_back":
            welcome_text = (
                f"Hey <b>{user_name}</b>,\n"
                f"This is <b>GameOver YT Streamer</b> !\n\n"
                f"A music player bot with some awesome and useful features.\n\n"
                f"<i>Click on the buttons below to get information about my commands.</i>"
            )
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Add me to your group", url=f"https://t.me/{bot_username}?startgroup=true", style="success")
                ],
                [
                    InlineKeyboardButton("Help", callback_data="welcome_help", style="primary"),
                    InlineKeyboardButton("Owner", url=Config.get_owner_url(), style="primary")
                ],
                [
                    InlineKeyboardButton("About", callback_data="welcome_about", style="danger")
                ]
            ])
            await edit_styled(chat_id, welcome_text, buttons, message_id=message_id, is_video=is_video)
            await query.answer()
