import os
import sqlite3
import time

DB_PATH = "gameover_yt_music.sqlite3"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Table to cache resolved/downloaded YouTube videos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS downloaded_cache (
            video_id TEXT,
            mode TEXT,
            file_path TEXT,
            title TEXT,
            thumbnail TEXT,
            duration INTEGER,
            timestamp REAL,
            PRIMARY KEY (video_id, mode)
        )
    """)
    
    # Migration helper for existing DBs missing new columns
    for col_name, col_type in [("thumbnail", "TEXT"), ("duration", "INTEGER")]:
        try:
            cursor.execute(f"ALTER TABLE downloaded_cache ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass
    
    # Table for Sudo users
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sudo_users (
            user_id INTEGER PRIMARY KEY
        )
    """)

    # Table for Authorized users in groups
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_users (
            chat_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
    """)

    # Table for Allowed Groups
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allowed_groups (
            chat_id INTEGER PRIMARY KEY
        )
    """)

    # Table for bot settings
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Table for broadcast groups
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS broadcast_groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            enabled INTEGER DEFAULT 1,
            welcome_enabled INTEGER DEFAULT 1,
            start_enabled INTEGER DEFAULT 1,
            bot_active INTEGER DEFAULT 1
        )
    """)

    # Migration for start_enabled column
    try:
        cursor.execute("ALTER TABLE broadcast_groups ADD COLUMN start_enabled INTEGER DEFAULT 1")
    except Exception:
        pass

    # Table for playlist tracklist caching
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS playlist_cache (
            playlist_id TEXT PRIMARY KEY,
            tracks_json TEXT,
            timestamp REAL
        )
    """)

    # Table for playlist playback state tracking per chat & playlist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS playlist_state (
            chat_id INTEGER,
            playlist_id TEXT,
            mode TEXT,
            last_index INTEGER,
            total_tracks INTEGER,
            last_updated REAL,
            title TEXT,
            PRIMARY KEY (chat_id, playlist_id, mode)
        )
    """)

    # Migration helper for playlist_state
    try:
        cursor.execute("ALTER TABLE playlist_state ADD COLUMN title TEXT")
    except Exception:
        pass

    # Table for Started Users in Private Chat
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS started_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            timestamp REAL
        )
    """)

    # Table for Approved Control Users in groups
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approved_users (
            chat_id INTEGER,
            user_id INTEGER,
            user_name TEXT,
            approved_by INTEGER,
            added_at REAL,
            PRIMARY KEY (chat_id, user_id)
        )
    """)
    # Table for bot PM users
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_pm_users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            joined_at REAL
        )
    """)
    conn.commit()
    conn.close()
    print("[DB] Database initialized successfully!")

def add_pm_user(user_id: int, first_name: str, username: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO bot_pm_users (user_id, first_name, username, joined_at) VALUES (?, ?, ?, ?)",
            (user_id, first_name or "", username or "", time.time())
        )
        conn.commit()
    except Exception as e:
        print(f"[DB] Error add_pm_user: {e}")
    finally:
        conn.close()

def get_total_pm_users() -> int:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM bot_pm_users")
        row = cursor.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0
    finally:
        conn.close()

def get_total_groups_count() -> int:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM broadcast_groups")
        row = cursor.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0
    finally:
        conn.close()

def save_playlist_to_cache(playlist_id: str, tracks: list):
    """Save parsed playlist tracklist into SQLite database."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        import json
        tracks_json = json.dumps(tracks)
        cursor.execute(
            "INSERT OR REPLACE INTO playlist_cache (playlist_id, tracks_json, timestamp) VALUES (?, ?, ?)",
            (playlist_id, tracks_json, time.time())
        )
        conn.commit()
        print(f"[DB] Saved playlist '{playlist_id}' ({len(tracks)} tracks) to cache DB.")
    except Exception as e:
        print(f"[DB] Error saving playlist cache: {e}")
    finally:
        conn.close()

def get_cached_playlist(playlist_id: str) -> list or None:
    """Retrieve cached playlist tracklist from SQLite database."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT tracks_json FROM playlist_cache WHERE playlist_id = ?", (playlist_id,))
        row = cursor.fetchone()
        if row and row[0]:
            import json
            tracks = json.loads(row[0])
            print(f"[DB] Instant Playlist Cache Hit! Retrieved {len(tracks)} tracks for '{playlist_id}'.")
            return tracks
    except Exception as e:
        print(f"[DB] Error getting cached playlist: {e}")
    finally:
        conn.close()
    return None

def save_playlist_state(chat_id: int, playlist_id: str, mode: str, last_index: int, total_tracks: int, title: str = None):
    """Save current playlist progress for a chat into SQLite DB."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO playlist_state (chat_id, playlist_id, mode, last_index, total_tracks, last_updated, title) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chat_id, playlist_id, mode, last_index, total_tracks, time.time(), title)
        )
        conn.commit()
    except Exception as e:
        print(f"[DB] Error saving playlist state: {e}")
    finally:
        conn.close()

def get_playlist_state(chat_id: int, mode: str = None, playlist_id: str = None) -> dict or None:
    """Get saved playlist progress for a chat."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        if playlist_id:
            if mode:
                cursor.execute(
                    "SELECT playlist_id, mode, last_index, total_tracks, last_updated, title FROM playlist_state WHERE chat_id = ? AND playlist_id = ? AND mode = ?",
                    (chat_id, playlist_id, mode)
                )
            else:
                cursor.execute(
                    "SELECT playlist_id, mode, last_index, total_tracks, last_updated, title FROM playlist_state WHERE chat_id = ? AND playlist_id = ? ORDER BY last_updated DESC LIMIT 1",
                    (chat_id, playlist_id)
                )
        else:
            if mode:
                cursor.execute(
                    "SELECT playlist_id, mode, last_index, total_tracks, last_updated, title FROM playlist_state WHERE chat_id = ? AND mode = ? ORDER BY last_updated DESC LIMIT 1",
                    (chat_id, mode)
                )
            else:
                cursor.execute(
                    "SELECT playlist_id, mode, last_index, total_tracks, last_updated, title FROM playlist_state WHERE chat_id = ? ORDER BY last_updated DESC LIMIT 1",
                    (chat_id,)
                )
        row = cursor.fetchone()
        if row:
            keys = row.keys()
            title_val = row["title"] if "title" in keys else None
            return {
                "playlist_id": row["playlist_id"],
                "mode": row["mode"],
                "last_index": row["last_index"],
                "total_tracks": row["total_tracks"],
                "last_updated": row["last_updated"],
                "title": title_val
            }
    except Exception as e:
        print(f"[DB] Error getting playlist state: {e}")
    finally:
        conn.close()
    return None

def get_all_playlist_states(chat_id: int) -> list:
    """Get all saved playlists for a chat sorted by last_updated descending."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT playlist_id, mode, last_index, total_tracks, last_updated, title FROM playlist_state WHERE chat_id = ? ORDER BY last_updated DESC LIMIT 10",
            (chat_id,)
        )
        rows = cursor.fetchall()
        result = []
        for r in rows:
            keys = r.keys()
            t_val = r["title"] if "title" in keys else None
            result.append({
                "playlist_id": r["playlist_id"],
                "mode": r["mode"],
                "last_index": r["last_index"],
                "total_tracks": r["total_tracks"],
                "last_updated": r["last_updated"],
                "title": t_val
            })
        return result
    except Exception as e:
        print(f"[DB] Error get_all_playlist_states: {e}")
        return []
    finally:
        conn.close()

def clear_playlist_state(chat_id: int, mode: str = None, playlist_id: str = None):
    """Clear saved playlist progress for a chat."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        if playlist_id:
            cursor.execute("DELETE FROM playlist_state WHERE chat_id = ? AND playlist_id = ?", (chat_id, playlist_id))
        elif mode:
            cursor.execute("DELETE FROM playlist_state WHERE chat_id = ? AND mode = ?", (chat_id, mode))
        else:
            cursor.execute("DELETE FROM playlist_state WHERE chat_id = ?", (chat_id,))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error clearing playlist state: {e}")
    finally:
        conn.close()

def reset_all_db_caches():
    """Wipe all playlist states, downloaded cache, and playlist cache from DB."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM playlist_state")
        cursor.execute("DELETE FROM downloaded_cache")
        cursor.execute("DELETE FROM playlist_cache")
        conn.commit()
        print("[DB] All caches & playlist states wiped clean.")
    except Exception as e:
        print(f"[DB] Error in reset_all_db_caches: {e}")
    finally:
        conn.close()

def save_to_cache(video_id: str, mode: str, file_path: str, title: str, thumbnail: str = "", duration: int = 0):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO downloaded_cache (video_id, mode, file_path, title, thumbnail, duration, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (video_id, mode, file_path, title, thumbnail, duration, time.time())
        )
        conn.commit()
        print(f"[DB] Saved {video_id} ({mode}) to cache DB.")
    except Exception as e:
        print(f"[DB] Error saving to cache: {e}")
    finally:
        conn.close()

def get_cached_path(video_id: str, mode: str) -> str:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT file_path FROM downloaded_cache WHERE video_id = ? AND mode = ?",
            (video_id, mode)
        )
        row = cursor.fetchone()
        if row and os.path.exists(row["file_path"]):
            return row["file_path"]
        # Delete invalid entry if file does not exist on disk
        if row:
            cursor.execute(
                "DELETE FROM downloaded_cache WHERE video_id = ? AND mode = ?",
                (video_id, mode)
            )
            conn.commit()
        return None
    except Exception as e:
        print(f"[DB] Error fetching from cache: {e}")
        return None
    finally:
        conn.close()

def get_cached_item(video_id: str, mode: str) -> dict:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT file_path, title, thumbnail, duration FROM downloaded_cache WHERE video_id = ? AND mode = ?",
            (video_id, mode)
        )
        row = cursor.fetchone()
        if row and os.path.exists(row["file_path"]):
            keys = row.keys()
            thumb = row["thumbnail"] if "thumbnail" in keys else None
            dur = row["duration"] if "duration" in keys else 0
            return {
                "file_path": row["file_path"],
                "title": row["title"],
                "thumbnail": thumb,
                "duration": dur
            }
        # Delete invalid entry if file does not exist on disk
        if row:
            cursor.execute(
                "DELETE FROM downloaded_cache WHERE video_id = ? AND mode = ?",
                (video_id, mode)
            )
            conn.commit()
        return None
    except Exception as e:
        print(f"[DB] Error fetching item from cache: {e}")
        return None
    finally:
        conn.close()

def get_from_cache(video_id: str, mode: str) -> dict:
    """Alias for get_cached_item."""
    return get_cached_item(video_id, mode)

# ─── Settings Helpers ───────────────────────────────────
def get_setting(key: str) -> str:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else None
    finally:
        conn.close()

def set_setting(key: str, value: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    finally:
        conn.close()

# ─── Sudo Users Helpers ─────────────────────────────────
def add_sudo_user(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO sudo_users (user_id) VALUES (?)", (user_id,))
        conn.commit()
    finally:
        conn.close()

def remove_sudo_user(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM sudo_users WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()

def is_sudo_user(user_id: int) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM sudo_users WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None
    finally:
        conn.close()

# ─── Broadcast Groups Helpers ───────────────────────────
def update_group_info(chat_id: int, title: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO broadcast_groups (chat_id, title, enabled) VALUES (?, ?, 1)", (chat_id, title))
        cursor.execute("UPDATE broadcast_groups SET title = ? WHERE chat_id = ?", (title, chat_id))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error update_group_info: {e}")
    finally:
        conn.close()

def remove_group_info(chat_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM broadcast_groups WHERE chat_id = ?", (chat_id,))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error remove_group_info: {e}")
    finally:
        conn.close()

def get_broadcast_groups() -> list:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT chat_id, title, enabled, welcome_enabled, bot_active FROM broadcast_groups")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DB] Error get_broadcast_groups: {e}")
        return []
    finally:
        conn.close()

def set_group_broadcast_enabled(chat_id: int, enabled: bool):
    conn = get_db()
    cursor = conn.cursor()
    val = 1 if enabled else 0
    try:
        cursor.execute("UPDATE broadcast_groups SET enabled = ? WHERE chat_id = ?", (val, chat_id))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error set_group_broadcast_enabled: {e}")
    finally:
        conn.close()

def set_group_welcome_enabled(chat_id: int, enabled: bool):
    conn = get_db()
    cursor = conn.cursor()
    val = 1 if enabled else 0
    try:
        cursor.execute("UPDATE broadcast_groups SET welcome_enabled = ? WHERE chat_id = ?", (val, chat_id))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error set_group_welcome_enabled: {e}")
    finally:
        conn.close()

def is_group_welcome_enabled(chat_id: int) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT welcome_enabled FROM broadcast_groups WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row and row["welcome_enabled"] is not None:
            return bool(row["welcome_enabled"])
        return True
    except Exception:
        return True
    finally:
        conn.close()

def set_group_start_enabled(chat_id: int, enabled: bool):
    conn = get_db()
    cursor = conn.cursor()
    val = 1 if enabled else 0
    try:
        cursor.execute("UPDATE broadcast_groups SET start_enabled = ? WHERE chat_id = ?", (val, chat_id))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error set_group_start_enabled: {e}")
    finally:
        conn.close()

def is_group_start_enabled(chat_id: int) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT start_enabled FROM broadcast_groups WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row and row["start_enabled"] is not None:
            return bool(row["start_enabled"])
        return True
    except Exception:
        return True
    finally:
        conn.close()

def set_group_bot_active(chat_id: int, active: bool):
    conn = get_db()
    cursor = conn.cursor()
    val = 1 if active else 0
    try:
        cursor.execute("UPDATE broadcast_groups SET bot_active = ? WHERE chat_id = ?", (val, chat_id))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error set_group_bot_active: {e}")
    finally:
        conn.close()

def is_group_bot_active(chat_id: int) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT bot_active FROM broadcast_groups WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row and row["bot_active"] is not None:
            return bool(row["bot_active"])
        return True
    except Exception:
        return True
    finally:
        conn.close()

# ─── Approved Control Users Helpers ───────────────────────
def add_approved_user(chat_id: int, user_id: int, user_name: str, approved_by: int):
    """Add a user to the approved control users table for a specific chat."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO approved_users (chat_id, user_id, user_name, approved_by, added_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, user_id, user_name, approved_by, time.time())
        )
        conn.commit()
        print(f"[DB] Added approved control user {user_id} ({user_name}) for chat {chat_id}")
    except Exception as e:
        print(f"[DB] Error adding approved user: {e}")
    finally:
        conn.close()

def remove_approved_user(chat_id: int, user_id: int):
    """Remove a user from the approved control users table for a specific chat."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM approved_users WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        conn.commit()
        print(f"[DB] Removed approved control user {user_id} for chat {chat_id}")
    except Exception as e:
        print(f"[DB] Error removing approved user: {e}")
    finally:
        conn.close()

def get_approved_users(chat_id: int = 0) -> list:
    """Get list of approved control users for a specific chat or all chats if chat_id is 0."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        if chat_id:
            cursor.execute("SELECT chat_id, user_id, user_name, approved_by, added_at FROM approved_users WHERE chat_id = ?", (chat_id,))
        else:
            cursor.execute("SELECT chat_id, user_id, user_name, approved_by, added_at FROM approved_users")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DB] Error fetching approved users: {e}")
        return []
    finally:
        conn.close()

def is_user_approved(chat_id: int, user_id: int) -> bool:
    """Check if a user is an approved control user for a specific chat."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM approved_users WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return cursor.fetchone() is not None
    except Exception as e:
        print(f"[DB] Error checking approved user: {e}")
        return False
    finally:
        conn.close()

# ─── Started Users Helpers ──────────────────────────────
def add_started_user(user_id: int, username: str, first_name: str) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM started_users WHERE user_id = ?", (user_id,))
        if cursor.fetchone():
            return False
        cursor.execute(
            "INSERT OR IGNORE INTO started_users (user_id, username, first_name, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, username, first_name, time.time())
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] Error add_started_user: {e}")
        return False
    finally:
        conn.close()

def get_setting(key: str, default: str = "") -> str:
    """Get setting value from SQLite DB."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default
    except Exception:
        return default
    finally:
        conn.close()

def save_setting(key: str, value: str):
    """Save/update setting value in SQLite DB."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error save_setting: {e}")
    finally:
        conn.close()

# Auto init database on import
init_db()
