import asyncio
import re
import json
import urllib.parse
from typing import Optional, Dict, List
import aiohttp
from core.dns_helper import get_doh_connector
from config import Config

def extract_video_id(url: str) -> Optional[str]:
    """Extract standard 11-char YouTube Video ID from any short or full link."""
    pattern = r'(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|embed/|v/)|youtu\.be/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def is_youtube_url(text: str) -> bool:
    """Return True if the text looks like a YouTube URL."""
    return bool(re.search(r'(?:youtube\.com|youtu\.be)', text, re.IGNORECASE))

async def search_youtube(query: str) -> Optional[Dict[str, str]]:
    """
    Search YouTube for a query using fast internal search + yt-dlp fallback.
    Returns a dict with 'video_id', 'url', 'title' of the top result in 1-2 seconds.
    """
    encoded = urllib.parse.quote(query)
    search_url = f"https://www.youtube.com/results?search_query={encoded}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        connector = get_doh_connector()
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(search_url, headers=headers, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    match = re.search(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
                    if match:
                        video_id = match.group(1)
                        title = "YouTube Video"
                        title_match = re.search(
                            r'"videoId":"' + re.escape(video_id) + r'".*?"title":\{"runs":\[\{"text":"([^"]+)"',
                            html
                        )
                        if title_match:
                            title = title_match.group(1)
                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                        print(f"[Search] Fast HTML Search Found: {title} → {video_url}")
                        return {"video_id": video_id, "url": video_url, "title": title}
    except Exception as e:
        print(f"[Search] Fast HTML search note: {e}")

    # Fast yt-dlp search fallback
    try:
        import yt_dlp
        ydl_opts = {
            'extract_flat': 'in_playlist',
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
        }
        loop = asyncio.get_event_loop()
        def _flat_search():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(f"ytsearch1:{query}", download=False)
        info = await loop.run_in_executor(None, _flat_search)
        if info and 'entries' in info and info['entries']:
            entry = info['entries'][0]
            v_id = entry.get('id')
            v_title = entry.get('title', query)
            if v_id:
                v_url = f"https://www.youtube.com/watch?v={v_id}"
                print(f"[Search] yt-dlp search found: {v_title} → {v_url}")
                return {"video_id": v_id, "url": v_url, "title": v_title}
    except Exception as e:
        print(f"[Search] yt-dlp search fallback error: {e}")

    return None


# Multi-layer scraper sequence for guaranteed 100% bypass of YouTube bot/cookie checks
SCRAPING_SITES = ["gameover_api", "ytdlp", "cobalt", "invidious", "piped", "yt5s", "yt1s", "y2mate", "9xbuddy", "ytmp3"]

async def resolve_stream_url(youtube_url: str, mode: str = "video") -> Optional[Dict[str, str]]:
    """
    Iterate over multi-layer scraper chain to resolve direct video or audio streams.
    Returns a dict with 'url', 'title', 'duration', 'thumbnail' on success, or None on failure.
    """
    video_id = extract_video_id(youtube_url)
    if not video_id:
        print(f"[Scraper] Invalid YouTube URL: {youtube_url}")
        return None

    clean_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"[Scraper] Resolving {mode} stream for YouTube ID: {video_id}")

    extractors = {
        "gameover_api": _extract_gameover_api,
        "ytdlp":        _extract_ytdlp_direct,
        "cobalt":       _extract_cobalt,
        "invidious":    _extract_invidious,
        "piped":        _extract_piped,
        "yt5s":         _extract_yt5s,
        "yt1s":         _extract_yt1s,
        "y2mate":       _extract_y2mate,
        "9xbuddy":      _extract_9xbuddy,
        "ytmp3":        _extract_ytmp3,
    }

    for site in SCRAPING_SITES:
        try:
            fn = extractors.get(site)
            if not fn:
                continue
            res = await fn(clean_url, mode)
            if res and res.get("url"):
                print(f"[Scraper] SUCCESS via {site}! Resolved Title: {res.get('title')}")
                return res
        except Exception as e:
            print(f"[Scraper] Site {site} failed for {video_id}: {e}")

    print(f"[Scraper] All scrapers failed to resolve {video_id}.")
    return None


# --- Scraper 0: GAMEOVER Local PC API Extractor (100% PURE LOCAL PC) ----
async def _extract_gameover_api(video_url: str, mode: str) -> Optional[Dict[str, str]]:
    """
    Primary Scraper: Hits Local PC API via Cloudflare Tunnel.
    - Zero cookies needed (Residential IP = No YouTube Ban).
    - Strictly returns JSON metadata + direct googlevideo stream links (~5KB).
    - NO nskmedia.net or cPanel fallback!
    """
    import os

    video_id = extract_video_id(video_url)
    if not video_id:
        return None

    local_api_url = os.getenv("LOCAL_API_URL", "").rstrip("/")
    local_api_key = os.getenv("LOCAL_API_KEY", "GAMEOVER_LOCAL_2026")

    if not local_api_url:
        print("[LocalAPI] WARNING: LOCAL_API_URL is not set in VPS .env!")
        return None

    targets = [
        f"{local_api_url}/api/extract?video_id={video_id}&api_key={local_api_key}",
        f"{local_api_url}/extract?video_id={video_id}&api_key={local_api_key}",
    ]

    for url in targets:
        print(f"[LocalAPI] Requesting stream JSON from Local PC: {url[:80]}...")
        try:
            timeout   = aiohttp.ClientTimeout(total=15)
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.get(url, allow_redirects=True) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == "success":
                            v_info = data.get("video_info") or data
                            stream_url = None

                            if mode == "audio":
                                raw = data.get("audio_only")
                                stream_url = raw if isinstance(raw, str) else (raw.get("url") if isinstance(raw, dict) else None)

                            if mode == "video" and data.get("streams"):
                                from core.db import get_setting
                                target_q   = get_setting("quality_pref") or "720p"
                                target_fps = get_setting("fps_pref") or "60"
                                streams_dict = data.get("streams", {})
                                preferred = [
                                    f"{target_q}{target_fps}", target_q,
                                    "1080p60", "1080p", "720p60", "720p",
                                    "2K60", "2K", "4K60", "4K", "480p", "360p"
                                ]
                                for pk in preferred:
                                    if pk in streams_dict:
                                        val = streams_dict[pk]
                                        stream_url = val if isinstance(val, str) else (
                                            val.get("video_url") or val.get("audio_url") or val.get("url")
                                        )
                                        if stream_url:
                                            print(f"[LocalAPI] Quality selected: {pk}")
                                            break

                            if not stream_url:
                                raw = data.get("best_merged")
                                stream_url = raw if isinstance(raw, str) else (
                                    (raw.get("url") or raw.get("video_url")) if isinstance(raw, dict) else None
                                )

                            if not stream_url and data.get("streams"):
                                for _, s_val in data["streams"].items():
                                    if isinstance(s_val, str):
                                        stream_url = s_val
                                        break
                                    elif isinstance(s_val, dict):
                                        stream_url = s_val.get("audio_url") or s_val.get("video_url") or s_val.get("url")
                                        if stream_url:
                                            break

                            if not stream_url:
                                stream_url = data.get("url")

                            if stream_url:
                                title     = data.get("title") or v_info.get("title") or "YouTube Stream"
                                duration  = data.get("duration") or v_info.get("duration") or 0
                                thumbnail = data.get("thumbnail") or v_info.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                                print(f"[LocalAPI] SUCCESS! Resolved JSON stream from Local PC: {title}")
                                return {
                                    "url":       stream_url,
                                    "title":     title,
                                    "duration":  duration,
                                    "thumbnail": thumbnail,
                                }
        except Exception as e:
            print(f"[LocalAPI] Local PC request failed: {e}")

    return None


# ─── Scraper 1: Programmatic yt-dlp Extractor (With Android/iOS Client Rotation) ──
async def _extract_ytdlp_direct(video_url: str, mode: str) -> Optional[Dict[str, str]]:
    """Programmatic yt-dlp extractor with Android/iOS/TV client rotation to bypass bot check."""
    import yt_dlp
    
    format_spec = "bestvideo[height<=480][fps<=60]+bestaudio/bestvideo[height<=480]+bestaudio/best[height<=480]/best" if mode == "video" else "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"

    def extract():
        ydl_opts = {
            'format': format_spec,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
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
                    'player_client': ['android_vr', 'web_creator', 'android']
                }
            }
        }
        if Config.USE_PROXY and Config.get_proxy_url():
            ydl_opts['proxy'] = Config.get_proxy_url()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            if not info:
                return None
            formats = info.get("formats", [])
            dl_url = info.get("url") or (formats[-1].get("url") if formats else None)
            if dl_url:
                video_id = info.get("id", "")
                thumbnail = info.get("thumbnail") or (
                    f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg" if video_id else ""
                )
                return {
                    "url": dl_url,
                    "title": info.get("title", "YouTube Video"),
                    "duration": int(info.get("duration") or 0),
                    "thumbnail": thumbnail,
                }
            return None

    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, extract)
        return res
    except Exception as e:
        print(f"[Scraper/ytdlp] Direct extraction failed: {e}")
        return None


# ─── Scraper 2: Cobalt API (High-Performance Multi-Instance Resolution) ────
async def _extract_cobalt(video_url: str, mode: str) -> Optional[Dict[str, str]]:
    """Resolves direct stream URL using public Cobalt API instances."""
    instances = [
        "https://api.qwkuns.me",
        "https://cobaltapi.kittycat.boo",
        "https://nuko-c.meowing.de",
        "https://subito-c.meowing.de",
        "https://rue-cobalt.xenon.zone",
        "https://api.cobalt.liubquanti.click",
    ]
    payload = {
        "url": video_url,
        "videoQuality": "480",
        "downloadMode": "audio" if mode == "audio" else "video"
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
    connector = get_doh_connector()
    try:
        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            async def check_instance(instance: str) -> Optional[Dict[str, str]]:
                try:
                    async with session.post(instance, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("status") != "error" and data.get("url"):
                                video_id = extract_video_id(video_url) or ""
                                return {
                                    "url": data["url"],
                                    "title": data.get("filename") or f"YouTube Video ({video_id})",
                                    "thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg" if video_id else "",
                                    "duration": 0
                                }
                except Exception:
                    pass
                return None

            tasks = [asyncio.create_task(check_instance(inst)) for inst in instances]
            for future in asyncio.as_completed(tasks):
                try:
                    res = await future
                    if res:
                        for t in tasks:
                            if not t.done():
                                t.cancel()
                        return res
                except Exception:
                    pass
    except Exception as e:
        print(f"[Scraper/cobalt] Cobalt extraction note: {e}")
    return None


# ─── Scraper 3: Invidious API (Open-Source Multi-Instance YouTube Frontend) ─
async def _extract_invidious(video_url: str, mode: str) -> Optional[Dict[str, str]]:
    """Resolves stream direct URL via Invidious API instances."""
    video_id = extract_video_id(video_url)
    if not video_id:
        return None

    instances = [
        "https://inv.tux.pizza",
        "https://invidious.nerdvpn.de",
        "https://vid.puffyan.us",
        "https://yewtu.be",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }
    connector = get_doh_connector()
    try:
        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            for inst in instances:
                try:
                    api_url = f"{inst}/api/v1/videos/{video_id}"
                    async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            title = data.get("title", "YouTube Video")
                            dur = int(data.get("lengthSeconds", 0))
                            thumb = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

                            if mode == "audio":
                                adaptive = data.get("adaptiveFormats", [])
                                audio_streams = [f for f in adaptive if str(f.get("type", "")).startswith("audio/")]
                                if audio_streams:
                                    audio_streams.sort(key=lambda x: int(x.get("bitrate", 0)), reverse=True)
                                    return {"url": audio_streams[0]["url"], "title": title, "duration": dur, "thumbnail": thumb}
                            else:
                                format_streams = data.get("formatStreams", [])
                                if format_streams:
                                    format_streams.sort(key=lambda x: int(x.get("height", 0) or 0), reverse=True)
                                    return {"url": format_streams[0]["url"], "title": title, "duration": dur, "thumbnail": thumb}
                except Exception:
                    continue
    except Exception as e:
        print(f"[Scraper/invidious] Invidious extraction note: {e}")
    return None


# ─── Scraper 4: Piped API (Open-Source Privacy API) ────────────────────────
async def _extract_piped(video_url: str, mode: str) -> Optional[Dict[str, str]]:
    """Resolves stream direct URL via Piped API instances."""
    video_id = extract_video_id(video_url)
    if not video_id:
        return None

    instances = [
        "https://pipedapi.kavin.rocks",
        "https://api.piped.privacydev.net",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
    connector = get_doh_connector()
    try:
        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            for inst in instances:
                try:
                    api_url = f"{inst}/streams/{video_id}"
                    async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            title = data.get("title", "YouTube Video")
                            dur = int(data.get("duration", 0))
                            thumb = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

                            if mode == "audio":
                                audio_streams = data.get("audioStreams", [])
                                if audio_streams:
                                    audio_streams.sort(key=lambda x: int(x.get("bitrate", 0) or 0), reverse=True)
                                    return {"url": audio_streams[0]["url"], "title": title, "duration": dur, "thumbnail": thumb}
                            else:
                                video_streams = data.get("videoStreams", [])
                                if video_streams:
                                    video_streams.sort(key=lambda x: int(x.get("height", 0) or 0), reverse=True)
                                    return {"url": video_streams[0]["url"], "title": title, "duration": dur, "thumbnail": thumb}
                except Exception:
                    continue
    except Exception as e:
        print(f"[Scraper/piped] Piped extraction note: {e}")
    return None


# ─── Scraper 5: yt5s ────────────────────────────────────────────────────────
async def _extract_yt5s(video_url: str, mode: str) -> Optional[Dict[str, str]]:
    domain = "yt5s.in"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": f"https://{domain}",
        "Referer": f"https://{domain}/"
    }

    connector = get_doh_connector()
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            search_url = f"https://{domain}/api/ajaxSearch/index"
            payload = f"query={urllib.parse.quote(video_url)}&vt=mp4"
            
            async with session.post(search_url, data=payload, headers=headers, timeout=12) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                if data.get("status") != "ok":
                    return None

                title = data.get("title", "YouTube Video")
                links_html = data.get("links", "")
                
                fid_match = re.search(r'data-fid="([^"]+)"', links_html)
                if not fid_match:
                    return None
                fid = fid_match.group(1)

                if mode == "audio":
                    k_match = (
                        re.search(r'data-ftype="mp3"[^>]*data-k="([^"]+)"', links_html) or
                        re.search(r'data-ftype="m4a"[^>]*data-k="([^"]+)"', links_html)
                    )
                else:
                    k_match = (
                        re.search(r'data-ftype="mp4"[^>]*data-fquality="720"[^>]*data-k="([^"]+)"', links_html) or
                        re.search(r'data-ftype="mp4"[^>]*data-fquality="480"[^>]*data-k="([^"]+)"', links_html) or
                        re.search(r'data-ftype="mp4"[^>]*data-k="([^"]+)"', links_html)
                    )
                
                if not k_match:
                    return None
                k_val = k_match.group(1)

                convert_url = f"https://{domain}/api/ajaxConvert/convert"
                convert_payload = f"vid={fid}&k={k_val}"
                
                async with session.post(convert_url, data=convert_payload, headers=headers, timeout=20) as c_resp:
                    if c_resp.status == 200:
                        c_data = await c_resp.json(content_type=None)
                        if c_data.get("status") == "ok":
                            dl = c_data.get("dlink")
                            if dl:
                                return {"url": dl, "title": title}
    except Exception:
        pass
    return None


# ─── Scraper 6: yt1s ────────────────────────────────────────────────────────
async def _extract_yt1s(video_url: str, mode: str) -> Optional[Dict[str, str]]:
    domain = "yt1s.com"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://{domain}/"
    }

    connector = get_doh_connector()
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            search_url = f"https://{domain}/api/ajaxSearch"
            payload = f"query={urllib.parse.quote(video_url)}&vt=mp4"

            async with session.post(search_url, data=payload, headers=headers, timeout=12) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                if data.get("status") != "ok":
                    return None

                title = data.get("title", "YouTube Video")
                links = data.get("links", {})
                vid = data.get("vid") or data.get("id")
                
                k_val = None
                if mode == "audio":
                    mp3_links = links.get("mp3", {})
                    for q in ["128kbps", "320kbps", "192kbps", "mp3128"]:
                        if q in mp3_links:
                            k_val = mp3_links[q].get("k") or mp3_links[q].get("f")
                            if k_val: break
                else:
                    mp4_links = links.get("mp4", {})
                    for q in ["720p", "480p", "360p", "mp4720"]:
                        if q in mp4_links:
                            k_val = mp4_links[q].get("k") or mp4_links[q].get("f")
                            if k_val: break

                if not k_val or not vid:
                    return None

                convert_url = f"https://{domain}/api/ajaxConvert"
                convert_payload = f"vid={vid}&k={k_val}"
                async with session.post(convert_url, data=convert_payload, headers=headers, timeout=20) as c_resp:
                    if c_resp.status == 200:
                        c_data = await c_resp.json(content_type=None)
                        dl = c_data.get("dlink") or c_data.get("url")
                        if dl:
                            return {"url": dl, "title": title}
    except Exception:
        pass
    return None


# ─── Scraper 7: y2mate ───────────────────────────────────────────────────────
async def _extract_y2mate(video_url: str, mode: str) -> Optional[Dict[str, str]]:
    domain = "y2mate.is"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://{domain}/"
    }

    connector = get_doh_connector()
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            analyze_url = f"https://{domain}/mates/en/analyze/ajax"
            analyze_payload = f"url={urllib.parse.quote(video_url)}&q_auto=0&ajax=1"

            async with session.post(analyze_url, data=analyze_payload, headers=headers, timeout=12) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                vid = data.get("vid")
                title = data.get("title", "YouTube Video")
                if not vid:
                    return None

                links = data.get("links", {})
                k_val = None
                
                if mode == "audio":
                    mp3_links = links.get("mp3", {})
                    for q in ["128k", "320k", "192k"]:
                        if q in mp3_links:
                            k_val = mp3_links[q].get("k")
                            if k_val: break
                else:
                    mp4_links = links.get("mp4", {})
                    for q in ["720p", "480p", "360p"]:
                        if q in mp4_links:
                            k_val = mp4_links[q].get("k")
                            if k_val: break

                if not k_val:
                    return None

                convert_url = f"https://{domain}/mates/en/convert"
                convert_payload = f"vid={vid}&k={k_val}"
                async with session.post(convert_url, data=convert_payload, headers=headers, timeout=20) as c_resp:
                    if c_resp.status == 200:
                        c_data = await c_resp.json(content_type=None)
                        dl_url = c_data.get("dlink")
                        if dl_url:
                            return {"url": dl_url, "title": title}
    except Exception:
        pass
    return None


# ─── Scraper 8: ytmp3 ────────────────────────────────────────────────────────
async def _extract_ytmp3(video_url: str, mode: str) -> Optional[Dict[str, str]]:
    domain = "ytmp3.cc"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    connector = get_doh_connector()
    try:
        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            api_mode = "mp4" if mode == "video" else "mp3"
            api_url = f"https://{domain}/api/json/{api_mode}?url={urllib.parse.quote(video_url)}"
            async with session.get(api_url, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    dl = data.get("url") or data.get("dlink") or data.get("download_url")
                    if dl and dl.startswith("http"):
                        return {"url": dl, "title": data.get("title", "YouTube Video")}
    except Exception:
        pass
    return None


# ─── Scraper 9: 9xbuddy ──────────────────────────────────────────────────────
async def _extract_9xbuddy(video_url: str, mode: str) -> Optional[Dict[str, str]]:
    domain = "9xbuddy.app"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": f"https://{domain}/"
    }

    connector = get_doh_connector()
    try:
        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            encoded = urllib.parse.quote(video_url)
            api_url = f"https://{domain}/process?url={encoded}"

            async with session.get(api_url, timeout=20) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
                if not text or not text.strip() or text.strip().startswith("<"):
                    return None
                data = json.loads(text)
                title = data.get("title", "YouTube Video")
                download_links = data.get("download", [])
                
                for link in download_links:
                    label = str(link.get("label", "")).lower()
                    url = link.get("url", "")
                    
                    if mode == "audio":
                        if "mp3" in label or "audio" in label or "m4a" in label:
                            return {"url": url, "title": title}
                    else:
                        if ("720" in label or "480" in label) and url.startswith("http"):
                            return {"url": url, "title": title}
                
                if download_links and download_links[0].get("url", "").startswith("http"):
                    return {"url": download_links[0]["url"], "title": title}
    except Exception:
        pass
    return None


async def extract_youtube_playlist(playlist_url: str) -> Optional[list]:
    """Extract flat entries from a YouTube playlist quickly with SQLite DB caching."""
    import yt_dlp
    import urllib.parse as urlparse
    from core.db import get_cached_playlist, save_playlist_to_cache

    playlist_id = None
    try:
        parsed = urlparse.urlparse(playlist_url)
        params = urlparse.parse_qs(parsed.query)
        playlist_id = params.get('list', [None])[0]
    except Exception:
        pass

    if not playlist_id:
        playlist_id = playlist_url.strip()

    # 1. Instant SQLite DB Cache Check
    cached = get_cached_playlist(playlist_id)
    if cached:
        print(f"[Scraper/playlist] Instant DB Cache Hit for playlist ID '{playlist_id}' ({len(cached)} tracks)!")
        return cached

    # 2. Fast GAMEOVER FastAPI Backend /api/playlist check
    try:
        import os
        api_base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
        api_key  = os.getenv("GAMEOVER_API_KEY", "GAMEOVER_SECRET_123")
        url = f"{api_base}/api/playlist?url={urllib.parse.quote(playlist_url)}&limit=50&api_key={api_key}"

        connector = get_doh_connector()
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "success" and data.get("videos"):
                        result = [
                            {"title": v["title"], "url": v["url"], "id": v["video_id"]}
                            for v in data["videos"]
                        ]
                        print(f"[Scraper/playlist] FastAPI extracted {len(result)} tracks for '{data.get('playlist_title')}'!")
                        if playlist_id:
                            save_playlist_to_cache(playlist_id, result)
                        return result
    except Exception as e:
        print(f"[Scraper/playlist] FastAPI playlist note: {e}")

    # Rewrite YouTube Mix / dynamic playlist links redirecting to homepage to watch mix URLs
    if "playlist?list=" in playlist_url:
        try:
            if playlist_id and (playlist_id.startswith('RD') or playlist_id.startswith('UL')) and len(playlist_id) == 13:
                video_id = playlist_id[2:]
                playlist_url = f"https://www.youtube.com/watch?v={video_id}&list={playlist_id}"
                print(f"[Scraper/playlist] Rewrote Mix playlist link to watch URL: {playlist_url}")
        except Exception as e:
            print(f"[Scraper/playlist] URL rewrite failed: {e}")
    
    def extract():
        ydl_opts = {
            'extract_flat': 'in_playlist',
            'quiet': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'socket_timeout': 5.0,
            'retries': 2,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android_vr', 'web_creator', 'android']
                }
            }
        }
        if Config.USE_PROXY and Config.get_proxy_url():
            ydl_opts['proxy'] = Config.get_proxy_url()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)
            if not info:
                return None
            entries = info.get('entries', [])
            result = []
            for entry in entries:
                if not entry:
                    continue
                video_id = entry.get('id')
                if not video_id and entry.get('url'):
                    video_id = extract_video_id(entry.get('url'))
                if video_id:
                    result.append({
                        "title": entry.get("title") or "YouTube Song",
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "id": video_id
                    })
            return result

    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, extract)
        if res:
            res = res[:50]
            if playlist_id:
                save_playlist_to_cache(playlist_id, res)
        return res
    except Exception as e:
        print(f"[Scraper/playlist] Playlist extraction failed: {e}")
        return None
