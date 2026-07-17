import os
from core.db import get_setting, set_setting

async def send_cached_video(client, chat_id, video_path, cache_key_prefix, caption=None, reply_markup=None, parse_mode=None):
    """
    Sends a video to the specified chat_id.
    Uses the cached file_id if available, otherwise uploads the local video_path
    and caches the resulting file_id for subsequent sends.
    """
    try:
        cached_id = get_setting(f"{cache_key_prefix}_file_id")
        cached_mtime = get_setting(f"{cache_key_prefix}_mtime")
        is_custom = get_setting(f"{cache_key_prefix}_custom") == "true"
        
        disk_file_exists = video_path and os.path.exists(video_path)
        disk_mtime = str(os.path.getmtime(video_path)) if disk_file_exists else None
        
        # If we have a cached id, and either is_custom is set, OR no disk file exists, OR disk file hasn't changed
        if cached_id and (is_custom or not disk_file_exists or cached_mtime == disk_mtime):
            print(f"[MediaHelper] Sending cached file_id for '{cache_key_prefix}'")
            try:
                return await client.send_video(
                    chat_id=chat_id,
                    video=cached_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    supports_streaming=True
                )
            except Exception as e:
                print(f"[MediaHelper] Cached send failed ({e}), clearing cache...")
                set_setting(f"{cache_key_prefix}_file_id", "")
                set_setting(f"{cache_key_prefix}_custom", "false")
                
        # Fallback to local file upload if no cached_id or mismatch or custom send failed
        if disk_file_exists:
            print(f"[MediaHelper] Uploading local file: {video_path}")
            sent_msg = await client.send_video(
                chat_id=chat_id,
                video=video_path,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                supports_streaming=True
            )
            if sent_msg and sent_msg.video:
                file_id = sent_msg.video.file_id
                set_setting(f"{cache_key_prefix}_file_id", file_id)
                set_setting(f"{cache_key_prefix}_mtime", disk_mtime)
                set_setting(f"{cache_key_prefix}_custom", "false")
                print(f"[MediaHelper] Cached new file_id: {file_id}")
            return sent_msg

        return await client.send_message(chat_id, caption, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        print(f"[MediaHelper] Error sending video: {e}")
        return await client.send_message(chat_id, caption, reply_markup=reply_markup, parse_mode=parse_mode)
