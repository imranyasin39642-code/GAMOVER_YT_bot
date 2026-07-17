import asyncio
import re
import json
import urllib.parse
from typing import Optional, Dict
import aiohttp
from core.dns_helper import get_doh_connector

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
    Search YouTube for a query using the internal search API (no API key needed).
    Returns a dict with 'video_id', 'url', 'title' of the top result, or None.
    """
    encoded = urllib.parse.quote(query)
    search_url = f"https://www.youtube.com/results?search_query={encoded}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        connector = get_doh_connector()
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(search_url, headers=headers, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
        
        # Extract video IDs from the initial data JSON embedded in the page
        match = re.search(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
        if not match:
            return None
        
        video_id = match.group(1)
        
        # Extract title — look for "title":{"runs":[{"text":"..."}]} pattern near the videoId
        title = "YouTube Video"
        title_match = re.search(
            r'"videoId":"' + re.escape(video_id) + r'".*?"title":\{"runs":\[\{"text":"([^"]+)"',
            html
        )
        if not title_match:
            # Fallback: grab any "text" right after videoId
            title_match = re.search(
                r'"videoId":"' + re.escape(video_id) + r'"[^}]*?"text":"([^"]{5,80})"',
                html
            )
        if title_match:
            title = title_match.group(1)
        
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"[Search] Found: {title} → {video_url}")
        return {"video_id": video_id, "url": video_url, "title": title}
        
    except Exception as e:
        print(f"[Search] YouTube search failed: {e}")
        return None

# Fallback sequence of sites to scrape
SCRAPING_SITES = ["yt5s", "yt1s", "y2mate", "ytmp3", "9xbuddy", "ytdlp"]

async def resolve_stream_url(youtube_url: str, mode: str = "video") -> Optional[Dict[str, str]]:
    """
    Iterate over our scraper chain to resolve direct video or audio streams.
    Returns a dict with 'url' and 'title' on success, or None on failure.
    """
    video_id = extract_video_id(youtube_url)
    if not video_id:
        print(f"[Scraper] Invalid YouTube URL: {youtube_url}")
        return None

    clean_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"[Scraper] Resolving {mode} stream for YouTube ID: {video_id}")

    extractors = {
        "yt5s":    _extract_yt5s,
        "yt1s":    _extract_yt1s,
        "y2mate":  _extract_y2mate,
        "ytmp3":   _extract_ytmp3,
        "9xbuddy": _extract_9xbuddy,
        "ytdlp":   _extract_ytdlp_direct,
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


# ─── Scraper 1: yt5s ────────────────────────────────────────────────────────
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
            # Search Video details
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

                # Find quality key based on mode
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

                # Convert to direct stream URL
                convert_url = f"https://{domain}/api/ajaxConvert/convert"
                convert_payload = f"vid={fid}&k={k_val}"
                
                async with session.post(convert_url, data=convert_payload, headers=headers, timeout=20) as c_resp:
                    if c_resp.status == 200:
                        c_data = await c_resp.json(content_type=None)
                        if c_data.get("status") == "ok":
                            dl = c_data.get("dlink")
                            if dl:
                                return {"url": dl, "title": title}
    finally:
        await connector.close()
    return None


# ─── Scraper 2: yt1s ────────────────────────────────────────────────────────
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
    finally:
        await connector.close()
    return None


# ─── Scraper 3: y2mate ───────────────────────────────────────────────────────
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
    finally:
        await connector.close()
    return None


# ─── Scraper 4: ytmp3 ────────────────────────────────────────────────────────
async def _extract_ytmp3(video_url: str, mode: str) -> Optional[Dict[str, str]]:
    domain = "ytmp3.cc"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    connector = get_doh_connector()
    try:
        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            # ytmp3 usually focuses on conversion. In mp4 mode, request the mp4 url.
            api_mode = "mp4" if mode == "video" else "mp3"
            api_url = f"https://{domain}/api/json/{api_mode}?url={urllib.parse.quote(video_url)}"
            async with session.get(api_url, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    dl = data.get("url") or data.get("dlink") or data.get("download_url")
                    if dl and dl.startswith("http"):
                        return {"url": dl, "title": data.get("title", "YouTube Video")}
    finally:
        await connector.close()
    return None


# ─── Scraper 5: 9xbuddy ──────────────────────────────────────────────────────
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
                
                # Final fallback to first link
                if download_links and download_links[0].get("url", "").startswith("http"):
                    return {"url": download_links[0]["url"], "title": title}
    finally:
        await connector.close()
    return None


# ─── Scraper 6: Programmatic yt-dlp iOS Extractor (Ultimate Fallback) ───────
async def _extract_ytdlp_direct(video_url: str, mode: str) -> Optional[Dict[str, str]]:
    """Programmatic yt-dlp extractor utilizing the iOS client to bypass all cookie barriers."""
    import yt_dlp
    
    format_spec = "best[height<=720]" if mode == "video" else "bestaudio"
    ydl_opts = {
        'format': format_spec,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'extractor_args': {
            'youtube': {
                'client': ['ios'] # Strictly use iOS client parameter to skip cookies
            }
        }
    }
    
    def extract():
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
            
    loop = asyncio.get_event_loop()
    try:
        res = await loop.run_in_executor(None, extract)
        return res
    except Exception as e:
        print(f"[Scraper/ytdlp-ios] Extraction failed: {e}")
        return None
