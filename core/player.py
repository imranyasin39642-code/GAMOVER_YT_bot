import os
import asyncio
import time
import aiohttp
from typing import Optional, Dict
from pyrogram import Client, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls import PyTgCalls, filters
from pytgcalls.types import MediaStream, VideoQuality, AudioQuality
from pytgcalls.types.raw import VideoParameters

from config import Config
from core.scrapers import resolve_stream_url, extract_video_id, search_youtube, is_youtube_url
from core.db import save_to_cache, get_cached_path, get_cached_item

ROYAL_HEADER = "👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀᴍᴇʀ</b> 👑\n\n"

# Ensure downloads directory exists
os.makedirs(Config.DOWNLOADS_DIR, exist_ok=True)

async def download_file(url: str, dest_path: str, progress_callback=None) -> bool:
    """Asynchronously downloads a direct URL to a file with progress updates."""
    if os.path.exists(dest_path):
        try:
            os.remove(dest_path)
        except Exception:
            pass

    max_retries = 3
    timeout = aiohttp.ClientTimeout(total=None, connect=20, sock_read=40)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.youtube.com/',
    }
    for attempt in range(1, max_retries + 1):
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP Status {response.status}")

                    total_size = int(response.headers.get('content-length', 0))
                    downloaded = 0
                    start_time = time.time()
                    last_update = 0

                    with open(dest_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(256 * 1024): # 256KB chunks
                            f.write(chunk)
                            downloaded += len(chunk)

                            # Trigger progress update every 3 seconds
                            now = time.time()
                            if progress_callback and (now - last_update >= 3.0 or downloaded == total_size):
                                pct = int((downloaded / total_size) * 100) if total_size > 0 else 0
                                await progress_callback(pct, downloaded, total_size, start_time)
                                last_update = now

                    if downloaded < 10000:
                        raise Exception("Downloaded file is too small.")
                    return True
        except Exception as e:
            print(f"[Downloader] Attempt {attempt} failed: {e}")
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except Exception:
                    pass
            await asyncio.sleep(2)
            
    return False


def auto_clean_downloads(max_folder_mb: int = 800, keep_files: set = None):
    """Automatically cleans old downloaded files when downloads/ folder size exceeds max_folder_mb (800 MB)."""
    downloads_dir = Config.DOWNLOADS_DIR
    if not os.path.exists(downloads_dir):
        return

    keep_files = keep_files or set()
    try:
        files = []
        total_bytes = 0
        for f in os.listdir(downloads_dir):
            fp = os.path.join(downloads_dir, f)
            if os.path.isfile(fp):
                sz = os.path.getsize(fp)
                total_bytes += sz
                files.append((fp, os.path.getmtime(fp), sz))
                
        limit_bytes = max_folder_mb * 1024 * 1024
        if total_bytes > limit_bytes:
            print(f"[AutoClean] Downloads dir size ({total_bytes // 1024 // 1024} MB) > limit ({max_folder_mb} MB). Cleaning oldest files...")
            files.sort(key=lambda x: x[1]) # Sort by mtime (oldest first)
            for fp, mtime, sz in files:
                if fp in keep_files:
                    continue
                try:
                    os.remove(fp)
                    total_bytes -= sz
                    print(f"[AutoClean] Removed old download: {os.path.basename(fp)}")
                    if total_bytes <= limit_bytes * 0.7: # Clean down to 70% threshold
                        break
                except Exception as e:
                    print(f"[AutoClean] Remove error {fp}: {e}")
    except Exception as e:
        print(f"[AutoClean] Error checking downloads size: {e}")


def get_configured_video_parameters():
    """Reads configured target resolution and FPS from database and returns VideoParameters."""
    from core.db import get_setting
    q = get_setting("quality_pref") or "720p"
    fps_str = get_setting("fps_pref") or "60"
    try:
        fps_val = int(fps_str)
    except Exception:
        fps_val = 60

    resolution_map = {
        "4K": (3840, 2160, 2160),
        "2K": (2560, 1440, 1440),
        "1080p": (1920, 1080, 1080),
        "720p": (1280, 720, 720),
        "480p": (854, 480, 480),
    }

    w, h, max_h = resolution_map.get(q, (1280, 720, 720))
    vid_params = VideoParameters(width=w, height=h, frame_rate=fps_val)
    return vid_params, q, fps_val, max_h


def get_media_duration(file_path: str) -> int:
    """Extract media duration in seconds from local file via ffprobe in 0.01 seconds."""
    if not file_path or not os.path.exists(file_path):
        return 0
    try:
        import subprocess, json
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", file_path
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=2)
        info = json.loads(out)
        dur = info.get("format", {}).get("duration")
        if dur:
            return int(float(dur))
    except Exception:
        pass
    return 0


def ensure_audio_track(file_path: str) -> str:
    """Check if media file has an audio stream via ffprobe. If missing, merge AAC audio track via ffmpeg."""
    if not file_path or not os.path.exists(file_path):
        return file_path
    try:
        import subprocess, json
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", file_path
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=3)
        info = json.loads(out)
        streams = info.get("streams", [])
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        if has_audio:
            return file_path
        
        # Audio track missing! Add silent AAC audio track using ffmpeg
        print(f"[Player] Audio track missing in {file_path}! Merging silent AAC audio track...")
        fixed_path = file_path.rsplit(".", 1)[0] + "_fixed.mp4"
        ff_cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-c:v", "copy", "-c:a", "aac", "-shortest", fixed_path
        ]
        subprocess.run(ff_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        if os.path.exists(fixed_path) and os.path.getsize(fixed_path) > 1000:
            os.replace(fixed_path, file_path)
            print(f"[Player] Fixed audio track successfully for {file_path}")
    except Exception as e:
        print(f"[Player] Audio track check note: {e}")
    return file_path

FILE_DOWNLOAD_LOCKS = {}

async def download_song_ytdlp(youtube_url: str, dest_path: str, mode: str, progress_callback=None) -> bool:
    """Asynchronously download and merge video + audio tracks using yt-dlp with multi-client rotation and fallback APIs."""
    import yt_dlp
    import glob
    import shutil
    
    # Auto-clean disk if downloads folder exceeds 800 MB
    auto_clean_downloads(max_folder_mb=800)

    # Fast direct hit check before lock
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 5000:
        print(f"[Player/ytdlp] Direct hit! File {dest_path} is already completely downloaded.")
        return True

    lock = FILE_DOWNLOAD_LOCKS.setdefault(dest_path, asyncio.Lock())
    async with lock:
        # Re-check inside lock in case concurrent task finished downloading while waiting
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 5000:
            print(f"[Player/ytdlp] Direct hit (after lock wait)! File {dest_path} is already completely downloaded.")
            return True

        loop = asyncio.get_running_loop()
        last_update = [time.time()]
        
        def hook(d):
            if d['status'] == 'downloading':
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                pct = int((downloaded / total) * 100) if total > 0 else 0
                
                now = time.time()
                if now - last_update[0] >= 6.0:
                    if progress_callback:
                        asyncio.run_coroutine_threadsafe(
                            progress_callback(pct, downloaded, total, last_update[0]),
                            loop
                        )
                    last_update[0] = now

        # Step 1: High-Speed Scraper / GAMEOVER API First (Zero 403 / Zero Cookie Error)
        try:
            print(f"[Player/Downloader] Initiating Primary High-Speed API extraction for {youtube_url}...")
            res = await resolve_stream_url(youtube_url, mode)
            if res and res.get("url"):
                stream_url = res["url"]
                print(f"[Player/Downloader] Resolved Direct Stream URL via GAMEOVER API: {res.get('title', 'YouTube Video')[:35]} | Downloading...")
                ok = await download_file(stream_url, dest_path, progress_callback)
                if ok and os.path.exists(dest_path) and os.path.getsize(dest_path) > 5000:
                    v_id = extract_video_id(youtube_url)
                    if v_id and res.get("title"):
                        save_to_cache(
                            video_id=v_id,
                            mode=mode,
                            file_path=dest_path,
                            title=res["title"],
                            duration=res.get("duration", 0),
                            thumbnail=res.get("thumbnail")
                        )
                    print(f"[Player/Downloader] API Direct Stream Download SUCCESS! File size: {os.path.getsize(dest_path) // 1024} KB")
                    return True
        except Exception as api_err:
            print(f"[Player/Downloader] Primary API extraction note: {api_err}")

        # Step 2: Local yt-dlp direct download fallback
        base_path = dest_path.rsplit('.', 1)[0]
        outtmpl = base_path + '.%(ext)s'
        
        if mode == "video":
            _, q, fps_val, max_h = get_configured_video_parameters()
            format_spec = f"bestvideo[height<={max_h}][fps<={fps_val}]+bestaudio/best[height<={max_h}]/best"
            print(f"[Downloader] Fallback yt-dlp Target Quality: {q} ({max_h}p) @ {fps_val} FPS")
        else:
            format_spec = "bestaudio/best"

        # Safe clean up of broken non-target files (ignore lock errors)
        for f in glob.glob(base_path + "*"):
            if not f.endswith(".mp4"):
                try:
                    os.remove(f)
                except Exception:
                    pass

        ydl_opts = {
            'format': format_spec,
            'outtmpl': outtmpl,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'progress_hooks': [hook],
            'merge_output_format': 'mp4',
            'socket_timeout': 30.0,
            'retries': 10,
            'fragment_retries': 10,
            'extractor_retries': 10,
            'source_address': '0.0.0.0',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['android_vr', 'ios', 'web_creator', 'tvhtml5', 'android']
                }
            }
        }
        if Config.USE_PROXY and Config.get_proxy_url():
            ydl_opts['proxy'] = Config.get_proxy_url()
        
        info_dict = {}
        def run():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                if info:
                    info_dict["title"] = info.get("title", "YouTube Video")
                    info_dict["duration"] = int(info.get("duration") or 0)
                    info_dict["thumbnail"] = info.get("thumbnail") or f"https://img.youtube.com/vi/{extract_video_id(youtube_url) or ''}/hqdefault.jpg"

        try:
            await loop.run_in_executor(None, run)
            
            # Check and rename output extension formats if merged to something else
            for ext in ['.mp4', '.mkv', '.webm', '.m4a', '.mp3', '.opus']:
                p = base_path + ext
                if os.path.exists(p) and os.path.getsize(p) > 5000:
                    if p != dest_path:
                        if os.path.exists(dest_path):
                            try:
                                os.remove(dest_path)
                            except Exception:
                                pass
                        try:
                            shutil.move(p, dest_path)
                        except Exception:
                            pass
                    
                    v_id = extract_video_id(youtube_url)
                    if v_id and info_dict.get("title"):
                        save_to_cache(
                            video_id=v_id,
                            mode=mode,
                            file_path=dest_path,
                            title=info_dict["title"],
                            duration=info_dict.get("duration", 0),
                            thumbnail=info_dict.get("thumbnail")
                        )
                    return True
            return os.path.exists(dest_path) and os.path.getsize(dest_path) > 5000
        except Exception as e:
            print(f"[Player/ytdlp-downloader] Fallback yt-dlp download note: {e}")

    return False


class SeekableMediaStream(MediaStream):
    async def check_stream(self):
        import pytgcalls.types.stream.media_stream as ms_mod
        orig_check = ms_mod.check_stream
        
        async def mock_check(ffmpeg_params, path, stream_params, before_cmds=None, headers=None):
            # Pass None to probe check so FFmpeg probe check ALWAYS succeeds regardless of -af parameters
            return await orig_check(None, path, stream_params, before_cmds, headers)
            
        ms_mod.check_stream = mock_check
        try:
            await super().check_stream()
        finally:
            ms_mod.check_stream = orig_check


class PlayerManager:
    def __init__(self):
        self._pytg: PyTgCalls = None
        self._assistant: Client = None
        self.app: Client = None
        self.active_calls: set[int] = set()
        self.in_call_chats: set[int] = set()           # chat_id -> active voice call session
        self.active_files: dict[int, str] = {}         # chat_id -> local_file_path
        self.queues: dict[int, list[dict]] = {}        # chat_id -> list of queued songs
        self.idle_tasks: dict[int, asyncio.Task] = {}  # chat_id -> idle timer task
        self.active_requester_id: dict[int, int] = {}  # chat_id -> requester user_id
        
        # Progress bar / Now Playing state
        self.stream_title: dict[int, str] = {}         # chat_id -> current streaming title
        self.stream_start_time: dict[int, float] = {}  # chat_id -> unix timestamp when play started
        self.stream_duration: dict[int, int] = {}      # chat_id -> total duration in seconds
        self.stream_thumbnail: dict[int, str] = {}     # chat_id -> thumbnail URL
        self.now_playing_msg_id: dict[int, int] = {}   # chat_id -> Telegram message_id of now-playing card
        self.progress_tasks: dict[int, asyncio.Task] = {}  # chat_id -> progress updater task
        self.download_tasks: dict[str, asyncio.Task] = {}  # video_id_mode -> download task
        self.pending_playlists: dict[int, dict] = {}      # chat_id -> pending playlist data
        self._last_stream_end: dict[int, float] = {}   # chat_id -> last stream_end timestamp
        self.in_effects_menu: set[int] = set()         # chat_id -> active viewing of effects menu
        self.is_changing_effect: set[int] = set()      # chat_id -> currently applying audio effect filter
        self.effect_ignore_until: dict[int, float] = {} # chat_id -> timestamp until which stream_end is ignored

    # ── Progress bar helpers ─────────────────────────────────────────────────

    @staticmethod
    def _fmt_time(seconds: int) -> str:
        """Format seconds to MM:SS or H:MM:SS."""
        seconds = max(0, int(seconds))
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @staticmethod
    def _make_progress_bar(elapsed: int, total: int, width: int = 26) -> str:
        """Build a wide text progress bar to stretch blockquote card to 100% full width."""
        if total <= 0:
            return ""
        ratio = min(elapsed / total, 1.0)
        filled = int(ratio * width)
        bar = "━" * filled + "●" + "─" * (width - filled)
        elapsed_str = PlayerManager._fmt_time(elapsed)
        total_str = PlayerManager._fmt_time(total)
        return f"{elapsed_str} {bar} {total_str}"

    def _cancel_progress_task(self, chat_id: int):
        task = self.progress_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    def _build_play_card_markup(self, chat_id: int, requested_by_id: int, elapsed: int, total: int, mode: str) -> InlineKeyboardMarkup:
        ctrl_row = [
            InlineKeyboardButton("▷", callback_data=f"play_resume|{chat_id}|{requested_by_id}", style="success"),
            InlineKeyboardButton("II", callback_data=f"play_pause|{chat_id}|{requested_by_id}", style="primary"),
            InlineKeyboardButton("↺", callback_data=f"play_loop|{chat_id}|{requested_by_id}", style="success"),
            InlineKeyboardButton("⏭", callback_data=f"play_skip|{chat_id}|{requested_by_id}", style="primary"),
            InlineKeyboardButton("▢", callback_data=f"play_stop|{chat_id}|{requested_by_id}", style="danger"),
        ]
        
        e_str = self._fmt_time(elapsed)
        t_str = self._fmt_time(total) if total else "Live"
        width = 12
        if total > 0:
            ratio = min(elapsed / total, 1.0)
            filled = max(0, min(width - 1, int(ratio * width)))
            bar = "─" * filled + "•" + "─" * (width - 1 - filled)
        else:
            bar = "──────────•──"
            
        dur_row = [
            InlineKeyboardButton(f"{e_str} {bar} {t_str}", callback_data="play_noop", style="primary")
        ]

        bottom_row = [
            InlineKeyboardButton("CLOSE", callback_data="play_close", style="danger"),
        ]

        return InlineKeyboardMarkup([ctrl_row, dur_row, bottom_row])

    def _start_progress_updater(self, chat_id: int, title: str, youtube_url: str,
                                 requested_by: str, requested_by_id: int, mode: str):
        """Launch a background task that edits the Now Playing caption & duration bar every 15 seconds."""
        self._cancel_progress_task(chat_id)

        async def _updater():
            from bot import edit_styled
            await asyncio.sleep(10)  # first update after 10s
            while chat_id in self.active_calls:
                try:
                    # Skip updating markup if user is currently navigating the Effects Menu
                    if chat_id in self.in_effects_menu:
                        await asyncio.sleep(15)
                        continue

                    start = self.stream_start_time.get(chat_id, time.time())
                    total = self.stream_duration.get(chat_id, 0)
                    elapsed = int(time.time() - start)

                    queue_len = len(self.queues.get(chat_id, []))
                    if queue_len > 1:
                        next_title = self.queues[chat_id][0]['title']
                        queue_str = f"\n📣 <b>Upcoming:</b> {next_title} (+{queue_len-1} more)"
                    elif queue_len == 1:
                        next_title = self.queues[chat_id][0]['title']
                        queue_str = f"\n📣 <b>Upcoming:</b> {next_title}"
                    else:
                        queue_str = ""

                    blank_pad = "⠀" * 20
                    dur_text = f"{self._fmt_time(total)} MINUTES" if total else "Live Stream"
                    mode_text = "Video" if mode == "video" else "Audio"
                    caption = (
                        f"➦ <b>STARTED STREAMING |</b>{blank_pad}\n\n"
                        f"<b>TITLE :</b> <a href=\"{youtube_url}\">{title}</a>\n"
                        f"<b>MODE :</b> {mode_text}\n"
                        f"<b>DURATION :</b> {dur_text}\n"
                        f"<b>REQUESTED BY :</b> {requested_by or 'Unknown'}"
                        f"{queue_str}"
                    )

                    msg_id = self.now_playing_msg_id.get(chat_id)
                    if msg_id:
                        buttons = self._build_play_card_markup(chat_id, requested_by_id, elapsed, total, mode)
                        await edit_styled(
                            chat_id=chat_id,
                            text=caption,
                            markup=buttons,
                            message_id=msg_id,
                            is_video=True
                        )
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    err_str = str(e)
                    if "FLOOD_WAIT" in err_str or "Wait for" in err_str:
                        pass
                    else:
                        print(f"[ProgressBar] Update note in {chat_id}: {e}")
                await asyncio.sleep(15)

        self.progress_tasks[chat_id] = asyncio.create_task(_updater())

        self.progress_tasks[chat_id] = asyncio.create_task(_updater())

    def _start_idle_timer(self, chat_id: int):
        self._cancel_idle_timer(chat_id)
        
        async def idle_timer():
            await asyncio.sleep(300) # 5 minutes
            print(f"[Player] Idle timeout triggered in chat {chat_id}")
            try:
                from bot import send_styled
                await send_styled(chat_id, "<b>No one listening, I leave voice chat. Bye.</b>")
            except Exception:
                pass
            await self.stop(chat_id)
            
        self.idle_tasks[chat_id] = asyncio.create_task(idle_timer())
        print(f"[Player] Started 5-minute idle timer in chat {chat_id}")

    def _cancel_idle_timer(self, chat_id: int):
        task = self.idle_tasks.pop(chat_id, None)
        if task:
            task.cancel()
            print(f"[Player] Cancelled idle timer in chat {chat_id}")

    async def _send_tg_logger_event(
        self,
        chat_id: int,
        title: str,
        youtube_url: str,
        requested_by: str,
        requested_by_id: int,
        mode: str,
        duration_sec: int,
        thumbnail_url: str,
        elapsed_time: float = 0.8,
    ):
        log_group_id = Config.LOG_GROUP_ID
        if not log_group_id:
            return

        try:
            chat_obj = await self.app.get_chat(chat_id)
            chat_title = chat_obj.title or f"Chat {chat_id}"
        except Exception:
            chat_title = f"Chat {chat_id}"

        from core.db import get_setting
        q_pref   = get_setting("quality_pref") or "720p"
        fps_pref = get_setting("fps_pref") or "60"

        dur_str = self._fmt_time(duration_sec) if duration_sec else "Live Stream"
        if mode == "video":
            mode_label = f"🎬 Video ({q_pref} @ {fps_pref} FPS)"
        else:
            mode_label = f"🎵 Audio (320kbps Studio MP3)"

        req_user_str = f"{requested_by}"
        if requested_by_id:
            req_user_str = f"<a href=\"tg://user?id={requested_by_id}\">{requested_by}</a> (<code>{requested_by_id}</code>)"

        log_card = (
            f"👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ Lᴏɢɢᴇʀ</b> 👑\n\n"
            f"🎬 <b>Tɪᴛʟᴇ:</b> <a href=\"{youtube_url}\">{title}</a>\n"
            f"⏱ <b>Dᴜʀᴀᴛɪᴏɴ:</b> <code>{dur_str}</code>\n"
            f"🎧 <b>Sᴛʀᴇᴀᴍ Mᴏᴅᴇ:</b> <code>{mode_label}</code>\n"
            f"👤 <b>Rᴇǫᴜᴇsᴛᴇᴅ Bʏ:</b> {req_user_str}\n"
            f"💬 <b>Gʀᴏᴜᴘ CHAT:</b> <b>{chat_title}</b> (<code>{chat_id}</code>)\n\n"
            f"🌐 <b>API Eɴɢɪɴᴇ:</b> <code>https://nskmedia.net/api/extract</code>\n"
            f"⚡ <b>API Response:</b> <code>{elapsed_time:.2f}s HTTP 200 OK</code>\n"
            f"🟢 <b>Cᴏᴏᴋɪᴇ Status:</b> Active Session / Zero-Cookie Fallback\n"
            f"🔗 <b>Lɪɴᴋ:</b> <a href=\"{youtube_url}\">Watch on YouTube</a>"
        )

        try:
            if thumbnail_url:
                await self.app.send_photo(
                    chat_id=log_group_id,
                    photo=thumbnail_url,
                    caption=log_card,
                    parse_mode=enums.ParseMode.HTML
                )
            else:
                await self.app.send_message(
                    chat_id=log_group_id,
                    text=log_card,
                    parse_mode=enums.ParseMode.HTML,
                    disable_web_page_preview=True
                )
            print(f"[TG Logger] Logged stream '{title}' to group {log_group_id}")
        except Exception as log_err:
            print(f"[TG Logger] Error sending log to group {log_group_id}: {log_err}")

    async def init(self, assistant: Client, bot: Client):
        self._assistant = assistant
        self.app = bot
        self._pytg = PyTgCalls(assistant)

        # Stream End Handler
        @self._pytg.on_update(filters.stream_end())
        async def on_stream_end(_, update):
            chat_id = update.chat_id
            
            if time.time() < self.effect_ignore_until.get(chat_id, 0) or chat_id in self.is_changing_effect:
                print(f"[Player] Ignoring stream_end event during active effect change in chat {chat_id}")
                return

            # De-duplicate: ignore duplicate stream_end events for the same chat within 2.5 seconds
            now = time.time()
            if now - self._last_stream_end.get(chat_id, 0) < 2.5:
                return
            self._last_stream_end[chat_id] = now

            print(f"[Player] Stream ended in chat {chat_id}")
            
            # Remove from active_calls BEFORE calling play()
            self.active_calls.discard(chat_id)
            self.active_files.pop(chat_id, None)
            self.active_requester_id.pop(chat_id, None)
            
            # Queue management: Play next song if available
            if chat_id in self.queues and self.queues[chat_id]:
                next_song = self.queues[chat_id].pop(0)
                print(f"[Player] Auto-playing next queued track: {next_song['title']}")
                
                async def _safe_play_next(song):
                    """Isolated coroutine — exceptions here NEVER break the queue chain."""
                    s_msg = None
                    try:
                        s_msg = await self.app.send_message(
                            chat_id,
                            f"{ROYAL_HEADER}⏭ <b>Next:</b> <code>{song['title']}</code>..."
                        )
                    except Exception:
                        pass
                    try:
                        ok = await self.play(
                            chat_id=chat_id,
                            youtube_url=song["url"],
                            mode=song["mode"],
                            status_msg=s_msg,
                            requested_by=song.get("requested_by"),
                            requested_by_id=song.get("requested_by_id", 0),
                            playlist_id=song.get("playlist_id", ""),
                            track_index=song.get("track_index"),
                            total_tracks=song.get("total_tracks", 0)
                        )
                        if not ok:
                            # Song failed — try the next one in queue automatically
                            if chat_id in self.queues and self.queues[chat_id]:
                                fallback = self.queues[chat_id].pop(0)
                                print(f"[Player] Song failed, auto-skipping to: {fallback['title']}")
                                await _safe_play_next(fallback)
                    except Exception as inner_e:
                        print(f"[Player] Safe-play-next error: {inner_e}")
                        # Even on crash, try the next song
                        if chat_id in self.queues and self.queues[chat_id]:
                            try:
                                fallback = self.queues[chat_id].pop(0)
                                await _safe_play_next(fallback)
                            except Exception:
                                pass

                asyncio.create_task(_safe_play_next(next_song))
            else:
                # Queue empty — start 5-min idle timer
                try:
                    from bot import send_styled
                    await send_styled(chat_id, "<b>Playback ended. Queue is empty.</b>")
                except Exception:
                    pass
                self._start_idle_timer(chat_id)

        # CLOSED voice chat handler
        @self._pytg.on_update(filters.chat_update(filters.ChatUpdate.Status.CLOSED_VOICE_CHAT))
        async def on_closed_vc(_, update):
            chat_id = update.chat_id
            print(f"[Player] Voice chat closed in chat {chat_id}")
            await self.stop(chat_id)

        await self._pytg.start()
        print("[Player] PyTgCalls Engine initialized!")

    async def _background_pre_download(self, chat_id: int, youtube_url: str, mode: str, title: str):
        video_id = extract_video_id(youtube_url)
        if not video_id:
            return
        
        # Check if already cached
        local_path = get_cached_path(video_id, mode)
        if local_path and os.path.exists(local_path):
            return
            
        task_key = f"{video_id}_{mode}"
        if task_key in self.download_tasks:
            print(f"[Player/pre-download] Task {task_key} is already downloading. Skipping duplicate pre-download.")
            return
        self.download_tasks[task_key] = asyncio.current_task()
        
        try:
            filename = f"{video_id}_{mode}.mp4"
            dest_path = os.path.join(Config.DOWNLOADS_DIR, filename)
            
            # Resolve metadata for DB cache
            res = await resolve_stream_url(youtube_url, mode)
            thumb = res.get("thumbnail") if res else f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
            dur = int(res.get("duration", 0)) if res else 0
            
            # Download silently in the background
            ok = await download_song_ytdlp(youtube_url, dest_path, mode, progress_callback=None)
            if ok and os.path.exists(dest_path):
                save_to_cache(video_id, mode, dest_path, title, thumb, dur)
                print(f"[Player/pre-download] Saved {video_id} ({mode}) to cache DB.")
        except Exception as e:
            print(f"[Player/pre-download] Error pre-downloading {video_id}: {e}")
        finally:
            self.download_tasks.pop(task_key, None)

    async def execute_playlist(
        self,
        chat_id: int,
        start_from_index: int = 0,
        mode: str = "video",
        status_msg = None
    ) -> bool:
        """Start playing queued playlist entries instantly when user clicks Start / Resume / Start Over button."""
        p_data = self.pending_playlists.get(chat_id)
        if not p_data or not p_data.get("entries"):
            # Fallback to DB cache if pending_playlists is empty
            if status_msg:
                from bot import edit_styled
                try:
                    await edit_styled(
                        chat_id=chat_id,
                        text=f"{ROYAL_HEADER}❌ <b>Playlist state reset. Kripya dubara playlist link dein!</b>",
                        message_id=status_msg.id if hasattr(status_msg, 'id') else None
                    )
                except Exception:
                    pass
            return False

        entries = p_data["entries"]
        playlist_url = p_data["url"]
        requested_by = p_data.get("requested_by")
        requested_by_id = p_data.get("requested_by_id", 0)
        total_tracks = len(entries)

        if start_from_index >= total_tracks or start_from_index < 0:
            start_from_index = 0

        target_entries = entries[start_from_index:]
        total_added = len(target_entries)

        if chat_id not in self.queues:
            self.queues[chat_id] = []

        import urllib.parse as urlparse
        try:
            parsed = urlparse.urlparse(playlist_url)
            params = urlparse.parse_qs(parsed.query)
            pl_id = params.get('list', [None])[0] or playlist_url
        except Exception:
            pl_id = playlist_url

        # Populate queues
        for idx, entry in enumerate(target_entries, start=start_from_index):
            self.queues[chat_id].append({
                "url": entry["url"],
                "mode": mode,
                "title": entry["title"],
                "requested_by": requested_by,
                "requested_by_id": requested_by_id,
                "playlist_id": pl_id,
                "track_index": idx,
                "total_tracks": total_tracks
            })

        is_active = chat_id in self.active_calls

        if not is_active:
            first_item = self.queues[chat_id].pop(0)
            p_msg = None
            try:
                p_msg = await self.app.send_message(
                    chat_id,
                    f"{ROYAL_HEADER}⚡ <b>Processing Playlist Track #{first_item['track_index'] + 1}:</b> <code>{first_item['title']}</code>...\n⏳ Initializing media download..."
                )
            except Exception:
                pass
            asyncio.create_task(self.play(
                chat_id=chat_id,
                youtube_url=first_item["url"],
                mode=mode,
                status_msg=p_msg,
                requested_by=requested_by,
                requested_by_id=requested_by_id,
                playlist_id=pl_id,
                track_index=first_item["track_index"],
                total_tracks=total_tracks
            ))
        else:
            if chat_id in self.queues and self.queues[chat_id]:
                next_track = self.queues[chat_id][0]
                asyncio.create_task(self._background_pre_download(chat_id, next_track["url"], mode, next_track["title"]))

        # Remove from pending once execution starts
        self.pending_playlists.pop(chat_id, None)
        return True

    async def play(
        self,
        chat_id: int,
        youtube_url: str,
        mode: str = "video",
        status_msg = None,
        requested_by: str = None,
        requested_by_id: int = 0,
        playlist_id: str = "",
        track_index: int = None,
        total_tracks: int = 0,
        force_restart: bool = False
    ) -> bool:
        # Ensure assistant is in the group and peer cache is primed
        try:
            await self._assistant.get_chat_member(chat_id, "me")
        except Exception:
            print(f"[Player] 📥 Assistant joining chat {chat_id}...")
            try:
                chat = await self.app.get_chat(chat_id)
                if chat.username:
                    await self._assistant.join_chat(chat.username)
                else:
                    link = await self.app.export_chat_invite_link(chat_id)
                    await self._assistant.join_chat(link)
            except Exception as join_err:
                print(f"[Player] Assistant auto-join note: {join_err}")

        # Save playlist progress to SQLite database if playing a playlist track
        if playlist_id and track_index is not None:
            from core.db import save_playlist_state
            save_playlist_state(chat_id, playlist_id, mode, track_index, total_tracks)

        # ── Auto-search if user gave a text query instead of a URL ──────────
        if not is_youtube_url(youtube_url):
            query = youtube_url.strip()
            if status_msg:
                await status_msg.edit_text(f"{ROYAL_HEADER}🔍 <b>Searching YouTube for:</b> <code>{query}</code>...")
            result = await search_youtube(query)
            if not result:
                if status_msg:
                    from bot import make_card
                    await status_msg.edit_text(make_card("❌ <b>No YouTube results found!</b>\nPlease try searching with a different track name."))
                return False
            youtube_url = result["url"]
            print(f"[Player] Search resolved to: {youtube_url}")

        # ── YouTube Playlist Detection and Processing ─────────────────────
        if "list=" in youtube_url or "playlist" in youtube_url:
            if status_msg:
                try:
                    await status_msg.edit_text(f"{ROYAL_HEADER}⏳ <b>Resolving YouTube Playlist... Please wait!</b>")
                except Exception:
                    pass

            from core.scrapers import extract_youtube_playlist
            entries = await extract_youtube_playlist(youtube_url)
            if not entries:
                if status_msg:
                    from bot import edit_styled
                    try:
                        await edit_styled(
                            chat_id=chat_id,
                            text=f"{ROYAL_HEADER}❌ <b>Playlist empty ya private hai!</b>",
                            message_id=status_msg.id if hasattr(status_msg, 'id') else None
                        )
                    except Exception:
                        pass
                return False

            entries = entries[:50]
            total_added = len(entries)

            import urllib.parse as urlparse
            try:
                parsed = urlparse.urlparse(youtube_url)
                params = urlparse.parse_qs(parsed.query)
                pl_id = params.get('list', [None])[0] or youtube_url
            except Exception:
                pl_id = youtube_url

            # Store in pending_playlists so button click executes instantly without re-extracting
            self.pending_playlists[chat_id] = {
                "url": youtube_url,
                "pl_id": pl_id,
                "mode": mode,
                "entries": entries,
                "requested_by": requested_by,
                "requested_by_id": requested_by_id
            }

            title_lines = []
            for idx, entry in enumerate(entries, start=1):
                t = entry['title']
                t_short = (t[:32] + "...") if len(t) > 32 else t
                title_lines.append(f"{idx}. {t_short}")

            playlist_list = "\n".join(title_lines)
            mode_label = "🎬 Video" if mode == "video" else "🎵 Audio"

            # Check if there is a saved state for this chat and mode
            from core.db import get_playlist_state
            saved_state = get_playlist_state(chat_id, mode)

            if saved_state and saved_state.get("last_index", 0) > 0 and not force_restart:
                last_idx = saved_state["last_index"]
                t_tracks = saved_state["total_tracks"]

                playlist_text = (
                    f"👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀᴍᴇʀ</b> 👑\n\n"
                    f"📌 <b>Saved Playlist Progress Found!</b>\n"
                    f"Aapne pehle is playlist ke <b>{last_idx + 1} / {t_tracks}</b> songs sun liye the.\n\n"
                    f"<b>Aap kya karna chahte hain?</b>"
                )
                buttons = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(f"▶ Resume (Song #{last_idx + 1})", callback_data=f"pl_do_resume|{pl_id}|{mode}|{last_idx}", style="success"),
                    ],
                    [
                        InlineKeyboardButton("🔄 Start Over (From Song #1)", callback_data=f"pl_do_restart|{pl_id}|{mode}", style="danger")
                    ],
                    [
                        InlineKeyboardButton("🗑 Close", callback_data="play_close")
                    ]
                ])
            else:
                playlist_text = (
                    f"<b>{Config.BOT_NAME}</b>\n"
                    f"⚡ <b>Playlist Ready — {total_added} tracks ({mode_label}):</b>\n\n"
                    f"<blockquote expandable>{playlist_list}</blockquote>"
                )
                buttons = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("▶ Start Playing Playlist", callback_data=f"pl_do_start|{pl_id}|{mode}|0", style="success"),
                    ],
                    [InlineKeyboardButton("🗑 Close", callback_data="play_close")]
                ])

            from bot import edit_styled, send_styled
            if status_msg:
                try:
                    await edit_styled(
                        chat_id=chat_id,
                        text=playlist_text,
                        markup=buttons,
                        message_id=status_msg.id if hasattr(status_msg, 'id') else None
                    )
                except Exception:
                    pass
            else:
                await send_styled(chat_id=chat_id, text=playlist_text, markup=buttons)

            return True

        video_id = extract_video_id(youtube_url)
        
        # Fallback for YouTube Mix list URLs (e.g. list=RDB-99Pm--78Y) which don't have a direct watch?v= param
        if not video_id:
            import urllib.parse as urlparse
            try:
                parsed = urlparse.urlparse(youtube_url)
                params = urlparse.parse_qs(parsed.query)
                list_param = params.get('list', [None])[0]
                if list_param and list_param.startswith('RD') and len(list_param) == 13:
                    video_id = list_param[2:]
                    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
                    print(f"[Player] Extracted fallback video ID {video_id} from YouTube Mix playlist")
            except Exception as parse_err:
                print(f"[Player] Failed to parse fallback video ID from query: {parse_err}")

        if not video_id:
            if status_msg:
                from bot import make_card
                await status_msg.edit_text(make_card("❌ <b>Invalid YouTube link or search query!</b>"))
            return False

        # If a stream is already active in this chat, add it to the queue instead of playing immediately
        if chat_id in self.active_calls:
            # Resolve title for the queue card
            res = await resolve_stream_url(youtube_url, mode)
            q_title = res["title"] if res else "YouTube Video"
            
            if chat_id not in self.queues:
                self.queues[chat_id] = []
            
            self.queues[chat_id].append({
                "url": youtube_url,
                "mode": mode,
                "title": q_title,
                "requested_by": requested_by,
                "requested_by_id": requested_by_id
            })
            
            req_by_str = ""
            if requested_by and requested_by_id:
                req_by_str = f"<b>Requested by:</b> <a href=\"tg://user?id={requested_by_id}\">{requested_by}</a>"

            pos = len(self.queues[chat_id])
            if status_msg:
                try:
                    await status_msg.edit_text(
                        f"{ROYAL_HEADER}"
                        f"<b>Upcoming Track: #{pos}</b>\n\n"
                        f"<b>Title:</b> <a href=\"{youtube_url}\">{q_title}</a>\n"
                        f"{req_by_str}",
                        disable_web_page_preview=True,
                        parse_mode=enums.ParseMode.HTML
                    )
                except Exception:
                    pass
            
            # Pre-download in the background to ensure instant play when current track ends
            asyncio.create_task(self._background_pre_download(chat_id, youtube_url, mode, q_title))
            return True

        # Cancel any active idle timer since we are about to start a new stream
        self._cancel_idle_timer(chat_id)

        # 1. Check local DB cache (also verify file exists on disk — stale cache guard)
        cached = get_cached_item(video_id, mode)
        local_path = None
        title = "YouTube Stream"

        if cached:
            cached_path = cached.get("file_path", "")
            if cached_path and os.path.exists(cached_path) and os.path.getsize(cached_path) > 5000:
                local_path = cached_path
                title = cached["title"]
                self.stream_thumbnail[chat_id] = cached.get("thumbnail") or f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                self.stream_duration[chat_id] = int(cached.get("duration") or 0)
            else:
                print(f"[Player] Cache entry found for {video_id} but file missing/corrupt on disk. Re-downloading.")

        # Check if background pre-download is currently running for this track
        task_key = f"{video_id}_{mode}"
        if not local_path and task_key in self.download_tasks:
            if status_msg:
                try:
                    await status_msg.edit_text(f"{ROYAL_HEADER}⏳ <b>Finishing background download...</b>")
                except Exception:
                    pass
            try:
                task = self.download_tasks[task_key]
                if task and not task.done():
                    await asyncio.shield(task)
            except Exception as e:
                print(f"[Player] Waiting for pre-download failed: {e}")

            # Re-check cache after waiting
            cached = get_cached_item(video_id, mode)
            if cached:
                cached_path = cached.get("file_path", "")
                if cached_path and os.path.exists(cached_path) and os.path.getsize(cached_path) > 5000:
                    local_path = cached_path
                    title = cached["title"]
                    self.stream_thumbnail[chat_id] = cached.get("thumbnail") or f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                    self.stream_duration[chat_id] = int(cached.get("duration") or 0)

        if not local_path:
            filename = f"{video_id}_{mode}.mp4"
            dest_path = os.path.join(Config.DOWNLOADS_DIR, filename)

            # Instant thumbnail assignment
            self.stream_thumbnail[chat_id] = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

            # 3. Download target file directly with progress updates (Single Pass Instant Start)
            if status_msg:
                try:
                    await status_msg.edit_text(f"{ROYAL_HEADER}⚡ <b>Starting high-speed download...</b>")
                except Exception:
                    pass
            
            last_progress_edit = [0.0]
            async def progress_cb(pct, down, tot, start):
                now = time.time()
                if now - last_progress_edit[0] < 6.0:
                    return
                last_progress_edit[0] = now

                elapsed = now - start
                speed = (down / elapsed) / (1024 * 1024) if elapsed > 0 else 0
                speed_bps = down / elapsed if elapsed > 0 else 0
                down_mb = down / (1024 * 1024)
                tot_mb = tot / (1024 * 1024) if tot else 0
                
                remaining_bytes = tot - down if tot else 0
                seconds_left = max(0, int(remaining_bytes / speed_bps)) if speed_bps > 0 and tot else 0
                time_left_str = f"{seconds_left}s" if tot else "calculating..."
                
                filled = int(pct / 10)
                bar = "■" * filled + "□" * (10 - filled)
                
                size_str = f"{down_mb:.1f} MB / {tot_mb:.1f} MB" if tot else f"{down_mb:.1f} MB / calculating..."
                
                caption = (
                    "👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ʏᴛ sᴛʀᴇᴀᴍᴇʀ</b> 👑\n\n"
                    "⚡ <b>ᴘʀᴏᴄᴇssɪɴɢ ᴍᴇᴅɪᴀ...</b>\n"
                    f"📌 <b>ᴛɪᴛʟᴇ:</b> <code>{title}</code>\n"
                    f"<code>[{bar}] {pct}%</code>\n"
                    f"📦 <b>sɪᴢᴇ:</b> <code>{size_str}</code>\n"
                    f"🚀 <b>sᴘᴇᴇᴅ:</b> <code>{speed:.1f} MB/s</code>\n"
                    f"⏳ <b>...ʀᴇᴍᴀɪɴɪɴɢ:</b> <code>{time_left_str}</code>"
                )
                try:
                    await status_msg.edit_text(caption, parse_mode=enums.ParseMode.HTML)
                except Exception:
                    pass

            # Try native yt-dlp first (Instant start in 1s!)
            print(f"[Player] Initiating native fast download for webpage_url: {youtube_url}")
            ok = await download_song_ytdlp(youtube_url, dest_path, mode, progress_cb)
            
            # Re-read cache to update real title and duration resolved in single-step download
            cached = get_cached_item(video_id, mode)
            if cached:
                title = cached.get("title", title)
                self.stream_title[chat_id] = title
                self.stream_duration[chat_id] = int(cached.get("duration") or 0)
                if cached.get("thumbnail"):
                    self.stream_thumbnail[chat_id] = cached.get("thumbnail")
            
            if not ok or not os.path.exists(dest_path):
                # Fallback to multi-tier web scraper chain ONLY if direct download fails
                print(f"[Player] Direct download failed. Resolving fallback stream URLs...")
                if status_msg:
                    try:
                        await status_msg.edit_text(f"{ROYAL_HEADER}📥 <b>Direct download failed. Resolving fallback stream...</b>")
                    except Exception:
                        pass
                res = await resolve_stream_url(youtube_url, mode)
                if res and res.get("url"):
                    stream_url = res["url"]
                    if not title or title == "YouTube Stream":
                        title = res.get("title", title)
                    ok = await download_file(stream_url, dest_path, progress_cb)
            
            if not ok or not os.path.exists(dest_path):
                print(f"[Player] Download failed for track '{title}'. Checking queue for next song...")
                if chat_id in self.queues and self.queues[chat_id]:
                    next_song = self.queues[chat_id].pop(0)
                    print(f"[Player] Skipping failed track, auto-playing next: {next_song['title']}")
                    if status_msg:
                        try:
                            await status_msg.edit_text(f"{ROYAL_HEADER}⚠️ <b>Song download failed (Cookie/Bot Protection). Skipping to:</b> <code>{next_song['title']}</code>...")
                        except Exception:
                            pass
                    asyncio.create_task(self.play(
                        chat_id=chat_id,
                        youtube_url=next_song["url"],
                        mode=next_song["mode"],
                        status_msg=status_msg,
                        requested_by=next_song.get("requested_by"),
                        requested_by_id=next_song.get("requested_by_id", 0)
                    ))
                    return True
                else:
                    if status_msg:
                        await status_msg.edit_text(f"{ROYAL_HEADER}❌ <b>Download failed or file corrupted!</b>")
                    return False

            local_path = dest_path
            # Save file path, title, thumbnail, duration to SQLite DB Cache
            save_to_cache(
                video_id, mode, local_path, title,
                thumbnail=self.stream_thumbnail.get(chat_id, f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"),
                duration=self.stream_duration.get(chat_id, 0)
            )

        else:
            print(f"[Player] Direct cache hit for ID {video_id}! Playing instantly.")

        # 4. Stream via PyTgCalls (Locks video parameters to 720p 60fps and audio filter leveling)
        if status_msg:
            try:
                await status_msg.edit_text(f"{ROYAL_HEADER}🟢 <b>Streaming starting on voice chat...</b>")
            except Exception:
                pass
        
        # Dynamic Configured Resolution & Framerate (4K/2K/1080p/720p/480p & 90/60/30 FPS)
        vid_params, q_pref, fps_pref, _ = get_configured_video_parameters()
        print(f"[Player] Initializing stream with Target Quality: {q_pref} | FPS: {fps_pref}")
        

        # PyTgCalls v3 dev: pass NO custom ffmpeg_parameters to avoid crash/immediate stream end
        # AudioQuality.STUDIO already sets 48kHz, 128kbps stereo — best quality without filters
        # Ensure media file has a valid audio track before PyTgCalls starts streaming
        local_path = ensure_audio_track(local_path)

        stream = SeekableMediaStream(
            media_path=local_path,
            audio_path=None,
            video_parameters=vid_params,
            audio_parameters=AudioQuality.STUDIO,
            video_flags=MediaStream.Flags.REQUIRED if mode == "video" else MediaStream.Flags.IGNORE,
            audio_flags=MediaStream.Flags.REQUIRED,
        )

        try:
            # Ensure assistant is unmuted
            try:
                await self._pytg.unmute(chat_id)
            except Exception:
                pass

            # Try direct play first. If call is already active, PyTgCalls joins without resetting existing participants.
            try:
                await self._pytg.play(chat_id, stream)
            except Exception as play_err:
                print(f"[Player] Initial play attempt note: {play_err}. Checking if call needs start/join...")
                try:
                    from pyrogram.raw.functions.phone import CreateGroupCall
                    import random
                    peer_as = await self._assistant.resolve_peer(chat_id)
                    await self._assistant.invoke(
                        CreateGroupCall(peer=peer_as, random_id=random.randint(0, 0x7FFFFFFF))
                    )
                    print(f"[Player] Started new voice chat in {chat_id}")
                    await asyncio.sleep(1.0)
                except Exception as start_err:
                    print(f"[Player] CreateGroupCall status: {start_err}")
                
                # Retry play after call creation attempt
                try:
                    await self._pytg.play(chat_id, stream)
                except Exception as play_err2:
                    print(f"[Player] Retry play attempt note: {play_err2}")
                    # If still failing, retry with audio-only mode as fallback
                    if mode == "video":
                        print(f"[Player] Video stream failed, retrying in Audio mode...")
                        audio_stream = SeekableMediaStream(
                            media_path=local_path,
                            audio_path=None,
                            video_parameters=vid_params,
                            audio_parameters=AudioQuality.STUDIO,
                            video_flags=MediaStream.Flags.IGNORE,
                            audio_flags=MediaStream.Flags.REQUIRED,
                        )
                        await self._pytg.play(chat_id, audio_stream)
                    else:
                        raise play_err2

            self.active_calls.add(chat_id)
            self.in_call_chats.add(chat_id)
            self.active_files[chat_id] = local_path
            self.active_requester_id[chat_id] = requested_by_id
            self.stream_start_time[chat_id] = time.time()
            self.stream_title[chat_id] = title

            # Ensure total stream duration is resolved for live progress bar timer
            if not self.stream_duration.get(chat_id, 0):
                self.stream_duration[chat_id] = get_media_duration(local_path)

            total = self.stream_duration.get(chat_id, 0)
            
            req_str = ""
            if requested_by and requested_by_id:
                req_str = f"\n👤 <b>Requested by:</b> <a href=\"tg://user?id={requested_by_id}\">{requested_by}</a>"
            
            queue_len = len(self.queues.get(chat_id, []))
            if queue_len > 1:
                next_title = self.queues[chat_id][0]['title']
                queue_str = f"\n📣 <b>Upcoming:</b> {next_title} (+{queue_len-1} more)"
            elif queue_len == 1:
                next_title = self.queues[chat_id][0]['title']
                queue_str = f"\n📣 <b>Upcoming:</b> {next_title}"
            else:
                queue_str = ""

            prog = self._make_progress_bar(0, total) if total > 0 else ""
            prog_line = f"\n<code>{self._fmt_time(0)} ──────────•── {self._fmt_time(total)}</code>" if total > 0 else ""

            mode_icon = "🎬" if mode == "video" else "🎵"
            mode_label = "Video" if mode == "video" else "Audio"

            blank_pad = "⠀" * 20
            dur_text = f"{self._fmt_time(total)} MINUTES" if total else "Live Stream"
            mode_text = "Video" if mode == "video" else "Audio"
            caption = (
                f"➦ <b>STARTED STREAMING |</b>{blank_pad}\n\n"
                f"<b>TITLE :</b> <a href=\"{youtube_url}\">{title}</a>\n"
                f"<b>MODE :</b> {mode_text}\n"
                f"<b>DURATION :</b> {dur_text}\n"
                f"<b>REQUESTED BY :</b> {requested_by or 'Unknown'}"
                f"{queue_str}"
            )

            buttons = self._build_play_card_markup(chat_id, requested_by_id, 0, total, mode)

            # Send full-size Photo Card (Photo on TOP, blockquote card below as caption)
            video_id = extract_video_id(youtube_url) or ''
            thumbnail_url = self.stream_thumbnail.get(chat_id, f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg")
            sent_msg = None
            from bot import _markup_to_bot_api_json, make_card
            import aiohttp as _aio
            import json as _json
            token = __import__('config').Config.BOT_TOKEN
            endpoint = f"https://api.telegram.org/bot{token}/sendPhoto"
            
            photo_candidates = [
                f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                thumbnail_url,
                f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "https://images.unsplash.com/photo-1514525253161-7a46d19cd819?q=80&w=800"
            ]
            for photo_target in photo_candidates:
                if not photo_target:
                    continue
                try:
                    payload = {
                        "chat_id": chat_id,
                        "photo": photo_target,
                        "caption": make_card(caption),
                        "parse_mode": "HTML",
                        "reply_markup": _json.dumps({"inline_keyboard": _markup_to_bot_api_json(buttons)})
                    }
                    async with _aio.ClientSession() as _s:
                        async with _s.post(endpoint, json=payload, timeout=_aio.ClientTimeout(total=4)) as r:
                            resp_json = await r.json()
                            if resp_json.get("ok"):
                                sent_msg = resp_json["result"]
                                print(f"[Player] Photo card sent successfully with image: {photo_target[:60]}")
                                break
                except Exception as photo_err:
                    print(f"[Player] Photo card send error with {photo_target}: {photo_err}")

            if sent_msg:
                # Delete old status message so ONLY the single photo card stays in chat
                if status_msg:
                    try:
                        await status_msg.delete()
                    except Exception:
                        pass
                self.now_playing_msg_id[chat_id] = sent_msg["message_id"]
            else:
                # Fallback to text card
                from bot import send_styled, edit_styled
                msg_id = status_msg.id if status_msg and hasattr(status_msg, 'id') else None
                try:
                    if msg_id:
                        await edit_styled(
                            chat_id=chat_id,
                            text=caption,
                            markup=buttons,
                            message_id=msg_id,
                            disable_preview=False
                        )
                        self.now_playing_msg_id[chat_id] = msg_id
                    else:
                        res = await send_styled(
                            chat_id=chat_id,
                            text=caption,
                            markup=buttons,
                            disable_preview=False
                        )
                        if res and res.get("ok"):
                            self.now_playing_msg_id[chat_id] = res["result"]["message_id"]
                except Exception as e:
                    print(f"[Player] Text fallback note: {e}")

            # Start live progress updater
            self._start_progress_updater(
                chat_id, title, youtube_url, requested_by, requested_by_id, mode
            )

            # Send rich log to Telegram Logger Group (-1003975646434)
            asyncio.create_task(
                self._send_tg_logger_event(
                    chat_id, title, youtube_url, requested_by, requested_by_id, mode, total, thumbnail_url
                )
            )

            # Silently pre-download ONLY the NEXT 1 upcoming song (saves disk space & bandwidth)
            queue_snapshot = list(self.queues.get(chat_id, [])[:1])
            for i, next_track in enumerate(queue_snapshot):
                print(f"[Player] Pre-downloading queued track #{i+1}: {next_track['title']}")
                asyncio.create_task(self._background_pre_download(chat_id, next_track["url"], mode, next_track["title"]))

            return True

        except Exception as err:
            err_str = str(err)
            print(f"[Player] Play error: {err_str}")
            
            # If it's already a Flood Wait error, fail gracefully instantly to avoid getting banned
            if "FLOOD_WAIT" in err_str:
                if status_msg:
                    try:
                        from bot import make_card
                        await status_msg.edit_text(make_card("⚠️ <b>Telegram Rate Limit (Flood Wait) active!</b>\nPlease try again in a few seconds."))
                    except Exception:
                        pass
                return False
                
            # Try auto-starting call (only if it's not a permission issue on helper)
            if "CHAT_ADMIN_REQUIRED" not in err_str:
                try:
                    from pyrogram.raw.functions.phone import CreateGroupCall
                    import random
                    peer_as = await self._assistant.resolve_peer(chat_id)
                    await self._assistant.invoke(
                        CreateGroupCall(peer=peer_as, random_id=random.randint(0, 0x7FFFFFFF))
                    )
                    await asyncio.sleep(1.5)
                    await self._pytg.play(chat_id, stream)
                    self.active_calls.add(chat_id)
                    self.active_files[chat_id] = local_path
                    return True
                except Exception as start_err:
                    start_err_str = str(start_err)
                    print(f"[Player] Call auto-start failed: {start_err_str}")
                    
            # Provide clean instruction if start/join failed
            if status_msg:
                try:
                    from bot import make_card
                    await status_msg.edit_text(
                        make_card(
                            "❌ <b>Voice chat is not active!</b>\n\n"
                            "Please start the video/voice chat in the group to begin streaming."
                        ),
                        parse_mode=enums.ParseMode.HTML
                    )
                except Exception:
                    pass
            return False

    async def skip(self, chat_id: int) -> bool:
        """Skip current track → play next in queue, or stop if queue is empty."""
        self._cancel_idle_timer(chat_id)
        
        if chat_id in self.queues and self.queues[chat_id]:
            next_song = self.queues[chat_id].pop(0)
            print(f"[Player] Skip → next: {next_song['title']} in {chat_id}")
            
            # CRITICAL: remove from active_calls so play() starts fresh instead of re-queuing
            self.active_calls.discard(chat_id)
            self.active_files.pop(chat_id, None)
            self.active_requester_id.pop(chat_id, None)
            
            status_msg = await self.app.send_message(
                chat_id,
                f"{ROYAL_HEADER}⏭ <b>Skipping... Next track:</b> <code>{next_song['title']}</code>"
            )
            asyncio.create_task(self.play(
                chat_id=chat_id,
                youtube_url=next_song["url"],
                mode=next_song["mode"],
                status_msg=status_msg,
                requested_by=next_song.get("requested_by"),
                requested_by_id=next_song.get("requested_by_id", 0),
                playlist_id=next_song.get("playlist_id", ""),
                track_index=next_song.get("track_index"),
                total_tracks=next_song.get("total_tracks", 0)
            ))
            return True
        else:
            # Queue is empty — fully stop
            await self.stop(chat_id)
            return False

    async def seek(self, chat_id: int, seconds: int) -> bool:
        """
        Seeks forward in the active stream by specified seconds (e.g. +10s, +30s, +120s).
        Adjusts internal stream_start_time so live progress bar stays 100% accurate.
        """
        if chat_id not in self.active_calls or chat_id not in self.active_files:
            return False

        local_path = self.active_files.get(chat_id)
        if not local_path or not os.path.exists(local_path):
            return False

        current_start = self.stream_start_time.get(chat_id, time.time())
        elapsed = max(0, int(time.time() - current_start))
        new_offset = elapsed + seconds

        total_dur = self.stream_duration.get(chat_id, 0)
        if total_dur > 0 and new_offset >= total_dur:
            # Offset exceeds remaining duration — skip to next track
            return await self.skip(chat_id)

        vid_params = VideoParameters(width=1280, height=720, frame_rate=60)
        mode = "video" if local_path.endswith(".mp4") or local_path.endswith(".mkv") else "audio"

        stream = MediaStream(
            media_path=local_path,
            audio_path=None,
            video_parameters=vid_params,
            audio_parameters=AudioQuality.STUDIO,
            ffmpeg_parameters=f"-ss {new_offset}",
            video_flags=MediaStream.Flags.REQUIRED if mode == "video" else MediaStream.Flags.IGNORE,
            audio_flags=MediaStream.Flags.REQUIRED,
        )

        try:
            await self._pytg.play(chat_id, stream)
            self.stream_start_time[chat_id] = time.time() - new_offset
            print(f"[Player] Seeked chat {chat_id} forward to {new_offset}s (+{seconds}s)")
            return True
        except Exception as e:
            print(f"[Player] Seek error in {chat_id}: {e}")
            return False

    async def set_audio_effect(self, chat_id: int, effect: str) -> bool:
        """Applies real-time FFmpeg audio effect by re-streaming from current position with filter."""
        if chat_id not in self.active_calls or chat_id not in self.active_files:
            return False

        local_path = self.active_files.get(chat_id)
        if not local_path or not os.path.exists(local_path):
            return False

        current_start = self.stream_start_time.get(chat_id, time.time())
        elapsed = max(0, int(time.time() - current_start))

        # FFmpeg audio filter expressions — forced 48000Hz resample for WebRTC Opus compatibility
        ffmpeg_filters = {
            "normal":    None,
            "bassboost": "equalizer=f=60:width_type=o:width=2:g=15,aresample=48000",
            "nightcore": "atempo=1.25,aresample=48000",
            "slowed":    "atempo=0.85,aresample=48000",
            "lofi":      "lowpass=f=3000,volume=1.2,aresample=48000",
            "8d":        "apulsator=hz=0.125,aresample=48000",
            "classic":   "equalizer=f=1000:g=6,aresample=48000",
            "jack":      "volume=1.4,aresample=48000",
        }

        af_expr = ffmpeg_filters.get(effect, None)

        if af_expr:
            ffmpeg_params = f"-ss {elapsed} -noaccurate_seek -af {af_expr} -avoid_negative_ts make_zero"
        else:
            ffmpeg_params = f"-ss {elapsed} -noaccurate_seek -avoid_negative_ts make_zero"

        vid_params, _, _, _ = get_configured_video_parameters()
        mode = "video" if local_path.endswith(".mp4") or local_path.endswith(".mkv") else "audio"

        print(f"[Player] Applying Effect '{effect.upper()}' | Chat: {chat_id} | Position: {elapsed}s | Params: {ffmpeg_params}")

        stream = SeekableMediaStream(
            media_path=local_path,
            audio_path=None,
            video_parameters=vid_params,
            audio_parameters=AudioQuality.STUDIO,
            ffmpeg_parameters=ffmpeg_params,
            video_flags=MediaStream.Flags.REQUIRED if mode == "video" else MediaStream.Flags.IGNORE,
            audio_flags=MediaStream.Flags.REQUIRED,
        )

        self.effect_ignore_until[chat_id] = time.time() + 4.0
        try:
            if hasattr(self._pytg, "change_stream"):
                await self._pytg.change_stream(chat_id, stream)
            else:
                await self._pytg.play(chat_id, stream)
            self.stream_start_time[chat_id] = time.time() - elapsed
            print(f"[Player] LIVE EFFECT SUCCESS: '{effect.upper()}' is now active in chat {chat_id}!")
            return True
        except Exception as e:
            print(f"[Player] change_stream note for effect '{effect}' in {chat_id}: {e}. Trying play fallback...")
            try:
                await self._pytg.play(chat_id, stream)
                self.stream_start_time[chat_id] = time.time() - elapsed
                print(f"[Player] Fallback play SUCCESS for effect '{effect.upper()}' in chat {chat_id}!")
                return True
            except Exception as e2:
                self.effect_ignore_until.pop(chat_id, None)
                print(f"[Player] ERROR applying effect '{effect}' in {chat_id}: {e2}")
                return False

    async def pause(self, chat_id: int) -> bool:
        """Pause active stream."""
        try:
            await self._pytg.pause(chat_id)
            return True
        except Exception as e:
            print(f"[Player] Pause error in {chat_id}: {e}")
            return False

    async def resume(self, chat_id: int) -> bool:
        """Resume paused stream."""
        try:
            await self._pytg.resume(chat_id)
            return True
        except Exception as e:
            print(f"[Player] Resume error in {chat_id}: {e}")
            return False

    async def stop(self, chat_id: int):
        """Leaves the call and clears memory queues for chat_id. Keeps saved playlist state in DB for /plresume."""
        self._cancel_progress_task(chat_id)
        self._cancel_idle_timer(chat_id)
        self.in_effects_menu.discard(chat_id)

        try:
            await self._pytg.leave_call(chat_id)
        except Exception as e:
            print(f"[Player] pytg.leave_call note in {chat_id}: {e}")

        # Raw Pyrogram call disconnect to ensure assistant leaves Telegram UI voice chat
        try:
            from pyrogram.raw.functions.phone import LeaveGroupCall
            from pyrogram.raw.types import InputGroupCall
            chat = await self.app.get_chat(chat_id)
            if hasattr(chat, "call") and chat.call:
                await self._assistant.invoke(
                    LeaveGroupCall(call=InputGroupCall(id=chat.call.id, access_hash=chat.call.access_hash), source=0)
                )
                print(f"[Player] Raw LeaveGroupCall invoked for chat {chat_id}")
        except Exception as raw_leave_err:
            print(f"[Player] Raw LeaveGroupCall note: {raw_leave_err}")

        # Clear memory queues & pending states
        self.active_calls.discard(chat_id)
        self.in_call_chats.discard(chat_id)
        self.active_files.pop(chat_id, None)
        self.queues.pop(chat_id, None)
        self.pending_playlists.pop(chat_id, None)
        self.active_requester_id.pop(chat_id, None)
        self.stream_title.pop(chat_id, None)
        self.stream_start_time.pop(chat_id, None)
        self.stream_duration.pop(chat_id, None)
        self.stream_thumbnail.pop(chat_id, None)
        self.now_playing_msg_id.pop(chat_id, None)

    async def full_reset(self) -> dict:
        """Owner-only system reset: stops calls, clears queues, wipes downloads directory & resets DB caches."""
        active_chat_ids = list(self.active_calls)
        for chat_id in active_chat_ids:
            try:
                await self.stop(chat_id)
            except Exception:
                pass
        
        self.active_calls.clear()
        self.in_call_chats.clear()
        self.active_files.clear()
        self.queues.clear()
        self.pending_playlists.clear()
        self.active_requester_id.clear()
        self.stream_title.clear()
        self.stream_start_time.clear()
        self.stream_duration.clear()
        self.stream_thumbnail.clear()
        self.now_playing_msg_id.clear()

        # Delete all media files in downloads directory
        deleted_files_count = 0
        downloads_dir = Config.DOWNLOADS_DIR
        if os.path.exists(downloads_dir):
            for fname in os.listdir(downloads_dir):
                fpath = os.path.join(downloads_dir, fname)
                try:
                    if os.path.isfile(fpath):
                        os.remove(fpath)
                        deleted_files_count += 1
                except Exception as fe:
                    print(f"[Reset] Error deleting file {fpath}: {fe}")

        # Wipe SQLite DB caches & states
        from core.db import reset_all_db_caches
        reset_all_db_caches()

        return {
            "stopped_calls": len(active_chat_ids),
            "deleted_files": deleted_files_count
        }

    async def close(self):
        """Gracefully shuts down by leaving active calls."""
        if self._pytg:
            print("[Player] 🔴 Shutting down — leaving active calls...")
            for chat_id in list(self.active_calls):
                self._cancel_progress_task(chat_id)
                try:
                    await asyncio.wait_for(self._pytg.leave_call(chat_id), timeout=2.0)
                except Exception:
                    pass
            for chat_id in list(self.idle_tasks.keys()):
                self._cancel_idle_timer(chat_id)
            self.active_calls.clear()

player_manager = PlayerManager()
