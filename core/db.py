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
            timestamp REAL,
            PRIMARY KEY (video_id, mode)
        )
    """)
    
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
            bot_active INTEGER DEFAULT 1
        )
    """)

    # Table for users who started the bot
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS started_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            timestamp REAL
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] Database initialized successfully!")

def save_to_cache(video_id: str, mode: str, file_path: str, title: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO downloaded_cache (video_id, mode, file_path, title, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (video_id, mode, file_path, title, time.time())
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
            "SELECT file_path, title FROM downloaded_cache WHERE video_id = ? AND mode = ?",
            (video_id, mode)
        )
        row = cursor.fetchone()
        if row and os.path.exists(row["file_path"]):
            return {"file_path": row["file_path"], "title": row["title"]}
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

# Auto init database on import
init_db()
