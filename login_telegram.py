import json
import asyncio
from telethon import TelegramClient

with open("config.json", "r") as f:
    config = json.load(f)

api_id = config["telegram"]["api_id"]
api_hash = config["telegram"]["api_hash"]

client = TelegramClient("telethon_session", api_id, api_hash)

async def main():
    print("="*60)
    print("TELEGRAM ONE-TIME AUTHENTICATION")
    print("Enter your phone number (with country code, e.g. +91XXXXXXXXXX)")
    print("Then enter the login code Telegram sends to your app.")
    print("="*60)
    await client.start()
    me = await client.get_me()
    print("\n" + "="*60)
    print(f"SUCCESS! Logged in as: {me.first_name} (@{me.username})")
    print("Session is saved as 'telethon_session.session'.")
    print("You can now close this window and run the automation pipeline!")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
