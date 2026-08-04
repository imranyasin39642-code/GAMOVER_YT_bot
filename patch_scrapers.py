"""
Patch script: Replace _extract_gameover_api in core/scrapers.py
Lines 126-234 (0-indexed: 125-233) will be replaced.
"""

NEW_FUNCTION = '''# --- Scraper 0: GAMEOVER FastAPI Extractor (Primary High-Speed Scraper) ----
async def _extract_gameover_api(video_url: str, mode: str) -> Optional[Dict[str, str]]:
    """
    Primary scraper: Hits LOCAL PC API (via Cloudflare Tunnel) FIRST.
    - Local PC uses Residential IP -> YouTube never blocks it -> No cookies needed!
    - Returns only JSON stream URL (few KBs) -> 20GB internet 100% safe!
    - Fallback: Tries nskmedia.net cPanel API if Local PC is offline.
    """
    import os

    video_id = extract_video_id(video_url)
    if not video_id:
        return None

    # LOCAL_API_URL = Cloudflare Tunnel to your Local PC (set in .env after cloudflare setup)
    local_api_url  = os.getenv("LOCAL_API_URL", "").rstrip("/")
    local_api_key  = os.getenv("LOCAL_API_KEY", "GAMEOVER_LOCAL_2026")

    # cPanel nskmedia.net fallback
    cpanel_api_url = os.getenv("API_BASE_URL", "https://nskmedia.net").rstrip("/")
    cpanel_api_key = os.getenv("GAMEOVER_API_KEY", "GAMEOVER_SECRET_123")

    # Build endpoint list: LOCAL first, then cPanel fallback
    endpoints = []
    if local_api_url:
        # Local PC API uses /extract (no /api/ prefix)
        endpoints.append({
            "url":  f"{local_api_url}/extract?video_id={video_id}&api_key={local_api_key}",
            "name": "LocalPC",
        })
    # cPanel API uses /api/extract
    endpoints.append({
        "url":  f"{cpanel_api_url}/api/extract?video_id={video_id}&api_key={cpanel_api_key}",
        "name": "cPanel",
    })

    for ep in endpoints:
        ep_url  = ep["url"]
        ep_name = ep["name"]
        print(f"[Scraper/GameOverAPI] [{ep_name}] Requesting: {ep_url[:80]}...")

        try:
            timeout   = aiohttp.ClientTimeout(total=20)
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.get(ep_url, allow_redirects=True) as resp:
                    print(f"[Scraper/GameOverAPI] [{ep_name}] HTTP {resp.status}")

                    if resp.status != 200:
                        body = await resp.text()
                        print(f"[Scraper/GameOverAPI] [{ep_name}] Error body: {body[:150]}")
                        continue

                    data = await resp.json()
                    api_status = data.get("status")
                    print(f"[Scraper/GameOverAPI] [{ep_name}] status={api_status} | keys={list(data.keys())}")

                    if api_status != "success":
                        print(f"[Scraper/GameOverAPI] [{ep_name}] API error: code={data.get('code')} msg={data.get('message')}")
                        continue

                    # Parse response (Local API has top-level fields, cPanel has video_info{})
                    v_info     = data.get("video_info") or data
                    stream_url = None

                    # Audio mode: pick audio_only first
                    if mode == "audio":
                        raw = data.get("audio_only")
                        stream_url = raw if isinstance(raw, str) else (raw.get("url") if isinstance(raw, dict) else None)

                    # Video mode: pick preferred quality
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
                                    print(f"[Scraper/GameOverAPI] [{ep_name}] Quality: {pk}")
                                    break

                    # Fallback: best_merged
                    if not stream_url:
                        raw = data.get("best_merged")
                        stream_url = raw if isinstance(raw, str) else (
                            (raw.get("url") or raw.get("video_url")) if isinstance(raw, dict) else None
                        )

                    # Fallback: any stream from streams dict
                    if not stream_url and data.get("streams"):
                        for _, s_val in data["streams"].items():
                            if isinstance(s_val, str):
                                stream_url = s_val
                                break
                            elif isinstance(s_val, dict):
                                stream_url = (
                                    s_val.get("audio_url") or
                                    s_val.get("video_url") or
                                    s_val.get("url")
                                )
                                if stream_url:
                                    break

                    # Fallback: top-level url or audio_only
                    if not stream_url:
                        stream_url = data.get("url") or (data.get("audio_only") if isinstance(data.get("audio_only"), str) else None)

                    if stream_url:
                        title     = data.get("title") or v_info.get("title") or "YouTube Stream"
                        duration  = data.get("duration") or v_info.get("duration") or 0
                        thumbnail = data.get("thumbnail") or v_info.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                        print(f"[Scraper/GameOverAPI] [{ep_name}] SUCCESS! Title: {title}")
                        return {
                            "url":       stream_url,
                            "title":     title,
                            "duration":  duration,
                            "thumbnail": thumbnail,
                        }
                    else:
                        print(f"[Scraper/GameOverAPI] [{ep_name}] status=success but stream_url was null!")

        except Exception as e:
            print(f"[Scraper/GameOverAPI] [{ep_name}] Error: {e}")

    return None

'''

with open('core/scrapers.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Lines 126 to 234 (1-indexed) = index 125 to 233 (0-indexed), inclusive
# Replace them with new function
new_lines = lines[:125] + [NEW_FUNCTION + '\n'] + lines[234:]

with open('core/scrapers.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("PATCH APPLIED SUCCESSFULLY!")
print(f"Original lines: {len(lines)}")
print(f"New lines: {len(new_lines)}")
