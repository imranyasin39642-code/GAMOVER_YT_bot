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
from core.db import is_sudo_user, get_broadcast_groups, set_group_broadcast_enabled, get_db, set_group_welcome_enabled, set_group_bot_active
from core.player import player_manager

ROYAL_HEADER = "👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ 👑</b>\n\n"

# In-memory dictionary to store admin states (e.g. if they are in broadcast input mode)
admin_states = {}

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

def get_api_manager_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔑 LIST ALL KEYS", callback_data="admin_api_list", style="primary"),
            InlineKeyboardButton("⚡ GENERATE KEY", callback_data="admin_api_gen_prompt", style="success")
        ],
        [
            InlineKeyboardButton("📊 API HIT STATS", callback_data="admin_api_stats", style="primary"),
            InlineKeyboardButton("❓ HELP & COMMANDS", callback_data="admin_api_help", style="primary")
        ],
        [
            InlineKeyboardButton("🔙 BACK", callback_data="admin_back", style="primary"),
            InlineKeyboardButton("❌ CLOSE", callback_data="admin_close", style="danger")
        ]
    ])

def get_admin_panel_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 BROADCAST", callback_data="admin_bc_prompt", style="success"),
            InlineKeyboardButton("👥 BC GROUPS", callback_data="admin_groups|0", style="primary")
        ],
        [
            InlineKeyboardButton("👋 WELCOME SETTINGS", callback_data="admin_welcome_groups|0", style="primary"),
            InlineKeyboardButton("🤖 BOT STATUS", callback_data="admin_status_groups|0", style="primary")
        ],
        [
            InlineKeyboardButton("🔑 API MANAGER", callback_data="admin_api_manager", style="success")
        ],
        [
            InlineKeyboardButton("📂 FILE MANAGER", callback_data="admin_file_manager|0", style="primary"),
            InlineKeyboardButton("🍪 COOKIES MANAGER", callback_data="admin_cookies_manager", style="primary")
        ],
        [
            InlineKeyboardButton("🌐 NETWORK MANAGER", callback_data="admin_network", style="primary"),
            InlineKeyboardButton("📹 MANAGE VIDEOS", callback_data="admin_manage_videos", style="primary")
        ],
        [
            InlineKeyboardButton("❌ CLOSE", callback_data="admin_close", style="danger")
        ]
    ])

def get_cookies_status() -> str:
    path = Config.COOKIES_FILE
    if not os.path.exists(path):
        return (
            "🔴 <b>Status: NOT FOUND</b>\n\n"
            "⚠️ <i>No cookies.txt is currently loaded. YouTube resolution might fail on VPS IP addresses without cookies.</i>"
        )
    
    try:
        size_bytes = os.path.getsize(path)
        size_kb = size_bytes / 1024
        mtime = os.path.getmtime(path)
        mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        
        line_count = 0
        cookie_count = 0
        has_netscape_header = False
        youtube_cookies = 0
        has_login_session = False
        login_cookie_names = {"LOGIN_INFO", "__Secure-3PSID", "SID", "HSID", "SSID"}
        
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline()
            if first_line and "netscape" in first_line.lower():
                has_netscape_header = True
            
            f.seek(0)
            for line in f:
                line_count += 1
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.strip().split("\t")
                if len(parts) >= 7:
                    cookie_count += 1
                    domain = parts[0].lower()
                    name = parts[5]
                    if "youtube.com" in domain or "google.com" in domain:
                        youtube_cookies += 1
                        if name in login_cookie_names:
                            has_login_session = True
                            
        warnings = []
        if not has_netscape_header:
            warnings.append("⚠️ <b>Invalid Header:</b> File doesn't start with <code># Netscape HTTP Cookie File</code>. yt-dlp might ignore it.")
        if youtube_cookies == 0:
            warnings.append("⚠️ <b>No YouTube Cookies:</b> No cookies found for <code>youtube.com</code> or <code>google.com</code>.")
        elif not has_login_session:
            warnings.append("⚠️ <b>No Login Session:</b> Missing active login session cookies (<code>LOGIN_INFO</code> / <code>SID</code>).")
            
        warning_text = ""
        if warnings:
            warning_text = "\n\n❌ <b>Issues Detected:</b>\n" + "\n".join(warnings)
        else:
            warning_text = "\n\n✅ <b>All Checks Passed:</b> Cookies file is formatted correctly."

        return (
            "🟢 <b>Status: ACTIVE & LOADED</b>\n\n"
            f"• <b>File Size:</b> <code>{size_kb:.2f} KB</code>\n"
            f"• <b>Total Cookies:</b> <code>{cookie_count}</code>\n"
            f"• <b>YouTube Cookies:</b> <code>{youtube_cookies}</code>\n"
            f"• <b>Login Session:</b> <code>{'Yes' if has_login_session else 'No'}</code>\n"
            f"• <b>Total Lines:</b> <code>{line_count}</code>\n"
            f"• <b>Last Modified:</b> <code>{mtime_str}</code>"
            f"{warning_text}"
        )
    except Exception as e:
        return f"⚠️ <b>Status: ERROR READING FILE</b>\n<code>{str(e)}</code>"

def get_cookies_manager_markup() -> InlineKeyboardMarkup:
    has_cookies = os.path.exists(Config.COOKIES_FILE)
    buttons = []
    if has_cookies:
        buttons.append([
            InlineKeyboardButton("🗑 DELETE COOKIES", callback_data="admin_cookies_delete", style="danger")
        ])
    buttons.append([
        InlineKeyboardButton("🔙 BACK", callback_data="admin_back", style="primary"),
        InlineKeyboardButton("❌ CLOSE", callback_data="admin_close", style="danger")
    ])
    return InlineKeyboardMarkup(buttons)


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

    @app.on_message(filters.document & filters.private & filters.create(is_admin_filter))
    async def handle_cookies_upload(client: Client, message: Message):
        doc = message.document
        if not doc.file_name:
            return
        
        file_name = doc.file_name.lower()
        if "cookies" in file_name and file_name.endswith(".txt"):
            status_msg = await message.reply_text(
                f"{ROYAL_HEADER}"
                f"📥 <b>Detecting Cookies File:</b> <code>{doc.file_name}</code>\n"
                f"⏳ <i>Processing and updating cookies, please wait...</i>",
                parse_mode=enums.ParseMode.HTML
            )
            
            try:
                temp_path = await message.download(file_name="temp_cookies.txt")
                if not temp_path or not os.path.exists(temp_path):
                    from bot import send_styled
                    await send_styled(
                        chat_id=message.chat.id,
                        text=(
                            f"{ROYAL_HEADER}"
                            f"❌ <b>Error: Failed to download the file to VPS.</b>"
                        ),
                        message_id=status_msg.id
                    )
                    return
                
                is_valid = False
                with open(temp_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if not line.strip() or line.startswith("#"):
                            continue
                        parts = line.strip().split("\t")
                        if len(parts) >= 7:
                            is_valid = True
                            break
                
                if not is_valid:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    from bot import send_styled
                    await send_styled(
                        chat_id=message.chat.id,
                        text=(
                            f"{ROYAL_HEADER}"
                            f"❌ <b>Error: Invalid Netscape cookie format!</b>\n\n"
                            f"Make sure you exported the cookies using a browser extension in Netscape format."
                        ),
                        message_id=status_msg.id
                    )
                    return
                
                dest_path = Config.COOKIES_FILE
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                import shutil
                shutil.move(temp_path, dest_path)
                
                status_text = get_cookies_status()
                markup = get_cookies_manager_markup()
                
                from bot import send_styled
                await send_styled(
                    chat_id=message.chat.id,
                    text=(
                        f"{ROYAL_HEADER}"
                        f"✅ <b>Cookies Updated Successfully!</b>\n\n"
                        f"{status_text}"
                    ),
                    markup=markup,
                    message_id=status_msg.id
                )
            except Exception as e:
                from bot import send_styled
                await send_styled(
                    chat_id=message.chat.id,
                    text=(
                        f"{ROYAL_HEADER}"
                        f"❌ <b>Error updating cookies:</b>\n"
                        f"<code>{str(e)}</code>"
                    ),
                    message_id=status_msg.id
                )

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

    @app.on_callback_query(filters.regex(r"^admin_"))
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
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
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
                markup=get_admin_panel_markup(),
                message_id=query.message.id
            )

        elif data == "admin_cookies_manager":
            await query.answer("Loading Cookies Manager...")
            status_text = get_cookies_status()
            markup = get_cookies_manager_markup()
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"🍪 <b>YouTube Cookies Manager</b>\n\n"
                    f"{status_text}\n\n"
                    f"💡 <b>How to update/upload cookies:</b>\n"
                    f"Simply send or forward a Netscape-format <code>.txt</code> file containing the word 'cookies' (e.g. <code>cookies.txt</code>) to this chat.\n\n"
                    f"The bot will automatically validate, delete old cookies, and replace them instantly."
                ),
                markup=markup,
                message_id=query.message.id
            )

        elif data == "admin_cookies_delete":
            path = Config.COOKIES_FILE
            if os.path.exists(path):
                try:
                    os.remove(path)
                    await query.answer("🗑 Cookies deleted from VPS successfully!", show_alert=True)
                except Exception as e:
                    await query.answer(f"❌ Error deleting file: {e}", show_alert=True)
            else:
                await query.answer("⚠️ No cookies.txt found on disk!", show_alert=True)
                
            status_text = get_cookies_status()
            markup = get_cookies_manager_markup()
            from bot import send_styled
            await send_styled(
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"🍪 <b>YouTube Cookies Manager</b>\n\n"
                    f"{status_text}\n\n"
                    f"💡 <b>How to update/upload cookies:</b>\n"
                    f"Simply send or forward a Netscape-format <code>.txt</code> file containing the word 'cookies' (e.g. <code>cookies.txt</code>) to this chat.\n\n"
                    f"The bot will automatically validate, delete old cookies, and replace them instantly."
                ),
                markup=markup,
                message_id=query.message.id
            )

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
            groups = get_broadcast_groups()
            
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
            groups = get_broadcast_groups()
            
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
            groups = get_broadcast_groups()
            
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
                    print(f"[Admin] Broadcast failed for group {group['chat_id']}: {copy_err}")
                    failed += 1
                await asyncio.sleep(0.15)

            await status_msg.edit_text(
                f"{ROYAL_HEADER}"
                f"✅ <b>Broadcast Completed!</b>\n\n"
                f"• <b>Successful:</b> <code>{success} groups</code>\n"
                f"• <b>Failed:</b> <code>{failed} groups</code>",
                parse_mode=enums.ParseMode.HTML
            )
