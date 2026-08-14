"""
╔══════════════════════════════════════════════════════════════╗
║    GAMEOVER YT MUSIC — core/playwright_scraper.py             ║
║    Tier 2 Playwright + Invidious Mirror Scraper Engine       ║
║                                                              ║
║    Features:                                                 ║
║    - 100% Cookie-free, 403-free Invidious & Web Engine       ║
║    - Direct YouTube link bypass                              ║
║    - Audio mode: High quality .m4a / .mp3 stream link        ║
║    - Video mode: 1080p60 / 1080p .mp4 stream link            ║
║    - Playwright Headless Browser + Fast HTTP Scrapers        ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio
import os
import re
import urllib.parse
from typing import Optional, Dict
import aiohttp

INVIDIOUS_MIRRORS = [
    "https://yewtu.be",
    "https://invidious.projectsegfau.lt",
    "https://inv.tux.pizza",
    "https://invidious.nerdvpn.de",
]



_PLAYWRIGHT_INSTANCE = None
_BROWSER_INSTANCE = None
_BROWSER_LOCK = asyncio.Lock()


async def get_browser():
    """Maintain singleton Playwright Chromium browser instance for ultra-fast scraping."""
    global _PLAYWRIGHT_INSTANCE, _BROWSER_INSTANCE
    async with _BROWSER_LOCK:
        if _BROWSER_INSTANCE is None or not _BROWSER_INSTANCE.is_connected():
            try:
                from playwright.async_api import async_playwright
                _PLAYWRIGHT_INSTANCE = await async_playwright().start()
                _BROWSER_INSTANCE = await _PLAYWRIGHT_INSTANCE.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled"
                    ]
                )
                print("[Playwright] Browser pool started successfully.")
            except Exception as e:
                print(f"[Playwright] Error starting browser pool: {e}")
                _BROWSER_INSTANCE = None
        return _BROWSER_INSTANCE


async def close_browser():
    """Cleanup Playwright browser instance on bot shutdown."""
    global _PLAYWRIGHT_INSTANCE, _BROWSER_INSTANCE
    async with _BROWSER_LOCK:
        if _BROWSER_INSTANCE:
            try:
                await _BROWSER_INSTANCE.close()
            except Exception:
                pass
            _BROWSER_INSTANCE = None
        if _PLAYWRIGHT_INSTANCE:
            try:
                await _PLAYWRIGHT_INSTANCE.stop()
            except Exception:
                pass
            _PLAYWRIGHT_INSTANCE = None


async def extract_stream_playwright(video_id: str, mode: str = "audio") -> Optional[Dict[str, str]]:
    """
    Tier 2 Multi-Engine Extractor (0-Cookie Web API & Scraper Pool).
    Races Cobalt, Invidious, Piped, Loader, YT5s, YT1s, Y2Mate, and YTmp3 IN PARALLEL for sub-second responses.
    """
    clean_video_id = video_id.strip()
    yt_url = f"https://www.youtube.com/watch?v={clean_video_id}"

    # Import fast scrapers from core.scrapers for parallel execution
    from core.scrapers import (
        _extract_cobalt, _extract_piped, _extract_yt5s,
        _extract_invidious, _extract_yt1s, _extract_y2mate, _extract_ytmp3
    )

    # Unified Parallel Engine Pool (Fast Web APIs + Scrapers)
    parallel_tasks = [
        asyncio.create_task(_extract_cobalt(yt_url, mode)),
        asyncio.create_task(_extract_invidious(yt_url, mode)),
        asyncio.create_task(_extract_piped(yt_url, mode)),
        asyncio.create_task(_scrape_loader_engine(clean_video_id, yt_url, mode)),
        asyncio.create_task(_extract_yt5s(yt_url, mode)),
        asyncio.create_task(_extract_yt1s(yt_url, mode)),
        asyncio.create_task(_extract_y2mate(yt_url, mode)),
        asyncio.create_task(_extract_ytmp3(yt_url, mode)),
    ]


    for future in asyncio.as_completed(parallel_tasks):
        try:
            res = await future
            if res and res.get("url"):
                for t in parallel_tasks:
                    if not t.done():
                        t.cancel()
                print(f"[Tier2/Parallel-Engine] INSTANT SUCCESS: {str(res.get('title', 'Video'))[:40]}")
                return res
        except (asyncio.CancelledError, Exception):
            pass


    # Playwright browser fallback if all API endpoints fail or timeout
    print(f"[Tier2] Fast API engines unresponsive for video_id={clean_video_id}. Attempting Playwright Chromium...")
    browser_res = await _scrape_invidious_playwright_browser(clean_video_id, mode)
    if browser_res and browser_res.get("url"):
        return browser_res

    print(f"[Tier2] All extraction engines failed for video_id={clean_video_id}")
    return None


async def _scrape_invidious_playwright_browser(video_id: str, mode: str) -> Optional[Dict[str, str]]:
    """Playwright Chromium headless browser scraper iterating active Invidious mirrors."""
    browser = await get_browser()
    if not browser:
        return None

    context = None
    page = None
    try:
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)
        page = await context.new_page()


        for mirror in INVIDIOUS_MIRRORS:
            try:
                target_url = f"{mirror}/watch?v={video_id}"
                await page.goto(target_url, timeout=8000, wait_until="domcontentloaded")
                await page.wait_for_timeout(800)

                title = await page.title()
                if "Gandalf" in title:
                    await page.wait_for_timeout(2000)
                    title = await page.title()

                html = await page.content()

                # 1. HTML source regex match for direct Invidious /latest_version download links
                match_links = re.findall(r'/latest_version\?[^\s"\'<>]+', html)
                if match_links:
                    chosen_url = None
                    if mode == "video":
                        for l in match_links:
                            if "1080" in l or "mp4" in l or "itag=22" in l or "itag=137" in l:
                                chosen_url = l
                                break
                        if not chosen_url:
                            chosen_url = match_links[0]
                    else:
                        for l in match_links:
                            if "m4a" in l or "audio" in l or "itag=140" in l or "itag=251" in l:
                                chosen_url = l
                                break
                        if not chosen_url:
                            chosen_url = match_links[-1]

                    if chosen_url:
                        full_stream_url = urllib.parse.urljoin(mirror, chosen_url)
                        title_str = str(title).encode('ascii', errors='ignore').decode('ascii')
                        print(f"[Playwright/Browser] Scraped Invidious stream URL from {mirror}: {title_str[:40]} -> {full_stream_url[:60]}")
                        return {
                            "url": full_stream_url,
                            "title": title.strip(),
                            "duration": 0,
                            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                        }

                # 2. DOM Evaluation fallback
                try:
                    dom_stream = await page.evaluate("""() => {
                        const audio = document.querySelector('audio source, audio');
                        if (audio && audio.src) return audio.src;
                        const video = document.querySelector('video source, video');
                        if (video && video.src) return video.src;
                        const downloadLink = document.querySelector('a[href*="/latest_version"], a[download]');
                        if (downloadLink && downloadLink.href) return downloadLink.href;
                        return null;
                    }""")
                    if dom_stream:
                        title_str = str(title).encode('ascii', errors='ignore').decode('ascii')
                        print(f"[Playwright/Browser] Scraped stream URL via DOM from {mirror}: {title_str[:40]}")
                        return {
                            "url": dom_stream,
                            "title": title.strip(),
                            "duration": 0,
                            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                        }
                except Exception:
                    pass

            except Exception as mirror_err:
                print(f"[Playwright/Browser] Mirror {mirror} note: {mirror_err}")
                continue


    except Exception as e:
        print(f"[Playwright/Invidious] Browser scrape error: {e}")
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass
        if context:
            try:
                await context.close()
            except Exception:
                pass

    return None


async def _scrape_loader_engine(video_id: str, youtube_url: str, mode: str) -> Optional[Dict[str, str]]:
    """Loader.to Web Scraper for 1080p video and MP3 audio."""
    clean_url = f"https://www.youtube.com/watch?v={video_id}"
    fmt = "1080" if mode == "video" else "mp3"
    init_url = f"https://loader.to/ajax/download.php?format={fmt}&url={urllib.parse.quote(clean_url)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Referer": "https://en.loader.to/"
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(init_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                if not data.get("success"):
                    return None

                progress_url = data.get("progress_url")
                title = data.get("title") or (data.get("info") or {}).get("title") or "YouTube Video"
                thumbnail = (data.get("info") or {}).get("image") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

                if not progress_url:
                    return None

            # Poll progress URL for up to 12 seconds
            for _ in range(10):
                await asyncio.sleep(1.0)
                try:
                    async with session.get(progress_url, timeout=aiohttp.ClientTimeout(total=6)) as resp2:
                        if resp2.status == 200:
                            pdata = await resp2.json(content_type=None)
                            dl_url = pdata.get("download_url")
                            if dl_url and dl_url.startswith("http") and not dl_url.endswith(".html"):
                                return {
                                    "url": dl_url,
                                    "title": pdata.get("title") or title,
                                    "duration": int(pdata.get("video_duration") or 0),
                                    "thumbnail": thumbnail,
                                }
                except Exception as e:
                    print(f"[Tier2/Loader] Poll note: {e}")
    except Exception as e:
        print(f"[Tier2/Loader] Error: {e}")

    return None


async def _scrape_invidious_api_fast(mirror_base: str, video_id: str, mode: str) -> Optional[Dict[str, str]]:
    """Fast Invidious REST API parser."""
    api_url = f"{mirror_base.rstrip('/')}/api/v1/videos/{video_id}"
    timeout = aiohttp.ClientTimeout(total=8, connect=4)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(api_url) as resp:
            if resp.status != 200:
                return None
            try:
                data = await resp.json(content_type=None)
            except Exception:
                return None

            if not data or "title" not in data:
                return None

            title = data.get("title", "YouTube Video")
            duration = int(data.get("lengthSeconds") or 0)
            thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

            adaptive = data.get("adaptiveFormats") or []
            format_streams = data.get("formatStreams") or []

            stream_url = None

            if mode == "audio":
                audio_formats = [f for f in adaptive if (f.get("type") or "").startswith("audio/")]
                audio_formats.sort(key=lambda x: int(x.get("bitrate") or 0), reverse=True)
                for f in audio_formats:
                    if f.get("url"):
                        stream_url = f["url"]
                        break
            else:
                video_1080 = [
                    f for f in (format_streams + adaptive)
                    if (f.get("qualityLabel") or "").startswith("1080p") and f.get("url")
                ]
                if video_1080:
                    stream_url = video_1080[0]["url"]
                else:
                    video_720 = [
                        f for f in (format_streams + adaptive)
                        if (f.get("qualityLabel") or "").startswith("720p") and f.get("url")
                    ]
                    if video_720:
                        stream_url = video_720[0]["url"]
                    elif format_streams:
                        stream_url = format_streams[0].get("url")

            if stream_url:
                if stream_url.startswith("/"):
                    stream_url = urllib.parse.urljoin(mirror_base, stream_url)

                return {
                    "url": stream_url,
                    "title": title,
                    "duration": duration,
                    "thumbnail": thumbnail,
                }
    return None
