import asyncio
from pyrogram import Client

async def main():
    print("=== Pyrogram String Session Generator ===")
    print("Aapki API_ID aur API_HASH default use kiye ja rahe hain jo aapne diye hain.\n")
    
    # Pre-filled values provided by the user
    api_id = 37206917
    api_hash = "bad0181a6c1149585fc8211485b57a7d"
    
    print(f"API_ID: {api_id}")
    print(f"API_HASH: {api_hash}\n")
    
    # Use in_memory=True to avoid Windows file creation issues with ":memory:" session name
    async with Client("temp_session", api_id=api_id, api_hash=api_hash, in_memory=True) as app:
        session_str = await app.export_session_string()
        print("\n=============================================")
        print("✅ SUCCESS: Aapka String Session generate ho gaya hai!")
        print("=============================================\n")
        print(session_str)
        print("\n=============================================")
        print("⚠️  Security Warning: Is string ko kisi ke sath share na karein.")
        print("Ise copy karke apne .env file mein 'STRING_SESSION' ki jagah paste kar dein.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled by user.")
