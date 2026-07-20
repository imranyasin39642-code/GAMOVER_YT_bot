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
    
    for attempt in range(1, max_retries + 1):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
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


async def download_song_ytdlp(youtube_url: str, dest_path: str, mode: str, progress_callback=None) -> bool:
    """Asynchronously download and merge video + audio tracks natively using yt-dlp with multi-client bot bypass."""
    import yt_dlp
    import glob
    import shutil
    
    loop = asyncio.get_running_loop()
    last_update = [time.time()]
    
    def hook(d):
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            pct = int((downloaded / total) * 100) if total > 0 else 0
            
            now = time.time()
            if now - last_update[0] >= 3.0:
                if progress_callback:
                    asyncio.run_coroutine_threadsafe(
                        progress_callback(pct, downloaded, total, last_update[0]),
                        loop
                    )
                last_update[0] = now

    base_path = dest_path.rsplit('.', 1)[0]
    outtmpl = base_path + '.%(ext)s'
    
    if mode == "video":
        format_spec = "bestvideo[height<=720][fps<=60]+bestaudio/best[height<=720]/best"
    else:
        format_spec = "bestaudio/best"

    clients_to_try = ["android", "ios", "mweb", "web_embedded"]

    # 1. Clean up any leftover temp files or target files from previous attempts
    for f in glob.glob(base_path + "*"):
        try:
            os.remove(f)
        except Exception:
            pass

    for client_name in clients_to_try:
        ydl_opts = {
            'format': format_spec,
            'outtmpl': outtmpl,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'progress_hooks': [hook],
            'merge_output_format': 'mp4',
            'extractor_args': {
                'youtube': {
                    'player_client': [client_name]
                }
            }
        }
        
        def run():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([youtube_url])

        try:
            await loop.run_in_executor(None, run)
            
            # Check and rename output extension formats if merged to something else
            for ext in ['.mp4', '.mkv', '.webm']:
                p = base_path + ext
                if os.path.exists(p):
                    if p != dest_path:
                        if os.path.exists(dest_path):
                            try:
                                os.remove(dest_path)
                            except Exception:
                                pass
                        shutil.move(p, dest_path)
                    return True
        except Exception as e:
            print(f"[Player/ytdlp-downloader] Client '{client_name}' failed: {e}")
            # Clean up temp files before trying next client
            for f in glob.glob(base_path + "*.temp.*") + glob.glob(base_path + "*.part"):
                try:
                    os.remove(f)
                except Exception:
                    pass
            continue

    return False


class SeekableMediaStream(MediaStream):
    async def check_stream(self):
        import pytgcalls.types.stream.media_stream as ms_mod
        orig_check = ms_mod.check_stream
        
        async def mock_check(ffmpeg_params, path, stream_params, before_cmds=None, headers=None):
            clean_params = None
            if ffmpeg_params:
                import shlex
                parts = shlex.split(ffmpeg_params)
                new_parts = []
                skip = False
                for part in parts:
                    if skip:
                        skip = False
                        continue
                    if part == "-ss":
                        skip = True
                        continue
                    if part == "-re":
                        continue
                    new_parts.append(part)
                clean_params = " ".join(new_parts) if new_parts else None
            return await orig_check(clean_params, path, stream_params, before_cmds, headers)
            
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
        self.active_files: dict[int, str] = {}         # chat_id -> local_file_path
        self.queues: dict[int, list[dict]] = {}        # chat_id -> list of queued songs
        self.idle_tasks: dict[int, asyncio.Task] = {}  # chat_id -> idle timer task
        self.active_requester_id: dict[int, int] = {}  # chat_id -> requester user_id
        
        # Progress bar / Now Playing state
        self.stream_start_time: dict[int, float] = {}  # chat_id -> unix timestamp when play started
        self.stream_duration: dict[int, int] = {}      # chat_id -> total duration in seconds
        self.stream_thumbnail: dict[int, str] = {}     # chat_id -> thumbnail URL
        self.now_playing_msg_id: dict[int, int] = {}   # chat_id -> Telegram message_id of now-playing card
        self.progress_tasks: dict[int, asyncio.Task] = {}  # chat_id -> progress updater task

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
    def _make_progress_bar(elapsed: int, total: int, width: int = 18) -> str:
        """Build a text progress bar like: 1:23 ━━━━━━●───────── 3:45"""
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

    def _start_progress_updater(self, chat_id: int, title: str, youtube_url: str,
                                 requested_by: str, requested_by_id: int, mode: str):
        """Launch a background task that edits the Now Playing caption every 10 seconds."""
        self._cancel_progress_task(chat_id)

        async def _updater():
            from bot import edit_styled
            await asyncio.sleep(10)  # first update after 10s
            while chat_id in self.active_calls:
                try:
                    start = self.stream_start_time.get(chat_id, time.time())
                    total = self.stream_duration.get(chat_id, 0)
                    elapsed = int(time.time() - start)
                    
                    req_str = ""
                    if requested_by and requested_by_id:
                        req_str = f"\n👤 <b>Requested by:</b> <a href=\"tg://user?id={requested_by_id}\">{requested_by}</a>"

                    prog = self._make_progress_bar(elapsed, total) if total > 0 else ""
                    prog_line = f"\n\n<code>{prog}</code>" if prog else ""

                    caption = (
                        f"⚡ <b>Started Streaming:</b>\n"
                        f"\n🎬 <b>Title:</b> <a href=\"{youtube_url}\">{title}</a>"
                        f"\n⏱ <b>Duration:</b> {self._fmt_time(total) if total else 'Live'}"
                        f"{req_str}"
                        f"{prog_line}"
                    )

                    msg_id = self.now_playing_msg_id.get(chat_id)
                    if msg_id:
                        buttons = InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton("⏭ SKIP", callback_data=f"play_skip|{chat_id}|{requested_by_id}", style="primary"),
                                InlineKeyboardButton("⏹ STOP", callback_data=f"play_stop|{chat_id}|{requested_by_id}", style="danger"),
                            ],
                            [
                                InlineKeyboardButton("🗑 Close", callback_data="play_close", style="danger")
                            ]
                        ])
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
                    print(f"[ProgressBar] Update error in {chat_id}: {e}")
                await asyncio.sleep(10)

        self.progress_tasks[chat_id] = asyncio.create_task(_updater())

    def _start_idle_timer(self, chat_id: int):
        self._cancel_idle_timer(chat_id)
        
        async def idle_timer():
            await asyncio.sleep(300) # 5 minutes
            print(f"[Player] Idle timeout triggered in chat {chat_id}")
            try:
                await self.app.send_message(chat_id, f"{ROYAL_HEADER}⏹ <b>5 minutes idle timeout! Leaving voice chat... Bye!</b>")
            except:
                pass
            await self.stop(chat_id)
            
        self.idle_tasks[chat_id] = asyncio.create_task(idle_timer())
        print(f"[Player] Started 5-minute idle timer in chat {chat_id}")

    def _cancel_idle_timer(self, chat_id: int):
        task = self.idle_tasks.pop(chat_id, None)
        if task:
            task.cancel()
            print(f"[Player] Cancelled idle timer in chat {chat_id}")

    async def init(self, assistant: Client, bot: Client):
        self._assistant = assistant
        self.app = bot
        self._pytg = PyTgCalls(assistant)

        # Stream End Handler
        @self._pytg.on_update(filters.stream_end())
        async def on_stream_end(_, update):
            chat_id = update.chat_id
            
            # De-duplicate: only process AUDIO end (skip VIDEO end)
            type_str = str(getattr(update, "stream_type", "")).upper()
            type_val = getattr(getattr(update, "stream_type", None), "value", None)
            if "VIDEO" in type_str or type_val == 2:
                return

            print(f"[Player] Stream ended in chat {chat_id}")
            
            # ─────────────────────────────────────────────────────────────
            # CRITICAL: Remove from active_calls BEFORE calling play() so
            # that play() doesn't think something is already streaming and
            # re-add the next song to the queue instead of playing it.
            # ─────────────────────────────────────────────────────────────
            self.active_calls.discard(chat_id)
            self.active_files.pop(chat_id, None)
            self.active_requester_id.pop(chat_id, None)
            
            # Queue management: Play next song if available
            if chat_id in self.queues and self.queues[chat_id]:
                next_song = self.queues[chat_id].pop(0)
                print(f"[Player] Auto-playing next queued track: {next_song['title']}")
                
                status_msg = await self.app.send_message(
                    chat_id,
                    f"{ROYAL_HEADER}⏭ <b>Next track loading:</b> <code>{next_song['title']}</code>..."
                )
                
                asyncio.create_task(self.play(chat_id, next_song["url"], next_song["mode"], status_msg, next_song.get("requested_by"), next_song.get("requested_by_id", 0)))
            else:
                # Queue empty — start 5-min idle timer
                try:
                    await self.app.send_message(chat_id, f"{ROYAL_HEADER}⏹ <b>Playback ended! Queue khatam ho gayi.</b>")
                except:
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
            
        filename = f"{video_id}_{mode}.mp4"
        dest_path = os.path.join(Config.DOWNLOADS_DIR, filename)
        
        # Download silently in the background
        ok = await download_song_ytdlp(youtube_url, dest_path, mode, progress_callback=None)
        if ok and os.path.exists(dest_path):
            save_to_cache(video_id, mode, dest_path, title)

    async def play(self, chat_id: int, youtube_url: str, mode: str = "video", status_msg = None, requested_by: str = None, requested_by_id: int = 0) -> bool:
        # ── Auto-search if user gave a text query instead of a URL ──────────
        if not is_youtube_url(youtube_url):
            query = youtube_url.strip()
            if status_msg:
                await status_msg.edit_text(f"{ROYAL_HEADER}🔍 <b>Searching YouTube for:</b> <code>{query}</code>...")
            result = await search_youtube(query)
            if not result:
                if status_msg:
                    await status_msg.edit_text(f"{ROYAL_HEADER}❌ <b>YouTube par koi result nahi mila!</b>\nKripya doosra query try karein.")
                return False
            youtube_url = result["url"]
            print(f"[Player] Search resolved to: {youtube_url}")

        video_id = extract_video_id(youtube_url)
        if not video_id:
            if status_msg:
                await status_msg.edit_text(f"{ROYAL_HEADER}❌ <b>Aapka YouTube Link invalid hai!</b>")
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
            await status_msg.edit_text(
                f"{ROYAL_HEADER}"
                f"<b>Upcoming Track: #{pos}</b>\n\n"
                f"<b>Title:</b> <a href=\"{youtube_url}\">{q_title}</a>\n"
                f"{req_by_str}",
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )
            
            # Pre-download in the background to ensure instant play when current track ends
            asyncio.create_task(self._background_pre_download(chat_id, youtube_url, mode, q_title))
            return True

        # Cancel any active idle timer since we are about to start a new stream
        self._cancel_idle_timer(chat_id)

        # 1. Check local DB cache
        cached = get_cached_item(video_id, mode)
        local_path = None
        title = "YouTube Stream"

        if cached:
            local_path = cached["file_path"]
            title = cached["title"]

        if not local_path:
            # 2. Resolve link via Web Scraper chain to fetch Title first
            await status_msg.edit_text(f"{ROYAL_HEADER}🔍 <b>Searching database & resolving stream...</b>")
            res = await resolve_stream_url(youtube_url, mode)
            if res:
                title = res["title"]
                stream_url = res["url"]
                # Store thumbnail + duration for now-playing card
                thumb = res.get("thumbnail") or f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                self.stream_thumbnail[chat_id] = thumb
                dur = res.get("duration", 0)
                if dur:
                    self.stream_duration[chat_id] = int(dur)
            else:
                title = "YouTube Stream"
                stream_url = None
                # Fallback thumbnail from video_id
                self.stream_thumbnail[chat_id] = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

            filename = f"{video_id}_{mode}.mp4"
            dest_path = os.path.join(Config.DOWNLOADS_DIR, filename)

            # 3. Download target file with progress updates
            await status_msg.edit_text(f"{ROYAL_HEADER}📥 <b>Starting high-speed download...</b>")
            
            async def progress_cb(pct, down, tot, start):
                elapsed = time.time() - start
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

            # Try native yt-dlp first to guarantee video + audio are merged together
            print(f"[Player] Initiating native download for webpage_url: {youtube_url}")
            ok = await download_song_ytdlp(youtube_url, dest_path, mode, progress_cb)
            
            if not ok or not os.path.exists(dest_path):
                # Fallback to direct HTTP URL download if native download fails
                if stream_url:
                    print(f"[Player] Native download failed. Falling back to direct URL HTTP download: {stream_url[:60]}")
                    await status_msg.edit_text(f"{ROYAL_HEADER}📥 <b>Native download failed. Trying direct link fallback...</b>")
                    ok = await download_file(stream_url, dest_path, progress_cb)
            
            if not ok or not os.path.exists(dest_path):
                await status_msg.edit_text(f"{ROYAL_HEADER}❌ <b>Download failed or file corrupted!</b>")
                return False

            local_path = dest_path
            # Save file path to SQLite DB Cache
            save_to_cache(video_id, mode, local_path, title)

        else:
            print(f"[Player] Direct cache hit for ID {video_id}! Playing instantly.")

        # 4. Stream via PyTgCalls (Locks video parameters to 720p 60fps and audio filter leveling)
        await status_msg.edit_text(f"{ROYAL_HEADER}🟢 <b>Streaming starting on voice chat...</b>")
        
        # 720p 60fps
        vid_params = VideoParameters(width=1280, height=720, frame_rate=60)
        
        if mode == "audio":
            audio_filter = (
                '-af "bass=g=4:f=100:w=0.5,'
                'acompressor=threshold=0.5:ratio=3:attack=8:release=80:makeup=1.5,'
                'alimiter=limit=0.85:level=1,'
                'aresample=48000"'
            )
            base_flags = "--base ---start -analyzeduration 2M -probesize 2M -threads 1 -thread_queue_size 256 "
            ffmpeg_params = f"{base_flags}--audio ---mid {audio_filter}"
        else:
            audio_filter = (
                '-af "equalizer=f=60:width_type=h:width=50:g=3,'
                'acompressor=threshold=0.15:ratio=4:attack=5:release=100:makeup=2.0,'
                'volume=1.8,alimiter=limit=0.90,'
                'aresample=async=1:min_comp=0.001:max_soft_comp=5"'
            )
            base_flags = "--base ---start -re -fflags +genpts -analyzeduration 10M -probesize 10M -threads 4 -thread_queue_size 2048 -vsync cfr "
            ffmpeg_params = f"{base_flags}--audio ---mid {audio_filter} -max_muxing_queue_size 2048"

        stream = SeekableMediaStream(
            media_path=local_path,
            audio_path=None,
            video_parameters=vid_params,
            audio_parameters=AudioQuality.HIGH,
            video_flags=MediaStream.Flags.REQUIRED if mode == "video" else MediaStream.Flags.IGNORE,
            audio_flags=MediaStream.Flags.REQUIRED,
            ffmpeg_parameters=ffmpeg_params
        )

        try:
            # Ensure assistant is in the voice call
            try:
                await self._pytg.unmute(chat_id)
            except Exception:
                pass

            await self._pytg.play(chat_id, stream)
            self.active_calls.add(chat_id)
            self.active_files[chat_id] = local_path
            self.active_requester_id[chat_id] = requested_by_id
            self.stream_start_time[chat_id] = time.time()

            # Build now-playing caption
            req_str = ""
            if requested_by and requested_by_id:
                req_str = f"\n👤 <b>Requested by:</b> <a href=\"tg://user?id={requested_by_id}\">{requested_by}</a>"

            total = self.stream_duration.get(chat_id, 0)
            prog = self._make_progress_bar(0, total) if total > 0 else ""
            prog_line = f"\n\n<code>{prog}</code>" if prog else ""

            caption = (
                f"⚡ <b>Started Streaming:</b>\n"
                f"\n🎬 <b>Title:</b> <a href=\"{youtube_url}\">{title}</a>"
                f"\n⏱ <b>Duration:</b> {self._fmt_time(total) if total else 'Live'}"
                f"{req_str}"
                f"{prog_line}"
            )

            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("⏭ SKIP", callback_data=f"play_skip|{chat_id}|{requested_by_id}", style="primary"),
                    InlineKeyboardButton("⏹ STOP", callback_data=f"play_stop|{chat_id}|{requested_by_id}", style="danger"),
                ],
                [
                    InlineKeyboardButton("🗑 Close", callback_data="play_close", style="danger")
                ]
            ])

            # Send thumbnail photo + caption as now-playing card
            thumbnail_url = self.stream_thumbnail.get(chat_id, "")
            sent_msg = None
            if thumbnail_url:
                try:
                    from bot import _markup_to_bot_api_json
                    import aiohttp as _aio
                    import json as _json
                    token = __import__('config').Config.BOT_TOKEN
                    endpoint = f"https://api.telegram.org/bot{token}/sendPhoto"
                    payload = {
                        "chat_id": chat_id,
                        "photo": thumbnail_url,
                        "caption": caption,
                        "parse_mode": "HTML",
                        "reply_markup": _json.dumps({"inline_keyboard": _markup_to_bot_api_json(buttons)})
                    }
                    async with _aio.ClientSession() as _s:
                        async with _s.post(endpoint, json=payload, timeout=_aio.ClientTimeout(total=10)) as r:
                            resp_json = await r.json()
                            if resp_json.get("ok"):
                                sent_msg = resp_json["result"]
                except Exception as thumb_err:
                    print(f"[Player] Thumbnail send failed: {thumb_err}")

            if sent_msg:
                # Delete old status message, remember new msg id
                try:
                    await status_msg.delete()
                except Exception:
                    pass
                self.now_playing_msg_id[chat_id] = sent_msg["message_id"]
            else:
                # Fallback: edit status_msg as text
                from bot import send_styled
                await send_styled(
                    chat_id=chat_id,
                    text=caption,
                    markup=buttons,
                    message_id=status_msg.id
                )
                self.now_playing_msg_id[chat_id] = status_msg.id

            # Start live progress updater
            self._start_progress_updater(
                chat_id, title, youtube_url, requested_by, requested_by_id, mode
            )
            return True

        except Exception as err:
            print(f"[Player] Play error: {err}")
            # Try auto-starting call
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
                print(f"[Player] Call auto-start failed: {start_err}")
                await status_msg.edit_text(f"{ROYAL_HEADER}❌ <b>Voice chat active nahi hai! Pehle group call shuru karein.</b>")
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
                chat_id,
                next_song["url"],
                next_song["mode"],
                status_msg,
                next_song.get("requested_by"),
                next_song.get("requested_by_id", 0)
            ))
            return True
        else:
            # Queue is empty — fully stop
            await self.stop(chat_id)
            return False

    async def stop(self, chat_id: int):
        """Leaves the call and removes playback reference."""
        self._cancel_progress_task(chat_id)
        try:
            await self._pytg.leave_call(chat_id)
        except Exception:
            pass
        self.active_calls.discard(chat_id)
        self.active_files.pop(chat_id, None)
        self.queues.pop(chat_id, None)
        self.active_requester_id.pop(chat_id, None)
        self.stream_start_time.pop(chat_id, None)
        self.stream_duration.pop(chat_id, None)
        self.stream_thumbnail.pop(chat_id, None)
        self.now_playing_msg_id.pop(chat_id, None)

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
