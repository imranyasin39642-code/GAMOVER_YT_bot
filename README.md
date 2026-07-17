# 👑 GameOver YT Streamer

A premium, high-performance Telegram group video and audio streamer bot using PyTgCalls.

## Features
- 🎬 High-speed video streaming (720p 60fps locked)
- 🎵 High-fidelity audio streaming
- 🔍 Automatic YouTube Search fallback (no API key needed)
- 📊 Interactive Now Playing cards with live progress bars and controls
- 👑 Sudo & Admin authorization rules

## VPS Setup Instructions
1. Clone the repository on your VPS:
   ```bash
   git clone https://github.com/imranyasin39642-code/GAMOVER_YT_bot.git
   cd GAMOVER_YT_bot
   ```
2. Install system dependencies (FFmpeg):
   ```bash
   sudo apt update && sudo apt install ffmpeg -y
   ```
3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create your `.env` file (see Configuration section below).
5. Start the bot:
   ```bash
   python bot.py
   ```

## Configuration (.env)
Create a `.env` file in the root directory:
```env
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
STRING_SESSION=your_pyrogram_assistant_session_string
OWNER_ID=your_telegram_user_id
```
