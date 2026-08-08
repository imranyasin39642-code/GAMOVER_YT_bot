"""
👑 GameOver Bot — Admin Panel Plugin
Interactive Admin Dashboard for owner/sudo users.
Supports dynamic Broadcast management with toggles per group, and mass forwarding.
"""

import asyncio
import os
import time
import json
try:
    import psutil
except ImportError:
    psutil = None
import aiohttp
from datetime import datetime
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import Config
from core.db import is_sudo_user, get_broadcast_groups, set_group_broadcast_enabled, get_db, set_group_welcome_enabled, set_group_bot_active, update_group_info
from core.player import player_manager
from bot import make_card

ROYAL_HEADER = "👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ 👑</b>\n\n"

# In-memory dictionary to store admin states (e.g. if they are in broadcast input mode)
admin_states = {}

async def sync_groups_from_telegram(client: Client) -> list:
    """Sync active group dialogs with SQLite DB if DB has 0 groups."""
    groups = get_broadcast_groups()
    if not groups:
        try:
            ast = player_manager._assistant
            if ast:
                async for dialog in ast.get_dialogs():
                    chat = getattr(dialog, "chat", None)
                    if chat and getattr(chat, "type", None) in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
                        update_group_info(chat.id, chat.title or "Group Chat")
                groups = get_broadcast_groups()
        except Exception as e:
            print(f"[Admin] Error syncing dialogs via assistant: {e}")
    return groups

def parse_duration(duration_str: str) -> int:
    """
    Parses a duration string (e.g. '10', '10m', '2h', '1d') and returns duration in seconds.
    Returns 0 for unlimited/invalid.
    """
    if not duration_str:
        return 0
    duration_str = duration_str.strip().lower()
    if duration_str == "0" or duration_str == "unlimited":
        return 0
    import re
    match = re.match(r"^(\d+)([mhd]?)$", duration_str)
    if not match:
        if duration_str.isdigit():
            return int(duration_str) * 60
        return 0
    value, unit = match.groups()
    val = int(value)
    if unit == "m" or not unit:
        return val * 60
    elif unit == "h":
        return val * 3600
    elif unit == "d":
        return val * 86400
    return 0

def format_time_remaining(expires_at: int) -> str:
    if expires_at == 0:
        return "Unlimited ♾️"
    import time
    now = int(time.time())
    diff = int(expires_at) - now
    if diff <= 0:
        return "Expired 🔴"
    days = diff // 86400
    hours = (diff % 86400) // 3600
    minutes = (diff % 3600) // 60
    seconds = diff % 60
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts) + " ⏳"

BASELINE_FILE = os.path.join(Config.DOWNLOADS_DIR, "net_baseline.json")

def get_net_baseline() -> tuple[int, int]:
    if os.path.exists(BASELINE_FILE):
        try:
            with open(BASELINE_FILE, "r") as f:
                data = json.load(f)
                return data.get("sent", 0), data.get("recv", 0)
        except Exception:
            pass
    return 0, 0

def save_net_baseline(sent: int, recv: int):
    try:
        with open(BASELINE_FILE, "w") as f:
            json.dump({"sent": sent, "recv": recv}, f)
    except Exception:
        pass

def get_network_usage() -> tuple[float, float]:
    try:
        if not psutil:
            return 0.0, 0.0
        counters = psutil.net_io_counters()
        base_sent, base_recv = get_net_baseline()
        sent = max(0, counters.bytes_sent - base_sent)
        recv = max(0, counters.bytes_recv - base_recv)
        return sent / (1024 * 1024), recv / (1024 * 1024)
    except Exception:
        return 0.0, 0.0

def reset_network_usage():
    try:
        if not psutil:
            return
        counters = psutil.net_io_counters()
        save_net_baseline(counters.bytes_sent, counters.bytes_recv)
    except Exception:
        pass

async def get_cpu_usage() -> float:
    """Returns accurate CPU % averaged over 1 second (non-blocking via executor thread)."""
    if not psutil:
        return 0.0
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, psutil.cpu_percent, 1)

async def run_network_speed_test() -> tuple[float, float]:
    """
    Accurate speed test: downloads 5 x 10MB chunks in PARALLEL from Cloudflare CDN.
    Returns (speed_mbps, elapsed_seconds).
    """
    url = "https://speed.cloudflare.com/__down?bytes=10485760"  # 10 MB per worker
    NUM_WORKERS = 5
    total_bytes = 0
    start = time.time()

    async def _fetch_one(session: aiohttp.ClientSession) -> int:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return len(data)
        except Exception as e:
            print(f"[Speedtest worker] {e}")
        return 0

    try:
        connector = aiohttp.TCPConnector(limit=NUM_WORKERS)
        async with aiohttp.ClientSession(connector=connector) as session:
            results = await asyncio.gather(*[_fetch_one(session) for _ in range(NUM_WORKERS)])
        total_bytes = sum(results)
        elapsed = time.time() - start
        if elapsed <= 0:
            elapsed = 0.01
        if total_bytes == 0:
            return 0.0, elapsed
        speed_mbps = (total_bytes * 8) / 1_000_000 / elapsed
        return speed_mbps, elapsed
    except Exception as e:
        print(f"[Speedtest] Error: {e}")
    return 0.0, 0.0

async def sync_groups_from_telegram(client: Client) -> list:
    """
    Validates all groups in SQLite DB against Telegram API.
    Auto-purges stale/deleted/kicked group IDs so ONLY real active groups where bot is present remain.
    """
    from core.db import get_broadcast_groups, remove_group_info, update_group_info
    raw_groups = get_broadcast_groups()
    valid_groups = []
    
    for g in raw_groups:
        c_id = g["chat_id"]
        try:
            chat = await client.get_chat(c_id)
            if chat and chat.title:
                if chat.title != g.get("title"):
                    update_group_info(c_id, chat.title)
                    g["title"] = chat.title
                valid_groups.append(g)
        except Exception as e:
            err_s = str(e)
            if any(k in err_s for k in ["CHANNEL_INVALID", "PEER_ID_INVALID", "CHAT_ID_INVALID", "USER_NOT_PARTICIPANT", "CHAT_ADMIN_REQUIRED", "INPUT_USER_DEACTIVATED", "Chat not found"]):
                print(f"[DB/Sync] Purging stale dead group {c_id} ({g.get('title')}): {err_s}")
                remove_group_info(c_id)
            else:
                valid_groups.append(g)
                
    return valid_groups

def get_network_manager_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ RUN SPEED TEST", callback_data="admin_net_speedtest", style="success"),
            InlineKeyboardButton("🧹 RESET COUNTER", callback_data="admin_net_reset", style="danger")
        ],
        [
            InlineKeyboardButton("🔙 BACK", callback_data="admin_back", style="primary"),
            InlineKeyboardButton("❌ CLOSE", callback_data="admin_close", style="danger")
        ]
    ])

def get_quality_menu_markup(current_q: str = None, current_fps: str = None) -> InlineKeyboardMarkup:
    from core.db import get_setting
    q   = current_q or get_setting("quality_pref") or "1080p"
    fps = current_fps or get_setting("fps_pref") or "60"

    q_4k_icon   = "🟢 " if q == "4K" else ""
    q_2k_icon   = "🟢 " if q == "2K" else ""
    q_1080_icon = "🟢 " if q == "1080p" else ""
    q_720_icon  = "🟢 " if q == "720p" else ""
    q_480_icon  = "🟢 " if q == "480p" else ""

    fps_60_icon = "⚡ " if fps == "60" else ""
    fps_90_icon = "⚡ " if fps == "90" else ""
    fps_30_icon = "⚡ " if fps == "30" else ""

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{q_4k_icon}4K (2160p)", callback_data="set_quality|4K", style="primary"),
            InlineKeyboardButton(f"{q_2k_icon}2K (1440p)", callback_data="set_quality|2K", style="primary")
        ],
        [
            InlineKeyboardButton(f"{q_1080_icon}1080p Full HD", callback_data="set_quality|1080p", style="primary"),
            InlineKeyboardButton(f"{q_720_icon}720p HD", callback_data="set_quality|720p", style="primary"),
            InlineKeyboardButton(f"{q_480_icon}480p SD", callback_data="set_quality|480p", style="primary")
        ],
        [
            InlineKeyboardButton(f"{fps_60_icon}60 FPS Mode", callback_data="set_fps|60", style="success"),
            InlineKeyboardButton(f"{fps_90_icon}90 FPS Mode", callback_data="set_fps|90", style="success"),
            InlineKeyboardButton(f"{fps_30_icon}30 FPS Mode", callback_data="set_fps|30", style="secondary")
        ],
        [
            InlineKeyboardButton("🔙 BACK TO DASHBOARD", callback_data="admin_back", style="primary"),
            InlineKeyboardButton("❌ CLOSE", callback_data="admin_close", style="danger")
        ]
    ])

def get_admin_panel_markup() -> InlineKeyboardMarkup:
    from core.player import player_manager
    active_count = len(player_manager.active_calls) if (player_manager and hasattr(player_manager, 'active_calls')) else 0
    live_label = f"🔴 LIVE STREAMS ({active_count})"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(live_label, callback_data="admin_live_streams", style="danger"),
            InlineKeyboardButton("⚡ QUALITY & FPS", callback_data="admin_quality_menu", style="success")
        ],
        [
            InlineKeyboardButton("📡 LOCAL PC API", callback_data="admin_api_menu", style="success"),
            InlineKeyboardButton("📢 BROADCAST", callback_data="admin_bc_prompt", style="success")
        ],
        [
            InlineKeyboardButton("👥 BC GROUPS", callback_data="admin_groups|0", style="primary"),
            InlineKeyboardButton("👋 WELCOME SETTINGS", callback_data="admin_welcome_groups|0", style="primary")
        ],
        [
            InlineKeyboardButton("🤖 BOT STATUS", callback_data="admin_status_groups|0", style="primary"),
            InlineKeyboardButton("📂 FILE MANAGER", callback_data="admin_file_manager|0", style="primary")
        ],
        [
            InlineKeyboardButton("🌐 NETWORK MANAGER", callback_data="admin_network", style="primary"),
            InlineKeyboardButton("📹 MANAGE VIDEOS", callback_data="admin_manage_videos", style="primary")
        ],
        [
            InlineKeyboardButton("👥 APPROVED USERS", callback_data="admin_approved_groups|0", style="success"),
            InlineKeyboardButton("🔄 RELOAD BOT", callback_data="admin_reload_bot", style="danger")
        ],
        [
            InlineKeyboardButton("❌ CLOSE", callback_data="admin_close", style="danger")
        ]
    ])


def get_groups_markup(groups: list, page: int) -> InlineKeyboardMarkup:
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_groups = groups[start:end]

    buttons = []
    for g in page_groups:
        status_icon = "🟢" if g["enabled"] else "🔴"
        status_style = "success" if g["enabled"] else "danger"
        status_text = f"{status_icon} {g['title']}"
        buttons.append([
            InlineKeyboardButton(status_text, callback_data=f"admin_toggle|{g['chat_id']}|{page}", style=status_style)
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ PREV", callback_data=f"admin_groups|{page - 1}", style="success"))
    
    if end < len(groups):
        nav_buttons.append(InlineKeyboardButton("NEXT ▶️", callback_data=f"admin_groups|{page + 1}", style="success"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([
        InlineKeyboardButton("🔙 BACK", callback_data="admin_back", style="primary"),
        InlineKeyboardButton("❌ CLOSE", callback_data="admin_close", style="danger")
    ])
    return InlineKeyboardMarkup(buttons)

def get_welcome_groups_markup(groups: list, page: int) -> InlineKeyboardMarkup:
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_groups = groups[start:end]

    buttons = []
    for g in page_groups:
        welcome_active = g.get("welcome_enabled", 1)
        if welcome_active is None:
            welcome_active = 1
        status_icon = "🟢" if welcome_active else "🔴"
        status_style = "success" if welcome_active else "danger"
        status_text = f"{status_icon} {g['title']}"
        buttons.append([
            InlineKeyboardButton(status_text, callback_data=f"admin_welcome_toggle|{g['chat_id']}|{page}", style=status_style)
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ PREV", callback_data=f"admin_welcome_groups|{page - 1}", style="success"))
    
    if end < len(groups):
        nav_buttons.append(InlineKeyboardButton("NEXT ▶️", callback_data=f"admin_welcome_groups|{page + 1}", style="success"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([
        InlineKeyboardButton("🔙 BACK", callback_data="admin_back", style="primary"),
        InlineKeyboardButton("❌ CLOSE", callback_data="admin_close", style="danger")
    ])
    return InlineKeyboardMarkup(buttons)

def get_status_groups_markup(groups: list, page: int) -> InlineKeyboardMarkup:
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_groups = groups[start:end]

    buttons = []
    for g in page_groups:
        bot_active = g.get("bot_active", 1)
        if bot_active is None:
            bot_active = 1
        status_icon = "🟢" if bot_active else "🔴"
        status_style = "success" if bot_active else "danger"
        status_text = f"{status_icon} {g['title']}"
        buttons.append([
            InlineKeyboardButton(status_text, callback_data=f"admin_status_toggle|{g['chat_id']}|{page}", style=status_style)
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ PREV", callback_data=f"admin_status_groups|{page - 1}", style="success"))
    
    if end < len(groups):
        nav_buttons.append(InlineKeyboardButton("NEXT ▶️", callback_data=f"admin_status_groups|{page + 1}", style="success"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([
        InlineKeyboardButton("🔙 BACK", callback_data="admin_back", style="primary"),
        InlineKeyboardButton("❌ CLOSE", callback_data="admin_close", style="danger")
    ])
    return InlineKeyboardMarkup(buttons)

def list_downloads_files() -> list:
    files = []
    downloads_dir = Config.DOWNLOADS_DIR
    if not os.path.exists(downloads_dir):
        return []
    
    for root, dirs, filenames in os.walk(downloads_dir):
        for f in filenames:
            file_path = os.path.join(root, f)
            if os.path.isfile(file_path):
                try:
                    size_bytes = os.path.getsize(file_path)
                except Exception:
                    size_bytes = 0
                
                rel_path = os.path.relpath(file_path, downloads_dir).replace("\\", "/")
                
                if f.endswith(".mp4") or f.endswith(".mkv"):
                    file_type = "📹 Video"
                elif f.endswith(".mp3") or f.endswith(".m4a") or f.endswith(".ogg"):
                    file_type = "🎵 Audio"
                else:
                    file_type = "📄 Other"
                
                files.append({
                    "path": file_path,
                    "rel_path": rel_path,
                    "filename": f,
                    "size_mb": size_bytes / (1024 * 1024),
                    "size_bytes": size_bytes,
                    "type": file_type,
                    "mtime": os.path.getmtime(file_path) if os.path.exists(file_path) else 0
                })
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return files

def get_protected_files() -> tuple:
    protected = set(player_manager.active_files.values())
    queued_ids = set()
    from core.scrapers import extract_video_id
    for chat_id, songs in list(player_manager.queues.items()):
        for song in songs:
            qid = extract_video_id(song["url"])
            if qid:
                queued_ids.add(qid)
    return protected, queued_ids

def is_file_protected(file_path: str, protected_paths: set, queued_ids: set) -> bool:
    if file_path in protected_paths:
        return True
    filename = os.path.basename(file_path)
    for qid in queued_ids:
        if qid in filename:
            return True
    return False


def get_files_markup(files: list, page: int, file_keys: list) -> InlineKeyboardMarkup:
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_keys = file_keys[start:end]
    
    buttons = []
    for key in page_keys:
        f_key, f_data = key
        text = f"{f_data['type']} | {f_data['filename'][:20]} ({f_data['size_mb']:.1f}MB)"
        buttons.append([
            InlineKeyboardButton(text, callback_data=f"admin_file_info|{f_key}|{page}", style="primary")
        ])
        
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ PREV", callback_data=f"admin_file_manager|{page - 1}", style="success"))
    if end < len(file_keys):
        nav_buttons.append(InlineKeyboardButton("NEXT ▶️", callback_data=f"admin_file_manager|{page + 1}", style="success"))
        
    if nav_buttons:
        buttons.append(nav_buttons)
        
    buttons.append([
        InlineKeyboardButton("🧹 CLEAR ALL CACHE", callback_data="admin_file_clear_confirm", style="danger")
    ])
    buttons.append([
        InlineKeyboardButton("🔙 BACK", callback_data="admin_back", style="primary"),
        InlineKeyboardButton("❌ CLOSE", callback_data="admin_close", style="danger")
    ])
    return InlineKeyboardMarkup(buttons)

def register(app: Client):

    def is_admin_filter(_, __, message: Message) -> bool:
        user_id = message.from_user.id if message.from_user else 0
        return user_id == Config.OWNER_ID or is_sudo_user(user_id)



    @app.on_message(filters.command(["restart", "reboot", "reset"]) & filters.create(is_admin_filter))
    async def restart_command(client: Client, message: Message):
        status_msg = await message.reply_text(
            f"{ROYAL_HEADER}"
            f"🔄 <b>RESTARTING BOT PROCESS...</b>\n\n"
            f"⚡ <i>Stopping active PyTgCalls streams & refreshing process terminal... Please wait a few seconds!</i>",
            parse_mode=enums.ParseMode.HTML
        )
        from core.player import player_manager
        try:
            await player_manager.close()
        except Exception:
            pass
        print(f"[System] Owner/Admin initiated bot restart via command...")
        os._exit(0)

    @app.on_message(filters.command("admin") & filters.private & filters.create(is_admin_filter))
    async def admin_panel(client: Client, message: Message):
        admin_states.pop(message.from_user.id, None)
        cpu_usage = await get_cpu_usage()
        ram_usage = psutil.virtual_memory().percent if psutil else "N/A"
        from bot import send_styled
        await send_styled(
            chat_id=message.chat.id,
            text=(
                f"{ROYAL_HEADER}"
                f"Welcome to the bot control dashboard, Owner.\n\n"
                f"💻 <b>System Status:</b>\n"
                f"• CPU Usage: <code>{cpu_usage}%</code>\n"
                f"• RAM Usage: <code>{ram_usage}%</code>\n\n"
                f"ℹ️ <b>Quick Guide:</b>\n"
                f"• <b>BROADCAST</b>: Send announcement to all groups.\n"
                f"• <b>BC GROUPS</b>: Toggle group broadcast targets.\n"
                f"• <b>WELCOME SETTINGS</b>: Toggle welcome message cards.\n"
                f"• <b>BOT STATUS</b>: Toggle bot playback functionality per group.\n\n"
                f"Select an operation below:"
            ),
            markup=get_admin_panel_markup()
        )

    @app.on_message(filters.command("nst") & filters.create(is_admin_filter))
    async def nst_command(client: Client, message: Message):
        ram = psutil.virtual_memory().percent if psutil else "N/A"
        
        status_msg = await message.reply_text(
            f"{ROYAL_HEADER}"
            f"⚡ <b>Running Network Speed Test...</b>\n"
            f"Downloading 5 × 10MB in parallel from Cloudflare CDN.\n"
            f"This takes ~10–20 seconds for accurate results.\n\n"
            f"🧠 <b>RAM:</b> <code>{ram}%</code> | 💻 CPU: measuring...",
            parse_mode=enums.ParseMode.HTML
        )
        
        speed_mbps, elapsed = await run_network_speed_test()
        cpu_after = await get_cpu_usage()
        
        total_downloaded_mb = (speed_mbps * elapsed) / 8  # Mbps → MB
        
        if speed_mbps > 0:
            await status_msg.edit_text(
                f"{ROYAL_HEADER}"
                f"📊 <b>Network Speed Test Result:</b>\n\n"
                f"🚀 <b>Download Speed:</b> <code>{speed_mbps:.1f} Mbps</code>\n"
                f"💾 <b>Data Downloaded:</b> <code>{total_downloaded_mb:.1f} MB</code> in <code>{elapsed:.1f}s</code>\n"
                f"📡 <b>Workers:</b> <code>5 parallel connections</code>\n\n"
                f"💻 <b>CPU (1s avg):</b> <code>{cpu_after}%</code>\n"
                f"🧠 <b>RAM Usage:</b> <code>{ram}%</code>",
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await status_msg.edit_text(
                f"{ROYAL_HEADER}"
                f"❌ <b>Speed Test Failed!</b>\n"
                f"Could not connect to Cloudflare CDN speed test server.",
                parse_mode=enums.ParseMode.HTML
            )

    @app.on_callback_query(filters.regex(r"^(admin_|set_quality|set_fps)"))
    async def admin_callback(client: Client, query: CallbackQuery):
        user_id = query.from_user.id if query.from_user else 0
        if user_id != Config.OWNER_ID and not is_sudo_user(user_id):
            await query.answer("⚠️ Access Denied!", show_alert=True)
            return

        data = query.data
        chat_id = query.message.chat.id

        if data == "admin_close":
            admin_states.pop(user_id, None)
            await query.answer("Closing...")
            await query.message.delete()
            return

        elif data == "admin_back":
            admin_states.pop(user_id, None)
            await query.answer("Back...")
            cpu_usage = await get_cpu_usage()
            ram_usage = psutil.virtual_memory().percent if psutil else "N/A"
            text = make_card(
                f"{ROYAL_HEADER}"
                f"Welcome to the bot control dashboard, Owner.\n\n"
                f"💻 <b>System Status:</b>\n"
                f"• CPU Usage: <code>{cpu_usage}%</code>\n"
                f"• RAM Usage: <code>{ram_usage}%</code>\n\n"
                f"ℹ️ <b>Quick Guide:</b>\n"
                f"• <b>BROADCAST</b>: Send announcement to all groups.\n"
                f"• <b>BC GROUPS</b>: Toggle group broadcast targets.\n"
                f"• <b>WELCOME SETTINGS</b>: Toggle welcome message cards.\n"
                f"• <b>BOT STATUS</b>: Toggle bot playback functionality per group.\n\n"
                f"Select an operation below:"
            )
            markup = get_admin_panel_markup()
            try:
                await query.message.edit_text(text, reply_markup=markup)
            except Exception:
                pass

        elif data == "admin_api_menu":
            await query.answer("Opening Local PC API Manager...")
            from core.db import get_setting
            curr_url = get_setting("local_api_url") or Config.LOCAL_API_URL or "Not Set"
            text = make_card(
                f"{ROYAL_HEADER}"
                f"📡 <b>LOCAL PC API MANAGER</b> 📡\n\n"
                f"• <b>Current Live URL:</b>\n<code>{curr_url}</code>\n\n"
                f"• <b>Architecture:</b> <code>Hybrid Local Extraction Engine</code>\n"
                f"• <b>Local PC Bandwidth Load:</b> <code>0% (Metadata JSON Only)</code>\n"
                f"• <b>Port:</b> <code>8000 (FastAPI + Cloudflare Tunnel)</code>\n\n"
                f"💡 <b>To update URL via command, send:</b>\n"
                f"<code>/setapi https://your-new-tunnel.trycloudflare.com</code>"
            )
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔙 BACK TO DASHBOARD", callback_data="admin_back", style="primary"),
                    InlineKeyboardButton("❌ CLOSE", callback_data="admin_close", style="danger")
                ]
            ])
            try:
                await query.message.edit_text(text, reply_markup=markup)
            except Exception:
                pass

        elif data == "admin_quality_menu":
            await query.answer("Opening Quality & FPS Settings...")
            from core.db import get_setting
            q = get_setting("quality_pref") or "720p"
            fps = get_setting("fps_pref") or "60"
            text = make_card(
                f"{ROYAL_HEADER}"
                f"⚡ <b>VIDEO QUALITY & FPS MANAGER</b> ⚡\n\n"
                f"Current Active Stream Target:\n"
                f"• <b>Target Quality:</b> <code>{q}</code>\n"
                f"• <b>Framerate Mode:</b> <code>{fps} FPS</code>\n\n"
                f"<i>Select your preferred resolution or framerate below. All Telegram video streams will extract using these quality settings!</i>"
            )
            markup = get_quality_menu_markup()
            try:
                await query.message.edit_text(text, reply_markup=markup)
            except Exception:
                pass

        elif data.startswith("set_quality|"):
            new_q = data.split("|")[1]
            from core.db import set_setting, get_setting
            set_setting("quality_pref", new_q)
            print(f"[Admin] Quality updated to '{new_q}' in database by user {user_id}")
            await query.answer(f"✅ Quality set to {new_q}!")
            fps = get_setting("fps_pref") or "60"
            text = make_card(
                f"{ROYAL_HEADER}"
                f"⚡ <b>VIDEO QUALITY & FPS MANAGER</b> ⚡\n\n"
                f"✅ <b>Updated Target Resolution to {new_q}!</b>\n\n"
                f"Current Active Stream Target:\n"
                f"• <b>Target Quality:</b> <code>{new_q}</code>\n"
                f"• <b>Framerate Mode:</b> <code>{fps} FPS</code>\n\n"
                f"<i>Select your preferred resolution or framerate below:</i>"
            )
            markup = get_quality_menu_markup(current_q=new_q, current_fps=fps)
            try:
                await query.message.edit_text(text, reply_markup=markup)
            except Exception as e:
                print(f"[Admin] set_quality edit note: {e}")

        elif data.startswith("set_fps|"):
            new_fps = data.split("|")[1]
            from core.db import set_setting, get_setting
            set_setting("fps_pref", new_fps)
            print(f"[Admin] FPS Mode updated to '{new_fps} FPS' in database by user {user_id}")
            await query.answer(f"⚡ FPS Mode set to {new_fps} FPS!")
            q = get_setting("quality_pref") or "720p"
            text = make_card(
                f"{ROYAL_HEADER}"
                f"⚡ <b>VIDEO QUALITY & FPS MANAGER</b> ⚡\n\n"
                f"⚡ <b>Updated Framerate Mode to {new_fps} FPS!</b>\n\n"
                f"Current Active Stream Target:\n"
                f"• <b>Target Quality:</b> <code>{q}</code>\n"
                f"• <b>Framerate Mode:</b> <code>{new_fps} FPS</code>\n\n"
                f"<i>Select your preferred resolution or framerate below:</i>"
            )
            markup = get_quality_menu_markup(current_q=q, current_fps=new_fps)
            try:
                await query.message.edit_text(text, reply_markup=markup)
            except Exception as e:
                print(f"[Admin] set_fps edit note: {e}")



        elif data == "admin_live_streams":
            await query.answer("Loading Active Live Streams...")
            from core.player import player_manager
            active_chats = list(player_manager.active_calls) if player_manager else []
            
            if not active_chats:
                text_content = (
                    f"{ROYAL_HEADER}"
                    f"🔴 <b>ACTIVE LIVE STREAMS (0)</b>\n\n"
                    f"⚠️ <i>Currently, there are NO active music or video streams running in any group.</i>"
                )
                buttons = [[InlineKeyboardButton("🔙 BACK", callback_data="admin_back", style="primary")]]
            else:
                lines = []
                buttons = []
                for idx, c_id in enumerate(active_chats, start=1):
                    group_title = f"Group {c_id}"
                    try:
                        chat_obj = await client.get_chat(c_id)
                        if chat_obj and chat_obj.title:
                            group_title = chat_obj.title
                    except Exception:
                        pass
                    
                    song_title = player_manager.stream_title.get(c_id, "Unknown Track")
                    start_time = player_manager.stream_start_time.get(c_id, time.time())
                    elapsed = max(0, int(time.time() - start_time))
                    tot_dur = player_manager.stream_duration.get(c_id, 0)
                    
                    elapsed_str = player_manager._fmt_time(elapsed)
                    tot_str = player_manager._fmt_time(tot_dur) if tot_dur else "Live"
                    
                    local_p = player_manager.active_files.get(c_id, "")
                    mode_str = "🎥 Video (720p 60fps)" if (local_p.endswith(".mp4") or local_p.endswith(".mkv")) else "🎧 Audio (Studio HQ)"
                    
                    lines.append(
                        f"<b>{idx}. {group_title}</b> [<code>{c_id}</code>]\n"
                        f"   📌 <b>Song:</b> <code>{song_title[:35]}</code>\n"
                        f"   {mode_str}\n"
                        f"   ⏱ <b>Progress:</b> <code>{elapsed_str} / {tot_str}</code>\n"
                    )
                    buttons.append([InlineKeyboardButton(f"⏹ Force Stop: {group_title[:20]}", callback_data=f"admin_stop_stream|{c_id}")])
                
                text_content = (
                    f"{ROYAL_HEADER}"
                    f"🔴 <b>ACTIVE LIVE STREAMS ({len(active_chats)}):</b>\n\n" +
                    "\n".join(lines) +
                    f"\n💡 <i>Tap any button below to force stop playback in that specific group.</i>"
                )
                buttons.append([InlineKeyboardButton("🔄 REFRESH LIST", callback_data="admin_live_streams", style="success")])
                buttons.append([InlineKeyboardButton("🔙 BACK", callback_data="admin_back", style="primary")])

            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=text_content,
                markup=InlineKeyboardMarkup(buttons),
                message_id=query.message.id
            )

        elif data.startswith("admin_stop_stream|"):
            target_chat_id = int(data.split("|")[1])
            await query.answer(f"Force stopping stream in {target_chat_id}...")
            from core.player import player_manager
            await player_manager.stop(target_chat_id)
            
            active_chats = list(player_manager.active_calls) if player_manager else []
            if not active_chats:
                text_content = (
                    f"{ROYAL_HEADER}"
                    f"🔴 <b>ACTIVE LIVE STREAMS (0)</b>\n\n"
                    f"✅ <i>Stream stopped! Currently no active streams running in any group.</i>"
                )
                buttons = [[InlineKeyboardButton("🔙 BACK", callback_data="admin_back", style="primary")]]
            else:
                lines = []
                buttons = []
                for idx, c_id in enumerate(active_chats, start=1):
                    g_title = f"Group {c_id}"
                    try:
                        chat_obj = await client.get_chat(c_id)
                        if chat_obj and chat_obj.title:
                            g_title = chat_obj.title
                    except Exception:
                        pass
                    
                    s_title = player_manager.stream_title.get(c_id, "Unknown Track")
                    st_time = player_manager.stream_start_time.get(c_id, time.time())
                    el = max(0, int(time.time() - st_time))
                    tot_d = player_manager.stream_duration.get(c_id, 0)
                    
                    lines.append(
                        f"<b>{idx}. {g_title}</b> [<code>{c_id}</code>]\n"
                        f"   📌 <b>Song:</b> <code>{s_title[:35]}</code>\n"
                        f"   ⏱ <b>Progress:</b> <code>{player_manager._fmt_time(el)} / {player_manager._fmt_time(tot_d) if tot_d else 'Live'}</code>\n"
                    )
                    buttons.append([InlineKeyboardButton(f"⏹ Force Stop: {g_title[:20]}", callback_data=f"admin_stop_stream|{c_id}")])
                
                text_content = (
                    f"{ROYAL_HEADER}"
                    f"🔴 <b>ACTIVE LIVE STREAMS ({len(active_chats)}):</b>\n\n" +
                    "\n".join(lines)
                )
                buttons.append([InlineKeyboardButton("🔄 REFRESH LIST", callback_data="admin_live_streams", style="success")])
                buttons.append([InlineKeyboardButton("🔙 BACK", callback_data="admin_back", style="primary")])

            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=text_content,
                markup=InlineKeyboardMarkup(buttons),
                message_id=query.message.id
            )

        elif data.startswith("admin_approved_groups"):
            await query.answer("Loading Approved Control Users...")
            from core.db import get_approved_users
            ausers = get_approved_users()
            
            lines = []
            buttons_list = []
            for i, u in enumerate(ausers, start=1):
                gid = u["chat_id"]
                uid = u["user_id"]
                uname = u["user_name"] or f"User {uid}"
                by_id = u.get("approved_by", 0)
                t_str = datetime.fromtimestamp(u.get("added_at", time.time())).strftime("%d %b %Y, %I:%M %p")
                lines.append(
                    f"<b>{i}.</b> <a href=\"tg://user?id={uid}\">{uname}</a> [<code>{uid}</code>] (Group: <code>{gid}</code>)\n"
                    f"   📅 <i>Approved On: {t_str}</i>\n"
                    f"   👑 <i>Approved By: <code>{by_id}</code></i>\n"
                )
                buttons_list.append([InlineKeyboardButton(f"❌ Revoke ({gid}): {uname[:14]}", callback_data=f"unapprove_user|{gid}|{uid}")])

            if not lines:
                text_content = (
                    f"{ROYAL_HEADER}👥 <b>No Approved Control Users!</b>\n\n"
                    f"Aap kisi group me user ke message par reply karke <code>/approvecontrol</code> (ya <code>/aprovedcontroll</code>) chalayein."
                )
            else:
                text_content = (
                    f"{ROYAL_HEADER}👥 <b>ALL APPROVED CONTROL USERS ({len(lines)}):</b>\n\n" +
                    "\n".join(lines)
                )

            buttons_list.append([InlineKeyboardButton("🔙 BACK", callback_data="admin_back", style="primary")])
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=text_content,
                markup=InlineKeyboardMarkup(buttons_list),
                message_id=query.message.id
            )

        elif data == "admin_reload_bot":
            await query.answer("🔄 Reloading Bot Process...")
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"🔄 <b>RELOADING BOT PROCESS...</b>\n\n"
                    f"⚡ <i>Stopping active streams &amp; refreshing process terminal... Please wait a few seconds!</i>"
                ),
                message_id=query.message.id
            )
            from core.player import player_manager
            try:
                await player_manager.close()
            except Exception:
                pass
            import sys
            print("[System] Admin initiated process reload...")
            os._exit(0)

        elif data == "admin_cookies_delete":
            await query.answer("🟢 100% Zero-Cookie Architecture Active! No cookies needed on VPS.", show_alert=True)

        elif data == "admin_network":
            await query.answer("Loading Network Manager...")
            sent_mb, recv_mb = get_network_usage()
            cpu_usage = await get_cpu_usage()
            ram_usage = psutil.virtual_memory().percent if psutil else "N/A"
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"🌐 <b>Network Manager & Stats</b>\n\n"
                    f"📊 <b>Network Usage (Session):</b>\n"
                    f"• Sent: <code>{sent_mb:.2f} MB</code>\n"
                    f"• Received: <code>{recv_mb:.2f} MB</code>\n"
                    f"• Total Combined: <code>{(sent_mb + recv_mb):.2f} MB</code>\n\n"
                    f"💻 <b>System Status:</b>\n"
                    f"• CPU Usage: <code>{cpu_usage}%</code>\n"
                    f"• RAM Usage: <code>{ram_usage}%</code>\n\n"
                    f"<i>Select an option below:</i>"
                ),
                markup=get_network_manager_markup(),
                message_id=query.message.id
            )

        elif data == "admin_net_speedtest":
            await query.answer("Running network speed test...")
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"⚡ <b>Running Speed Test...</b>\n\n"
                    f"Please wait, testing connection with Cloudflare CDN servers..."
                ),
                markup=None,
                message_id=query.message.id
            )
            speed_mbps, elapsed = await run_network_speed_test()
            sent_mb, recv_mb = get_network_usage()
            cpu_usage = await get_cpu_usage()
            ram_usage = psutil.virtual_memory().percent if psutil else "N/A"
            total_downloaded_mb = (speed_mbps * elapsed) / 8
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"🌐 <b>Network Manager & Stats</b>\n\n"
                    f"🚀 <b>Last Speed Test:</b> <code>{speed_mbps:.1f} Mbps</code>\n"
                    f"💾 <b>Downloaded:</b> <code>{total_downloaded_mb:.1f} MB</code> in <code>{elapsed:.1f}s</code>\n"
                    f"📡 <b>Workers:</b> <code>5 parallel connections</code>\n\n"
                    f"📊 <b>Network Usage (Session):</b>\n"
                    f"• Sent: <code>{sent_mb:.2f} MB</code>\n"
                    f"• Received: <code>{recv_mb:.2f} MB</code>\n"
                    f"• Total Combined: <code>{(sent_mb + recv_mb):.2f} MB</code>\n\n"
                    f"💻 <b>CPU (1s avg):</b> <code>{cpu_usage}%</code>\n"
                    f"🧠 <b>RAM Usage:</b> <code>{ram_usage}%</code>"
                ),
                markup=get_network_manager_markup(),
                message_id=query.message.id
            )

        elif data == "admin_net_reset":
            reset_network_usage()
            await query.answer("Network counters reset successfully!", show_alert=True)
            sent_mb, recv_mb = get_network_usage()
            cpu_usage = await get_cpu_usage()
            ram_usage = psutil.virtual_memory().percent if psutil else "N/A"
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"🌐 <b>Network Manager & Stats</b>\n\n"
                    f"🟢 <i>Network usage counters reset successfully!</i>\n\n"
                    f"📊 <b>Network Usage (Session):</b>\n"
                    f"• Sent: <code>{sent_mb:.2f} MB</code>\n"
                    f"• Received: <code>{recv_mb:.2f} MB</code>\n"
                    f"• Total Combined: <code>{(sent_mb + recv_mb):.2f} MB</code>\n\n"
                    f"💻 <b>System Status:</b>\n"
                    f"• CPU Usage: <code>{cpu_usage}%</code>\n"
                    f"• RAM Usage: <code>{ram_usage}%</code>"
                ),
                markup=get_network_manager_markup(),
                message_id=query.message.id
            )

        elif data.startswith("admin_groups|"):
            page = int(data.split("|")[1])
            groups = await sync_groups_from_telegram(client)
            
            if not groups:
                await query.answer("⚠️ No groups registered in database yet!", show_alert=True)
                return

            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"👥 <b>Broadcast Target Chats (Page {page+1})</b>\n\n"
                    f"🟢 = Receives broadcasts | 🔴 = Skipped"
                ),
                markup=get_groups_markup(groups, page),
                message_id=query.message.id
            )

        elif data.startswith("admin_toggle|"):
            parts = data.split("|")
            target_chat_id = int(parts[1])
            page = int(parts[2])

            groups = get_broadcast_groups()
            group = next((g for g in groups if g["chat_id"] == target_chat_id), None)
            if group:
                new_state = not group["enabled"]
                set_group_broadcast_enabled(target_chat_id, new_state)
                await query.answer(f"Updated: {'Enabled' if new_state else 'Disabled'}")
                
                groups = get_broadcast_groups()
                from bot import send_styled
                await send_styled(
                    chat_id=chat_id,
                    text=(
                        f"{ROYAL_HEADER}"
                        f"👥 <b>Broadcast Target Chats (Page {page+1})</b>\n\n"
                        f"🟢 = Receives broadcasts | 🔴 = Skipped"
                    ),
                    markup=get_groups_markup(groups, page),
                    message_id=query.message.id
                )

        elif data.startswith("admin_welcome_groups|"):
            page = int(data.split("|")[1])
            groups = await sync_groups_from_telegram(client)
            
            if not groups:
                await query.answer("⚠️ No groups registered in database yet!", show_alert=True)
                return

            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"👋 <b>Welcome Messages List (Page {page+1})</b>\n\n"
                    f"🟢 = Cards enabled | 🔴 = Cards disabled"
                ),
                markup=get_welcome_groups_markup(groups, page),
                message_id=query.message.id
            )

        elif data.startswith("admin_welcome_toggle|"):
            parts = data.split("|")
            target_chat_id = int(parts[1])
            page = int(parts[2])

            groups = get_broadcast_groups()
            group = next((g for g in groups if g["chat_id"] == target_chat_id), None)
            if group:
                current_state = group.get("welcome_enabled", 1)
                if current_state is None:
                    current_state = 1
                new_state = not current_state
                set_group_welcome_enabled(target_chat_id, new_state)
                await query.answer(f"Welcome: {'Enabled' if new_state else 'Disabled'}")
                
                groups = get_broadcast_groups()
                from bot import send_styled
                await send_styled(
                    chat_id=chat_id,
                    text=(
                        f"{ROYAL_HEADER}"
                        f"👋 <b>Welcome Messages List (Page {page+1})</b>\n\n"
                        f"🟢 = Cards enabled | 🔴 = Cards disabled"
                    ),
                    markup=get_welcome_groups_markup(groups, page),
                    message_id=query.message.id
                )

        elif data.startswith("admin_status_groups|"):
            page = int(data.split("|")[1])
            groups = await sync_groups_from_telegram(client)
            
            if not groups:
                await query.answer("⚠️ No groups registered in database yet!", show_alert=True)
                return

            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"🤖 <b>Bot Active Status List (Page {page+1})</b>\n\n"
                    f"🟢 = Bot active | 🔴 = Bot disabled"
                ),
                markup=get_status_groups_markup(groups, page),
                message_id=query.message.id
            )

        elif data.startswith("admin_status_toggle|"):
            parts = data.split("|")
            target_chat_id = int(parts[1])
            page = int(parts[2])

            groups = get_broadcast_groups()
            group = next((g for g in groups if g["chat_id"] == target_chat_id), None)
            if group:
                current_state = group.get("bot_active", 1)
                if current_state is None:
                    current_state = 1
                new_state = not current_state
                set_group_bot_active(target_chat_id, new_state)
                await query.answer(f"Bot Active: {'Enabled' if new_state else 'Disabled'}")
                
                groups = get_broadcast_groups()
                from bot import send_styled
                await send_styled(
                    chat_id=chat_id,
                    text=(
                        f"{ROYAL_HEADER}"
                        f"🤖 <b>Bot Active Status List (Page {page+1})</b>\n\n"
                        f"🟢 = Bot active | 🔴 = Bot disabled"
                    ),
                    markup=get_status_groups_markup(groups, page),
                    message_id=query.message.id
                )

        elif data == "admin_bc_prompt":
            admin_states[user_id] = "waiting_broadcast"
            await query.answer("Ready for broadcast")
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"📢 <b>Broadcast Mode Active</b>\n\n"
                    f"Ab jo bhi message aap is chat mein send karenge (chahe text, photo, video, ya document ho), wo automatically sabhi active groups mein send ho jayega.\n\n"
                    f"Or reply to any message here with <code>/broadcast</code>."
                ),
                markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin_back", style="primary")]]),
                message_id=query.message.id
            )

        elif data == "admin_manage_videos":
            admin_states.pop(user_id, None)
            from bot import send_styled
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("👋 WELCOME VIDEO", callback_data="admin_set_video|welcome", style="primary"),
                    InlineKeyboardButton("🚀 START VIDEO", callback_data="admin_set_video|start", style="primary")
                ],
                [
                    InlineKeyboardButton("🔙 BACK", callback_data="admin_back", style="success")
                ]
            ])
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"📹 <b>Welcome & Start Video Settings</b>\n\n"
                    f"Aap bot ka Welcome video aur Start video direct Telegram se change kar sakte hain. Niche option choose karein:"
                ),
                markup=markup,
                message_id=query.message.id
            )

        elif data.startswith("admin_set_video|"):
            target = data.split("|")[1] # welcome or start
            admin_states[user_id] = f"waiting_video_{target}"
            await query.answer(f"Awaiting video for {target}")
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"📹 <b>Upload Video for {target.upper()}</b>\n\n"
                    f"Ab is chat mein new video file send ya forward karein.\n\n"
                    f"<i>Bot use automatically save aur cache kar lega.</i>"
                ),
                markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin_manage_videos", style="primary")]]),
                message_id=query.message.id
            )


        elif data.startswith("admin_file_manager|"):
            page = int(data.split("|")[1])
            
            files = list_downloads_files()
            
            if user_id not in admin_states or not isinstance(admin_states[user_id], dict):
                admin_states[user_id] = {}
            admin_states[user_id]["files"] = {}
            
            file_keys = []
            for idx, f in enumerate(files):
                key = str(idx)
                admin_states[user_id]["files"][key] = f["path"]
                file_keys.append((key, f))
                
            total_files = len(files)
            total_size_mb = sum(f["size_mb"] for f in files)
            
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"📂 <b>GAMEOVER File Cache Manager</b>\n\n"
                    f"• <b>Total Files:</b> <code>{total_files}</code>\n"
                    f"• <b>Total Cache:</b> <code>{total_size_mb:.2f} MB</code>\n\n"
                    f"Select any file below to see its details, download it directly to this chat, or delete it from the VPS disk:"
                ),
                markup=get_files_markup(files, page, file_keys),
                message_id=query.message.id
            )

        elif data.startswith("admin_file_info|"):
            parts = data.split("|")
            file_key = parts[1]
            page = int(parts[2])
            
            if user_id not in admin_states or "files" not in admin_states[user_id]:
                files = list_downloads_files()
                if user_id not in admin_states:
                    admin_states[user_id] = {}
                admin_states[user_id]["files"] = {str(idx): f["path"] for idx, f in enumerate(files)}

            file_path = admin_states.get(user_id, {}).get("files", {}).get(file_key)
            if not file_path or not os.path.exists(file_path):
                await query.answer("⚠️ File no longer exists on disk!", show_alert=True)
                return
            
            filename = os.path.basename(file_path)
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            mtime = os.path.getmtime(file_path)
            mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            
            protected_paths, queued_ids = get_protected_files()
            protected = is_file_protected(file_path, protected_paths, queued_ids)
            
            status_text = (
                f"{ROYAL_HEADER}"
                f"📂 <b>File Details</b>\n\n"
                f"• <b>Name:</b> <code>{filename}</code>\n"
                f"• <b>Size:</b> <code>{size_mb:.2f} MB</code>\n"
                f"• <b>Modified:</b> <code>{mtime_str}</code>\n"
                f"• <b>Path:</b> <code>{file_path}</code>\n"
                f"• <b>Protected:</b> <code>{'Yes (Playing/Queued)' if protected else 'No (Safe to Delete)'}</code>"
            )
            
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🗑 DELETE FILE", callback_data=f"admin_file_del|{file_key}|{page}", style="danger"),
                    InlineKeyboardButton("📤 UPLOAD TO CHAT", callback_data=f"admin_file_send|{file_key}|{page}", style="success")
                ],
                [
                    InlineKeyboardButton("🔙 BACK TO MANAGER", callback_data=f"admin_file_manager|{page}", style="primary")
                ]
            ])
            
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=status_text,
                markup=markup,
                message_id=query.message.id
            )

        elif data.startswith("admin_file_del|"):
            parts = data.split("|")
            file_key = parts[1]
            page = int(parts[2])
            
            if user_id not in admin_states or "files" not in admin_states[user_id]:
                files = list_downloads_files()
                if user_id not in admin_states:
                    admin_states[user_id] = {}
                admin_states[user_id]["files"] = {str(idx): f["path"] for idx, f in enumerate(files)}

            file_path = admin_states.get(user_id, {}).get("files", {}).get(file_key)
            if not file_path or not os.path.exists(file_path):
                await query.answer("⚠️ File no longer exists on disk!", show_alert=True)
                return
            
            protected_paths, queued_ids = get_protected_files()
            if is_file_protected(file_path, protected_paths, queued_ids):
                await query.answer("⚠️ This file is currently active or queued! Cannot delete.", show_alert=True)
                return
                
            try:
                os.remove(file_path)
                await query.answer("🗑 File deleted from disk successfully!")
            except Exception as e:
                await query.answer(f"❌ Error: {e}", show_alert=True)
                
            files = list_downloads_files()
            file_keys = []
            if user_id not in admin_states:
                admin_states[user_id] = {}
            admin_states[user_id]["files"] = {}
            for idx, f in enumerate(files):
                key = str(idx)
                admin_states[user_id]["files"][key] = f["path"]
                file_keys.append((key, f))
                
            total_files = len(files)
            total_size_mb = sum(f["size_mb"] for f in files)
            
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"📂 <b>GAMEOVER File Cache Manager</b>\n\n"
                    f"• <b>Total Files:</b> <code>{total_files}</code>\n"
                    f"• <b>Total Cache:</b> <code>{total_size_mb:.2f} MB</code>\n\n"
                    f"Select any file below to see its details, download it directly to this chat, or delete it from the VPS disk:"
                ),
                markup=get_files_markup(files, page, file_keys),
                message_id=query.message.id
            )

        elif data.startswith("admin_file_send|"):
            parts = data.split("|")
            file_key = parts[1]
            page = int(parts[2])
            
            if user_id not in admin_states or "files" not in admin_states[user_id]:
                files = list_downloads_files()
                if user_id not in admin_states:
                    admin_states[user_id] = {}
                admin_states[user_id]["files"] = {str(idx): f["path"] for idx, f in enumerate(files)}

            file_path = admin_states.get(user_id, {}).get("files", {}).get(file_key)
            if not file_path or not os.path.exists(file_path):
                await query.answer("⚠️ File no longer exists on disk!", show_alert=True)
                return
            
            await query.answer("📤 Sending file as document... Please check chat.")
            
            async def _send_doc():
                try:
                    await client.send_document(
                        chat_id=chat_id,
                        document=file_path,
                        caption=f"📄 <b>File:</b> <code>{os.path.basename(file_path)}</code>\n🔑 Key: {file_key}"
                    )
                except Exception as e:
                    print(f"[Admin File Manager] Error sending document: {e}")
                    try:
                        await client.send_message(chat_id, f"❌ Failed to send document: {e}")
                    except:
                        pass
                        
            asyncio.create_task(_send_doc())

        elif data == "admin_file_clear_confirm":
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔥 YES, PURGE ENTIRE CACHE", callback_data="admin_file_clear_all", style="danger")
                ],
                [
                    InlineKeyboardButton("❌ CANCEL", callback_data="admin_file_manager|0", style="success")
                ]
            ])
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"⚠️ <b>WARNING: Purge Entire Cache</b>\n\n"
                    f"Are you sure you want to delete all cached audio, video, and studio files in downloads?\n\n"
                    f"• Active streams will be protected.\n"
                    f"• Queued tracks will be protected.\n"
                    f"• All other downloaded files will be permanently deleted."
                ),
                markup=markup,
                message_id=query.message.id
            )

        elif data == "admin_file_clear_all":
            files = list_downloads_files()
            protected_paths, queued_ids = get_protected_files()
            
            purged = 0
            errors = 0
            for f in files:
                path = f["path"]
                if is_file_protected(path, protected_paths, queued_ids):
                    continue
                try:
                    os.remove(path)
                    purged += 1
                except Exception as e:
                    print(f"[Admin] Error clearing cache file {path}: {e}")
                    errors += 1
                
            await query.answer(f"🧹 Purged {purged} files from disk! ({errors} errors)", show_alert=True)
            
            files = list_downloads_files()
            file_keys = []
            if user_id not in admin_states:
                admin_states[user_id] = {}
            admin_states[user_id]["files"] = {}
            for idx, f in enumerate(files):
                key = str(idx)
                admin_states[user_id]["files"][key] = f["path"]
                file_keys.append((key, f))
                
            total_files = len(files)
            total_size_mb = sum(f["size_mb"] for f in files)
            
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"📂 <b>GAMEOVER File Cache Manager</b>\n\n"
                    f"• <b>Total Files:</b> <code>{total_files}</code>\n"
                    f"• <b>Total Cache:</b> <code>{total_size_mb:.2f} MB</code>\n\n"
                    f"Select any file below to see its details, download it directly to this chat, or delete it from the VPS disk:"
                ),
                markup=get_files_markup(files, 0, file_keys),
                message_id=query.message.id
            )


    # Message listener for broadcast targets
    @app.on_message(filters.private & filters.create(is_admin_filter))
    async def broadcast_listener(client: Client, message: Message):
        if message.text and message.text.startswith("/") and not any(
            message.text.startswith(cmd) for cmd in ("/broadcast", "/bc")
        ):
            message.continue_propagation()
            return

        user_id = message.from_user.id if message.from_user else 0
        state = admin_states.get(user_id)

        if state and state.startswith("waiting_video_"):
            target = state.split("_")[-1] # welcome or start
            if not message.video:
                await message.reply_text(
                    f"{ROYAL_HEADER}"
                    f"❌ <b>Error: Please send/forward a valid Video file!</b>",
                    parse_mode=enums.ParseMode.HTML
                )
                return
            
            admin_states.pop(user_id, None)
            from core.db import set_setting
            cache_prefix = "welcome_video" if target == "welcome" else "start_video"
            set_setting(f"{cache_prefix}_file_id", message.video.file_id)
            set_setting(f"{cache_prefix}_custom", "true")
            
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"✅ <b>{target.upper()} Video updated successfully!</b>\n\n"
                f"Bot ab custom file_id (<code>{message.video.file_id}</code>) use karega.",
                parse_mode=enums.ParseMode.HTML
            )
            return

        is_bc_command = message.text and (message.text.startswith("/broadcast") or message.text.startswith("/bc"))
        
        if state == "waiting_broadcast" or is_bc_command:
            admin_states.pop(user_id, None)

            target_msg = message.reply_to_message if message.reply_to_message else message
            if is_bc_command and not message.reply_to_message:
                await message.reply_text(
                    f"{ROYAL_HEADER}"
                    f"❌ <b>Error: Reply to a message with `/broadcast` to send it!</b>",
                    parse_mode=enums.ParseMode.HTML
                )
                return

            groups = get_broadcast_groups()
            enabled_groups = [g for g in groups if g["enabled"]]

            if not enabled_groups:
                await message.reply_text(
                    f"{ROYAL_HEADER}"
                    f"❌ <b>Error: No groups are active/enabled in the broadcast settings!</b>",
                    parse_mode=enums.ParseMode.HTML
                )
                return

            status_msg = await message.reply_text(
                f"{ROYAL_HEADER}"
                f"📢 <b>Sending broadcast to {len(enabled_groups)} groups...</b>\n"
                f"⏳ <i>Please wait...</i>",
                parse_mode=enums.ParseMode.HTML
            )

            success = 0
            failed = 0

            for group in enabled_groups:
                try:
                    await target_msg.copy(chat_id=group["chat_id"])
                    success += 1
                except Exception as copy_err:
                    err_str = str(copy_err)
                    print(f"[Admin] Broadcast failed for group {group['chat_id']}: {copy_err}")
                    if any(k in err_str for k in ["CHANNEL_INVALID", "PEER_ID_INVALID", "CHAT_ID_INVALID", "USER_NOT_PARTICIPANT", "CHAT_ADMIN_REQUIRED", "INPUT_USER_DEACTIVATED", "Chat not found"]):
                        from core.db import remove_group_info
                        remove_group_info(group['chat_id'])
                        print(f"[Admin] Auto-purged dead group {group['chat_id']} from DB cache!")
                    failed += 1
                await asyncio.sleep(0.15)

            await status_msg.edit_text(
                f"{ROYAL_HEADER}"
                f"✅ <b>Broadcast Completed!</b>\n\n"
                f"• <b>Successful:</b> <code>{success} groups</code>\n"
                f"• <b>Failed:</b> <code>{failed} groups</code>",
                parse_mode=enums.ParseMode.HTML
            )


@Client.on_message(filters.command(["setapi", "apiurl"]))
async def set_api_url_handler(client: Client, message: Message):
    """Admin command to update Local PC API URL live via Telegram message in 1 second."""
    from core.db import save_setting, get_setting
    if not is_sudo_user(message.from_user.id) and message.from_user.id != Config.OWNER_ID:
        return await message.reply_text("❌ <b>Sudo/Owner permission required!</b>", parse_mode=enums.ParseMode.HTML)
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        curr = get_setting("local_api_url") or Config.LOCAL_API_URL or "Not Set"
        return await message.reply_text(
            f"{ROYAL_HEADER}"
            f"⚡ <b>CURRENT LOCAL API URL:</b>\n<code>{curr}</code>\n\n"
            f"💡 <b>To update instantly:</b>\n"
            f"<code>/setapi https://your-new-tunnel.trycloudflare.com</code>",
            parse_mode=enums.ParseMode.HTML
        )
    
    new_url = args[1].strip().rstrip("/")
    if not new_url.startswith("http"):
        return await message.reply_text("❌ <b>Invalid URL format! URL must start with http:// or https://</b>", parse_mode=enums.ParseMode.HTML)
    
    save_setting("local_api_url", new_url)
    Config.LOCAL_API_URL = new_url
    
    await message.reply_text(
        f"{ROYAL_HEADER}"
        f"✅ <b>LOCAL PC API URL UPDATED SUCCESSFULLY!</b>\n\n"
        f"📡 <b>New Live URL:</b> <code>{new_url}</code>\n\n"
        f"⚡ <i>Bot is now live-synced with your Local PC! Zero restart needed!</i>",
        parse_mode=enums.ParseMode.HTML
    )
