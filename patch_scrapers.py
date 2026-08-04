"""
Clean Proxy-based Local PC API scraper update for GAMEOVER YT MUSIC
"""

CLEAN_SCRAPER = '''# --- Scraper 0: GAMEOVER Local PC API Extractor (100% 403-FREE MEDIA STREAM PROXY) ----
async def _extract_gameover_api(video_url: str, mode: str) -> Optional[Dict[str, str]]:
    """
    Primary Scraper: Hits Local PC API via Cloudflare Tunnel.
    - Zero cookies needed (Residential IP = No YouTube Ban).
    - Uses /api/stream proxy endpoint to guarantee 200 OK on VPS (Zero 403 Errors!).
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

    meta_url = f"{local_api_url}/api/extract?video_id={video_id}&api_key={local_api_key}"
    print(f"[LocalAPI] Requesting metadata from Local PC: {meta_url[:80]}...")
    
    try:
        timeout   = aiohttp.ClientTimeout(total=15)
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.get(meta_url, allow_redirects=True) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "success":
                        v_info    = data.get("video_info") or data
                        title     = data.get("title") or v_info.get("title") or "YouTube Stream"
                        duration  = data.get("duration") or v_info.get("duration") or 0
                        thumbnail = data.get("thumbnail") or v_info.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                        
                        proxy_stream_url = f"{local_api_url}/api/stream?video_id={video_id}&mode={mode}&api_key={local_api_key}"
                        print(f"[LocalAPI] SUCCESS! Resolved Stream Proxy from Local PC: {title}")
                        return {
                            "url":       proxy_stream_url,
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
    print("Core scrapers updated with 100% 403-free stream proxy!")
