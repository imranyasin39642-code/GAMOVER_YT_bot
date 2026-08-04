"""
Clean 100% Pure Local PC API scraper update for GAMEOVER YT MUSIC (NO nskmedia.net!)
"""

CLEAN_SCRAPER = '''# --- Scraper 0: GAMEOVER Local PC API Extractor (100% PURE LOCAL PC) ----
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

'''

with open('core/scrapers.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

start_idx = None
end_idx = None
for i, l in enumerate(lines):
    if 'Scraper 0:' in l:
        start_idx = i
    if start_idx and i > start_idx and 'Scraper 1:' in l:
        end_idx = i - 1
        break

print(f"start_idx={start_idx}, end_idx={end_idx}")
if start_idx is not None and end_idx is not None:
    new_lines = lines[:start_idx] + [CLEAN_SCRAPER] + lines[end_idx:]
    with open('core/scrapers.py', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    print("Core scrapers updated: nskmedia.net removed 100%!")
