import os
import json
import asyncio
from datetime import datetime
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# === BOT CONFIG ===
api_id = 21845583  # Replace with your API ID
api_hash = "081a3cc51a428ad292be0be4d4f4f975"  # Replace with your API hash
bot_token = "8523604881:AAF7lmOn0RDaIInGrt_BNlyJ09HQeWg5i-4"  # Replace with your bot token

app = Client("UptimeX_Bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

# === DATABASE PATH ===
DB_PATH = "monitors.json"
if os.path.exists(DB_PATH):
    with open(DB_PATH, "r") as f:
        db = json.load(f)
else:
    db = {}

# === Save DB ===
def save_db():
    with open(DB_PATH, "w") as f:
        json.dump(db, f, indent=2)

# === Session Memory ===
user_states = {}  # {user_id: {"state": str, "temp": {}}}

# === Auth Check ===
def is_logged_in(user_id):
    return str(user_id) in db and db[str(user_id)].get("logged_in")

# === UI Buttons ===
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 My Monitors", callback_data="my_monitors")],
        [InlineKeyboardButton("➕ Add Monitor", callback_data="add_monitor")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
         InlineKeyboardButton("❌ Logout", callback_data="logout")]
    ])

@app.on_message(filters.command("start"))
async def start(client, message: Message):
    user_id = str(message.from_user.id)
    if user_id not in db:
        db[user_id] = {"registered": False, "logged_in": False, "monitors": []}
        save_db()
    if db[user_id]["logged_in"]:
        await message.reply("✅ Welcome back to UptimeX!", reply_markup=main_menu())
    else:
        await message.reply("👋 Welcome to **UptimeX** — your smart link monitor bot.\n\nPlease choose:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 Register", callback_data="register")],
                [InlineKeyboardButton("🔐 Login", callback_data="login")]
            ])
        )

@app.on_callback_query()
async def handle_buttons(client, callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    data = callback.data

    if data == "register":
        user_states[user_id] = {"state": "awaiting_register_username", "temp": {}}
        await callback.message.edit("🆕 Enter a desired username:")

    elif data == "login":
        user_states[user_id] = {"state": "awaiting_login_username", "temp": {}}
        await callback.message.edit("👤 Enter your username:")

    elif data == "logout":
        db[user_id]["logged_in"] = False
        save_db()
        await callback.message.edit("🚪 You have been logged out. Send /start to log in again.")

    elif data == "add_monitor":
        if not is_logged_in(user_id): return
        user_states[user_id] = {"state": "awaiting_monitor_url", "temp": {}}
        await callback.message.edit("🌐 Send the full URL to monitor (start with http:// or https://):")

    elif data == "my_monitors":
        if not is_logged_in(user_id): return
        monitors = db[user_id].get("monitors", [])
        if not monitors:
            await callback.message.edit("ℹ️ You have no active monitors yet.", reply_markup=main_menu())
            return
        msg = "📊 **Your Monitors:**\n"
        for i, m in enumerate(monitors):
            msg += (
                f"\n🔢 **#{i+1}**\n"
                f"🔗 URL: {m['url']}\n"
                f"📶 Status: {m['status']}\n"
                f"⏱ Interval: {m['interval']}s\n"
                f"📅 Last Check: {m['last_check']}\n"
                f"⚡ Response Time: {m['response_time']} ms\n"
            )
        await callback.message.edit(msg, reply_markup=main_menu())

    elif data == "settings":
        await callback.message.edit("⚙️ Settings panel coming soon!", reply_markup=main_menu())

@app.on_message(filters.text)
async def handle_user_input(client, message: Message):
    user_id = str(message.from_user.id)
    if user_id not in user_states:
        return

    state = user_states[user_id]["state"]
    temp = user_states[user_id]["temp"]
    text = message.text.strip()

    # === Register ===
    if state == "awaiting_register_username":
        temp["username"] = text
        user_states[user_id]["state"] = "awaiting_register_password"
        await message.reply("🔑 Enter a password:")

    elif state == "awaiting_register_password":
        temp["password"] = text
        db[user_id] = {
            "username": temp["username"],
            "password": temp["password"],
            "logged_in": True,
            "monitors": []
        }
        save_db()
        user_states.pop(user_id)
        await message.reply("🎉 Registration successful! You're now logged in.", reply_markup=main_menu())

    # === Login ===
    elif state == "awaiting_login_username":
        temp["username"] = text
        user_states[user_id]["state"] = "awaiting_login_password"
        await message.reply("🔒 Enter your password:")

    elif state == "awaiting_login_password":
        username = temp["username"]
        password = text
        for uid, info in db.items():
            if info.get("username") == username and info.get("password") == password:
                db[uid]["logged_in"] = True
                save_db()
                user_states.pop(user_id)
                await message.reply("✅ Logged in successfully!", reply_markup=main_menu())
                return
        user_states.pop(user_id)
        await message.reply("❌ Invalid credentials. Use /start to try again.")

    # === Add Monitor ===
    elif state == "awaiting_monitor_url":
        if not text.startswith("http"):
            await message.reply("❌ Invalid URL. Must start with http:// or https://")
            return
        temp["url"] = text
        user_states[user_id]["state"] = "awaiting_monitor_interval"
        await message.reply("⏱️ Enter interval in seconds (e.g. 60):")

    elif state == "awaiting_monitor_interval":
        try:
            interval = int(text)
        except:
            await message.reply("❌ Invalid number. Try again.")
            return
        url = temp["url"]
        monitor = {
            "url": url,
            "interval": interval,
            "status": "🟡 Starting...",
            "uptime": 100.0,
            "last_check": "-",
            "response_time": "-"
        }
        db[user_id]["monitors"].append(monitor)
        save_db()
        await message.reply(f"✅ **Monitor Added!**\n\n🔗 URL: {url}\n⏱ Interval: {interval}s\n📡 Status: Starting...", reply_markup=main_menu())
        asyncio.create_task(ping_url(user_id, len(db[user_id]["monitors"]) - 1))
        user_states.pop(user_id)

# === Monitor Pinger ===
async def ping_url(user_id, index):
    uid = str(user_id)
    while True:
        try:
            monitor = db[uid]["monitors"][index]
        except IndexError:
            return

        url = monitor["url"]
        interval = monitor["interval"]

        try:
            async with aiohttp.ClientSession() as session:
                start = datetime.now()
                async with session.get(url, timeout=10) as resp:
                    end = datetime.now()
                    rtime = int((end - start).total_seconds() * 1000)
                    db[uid]["monitors"][index]["status"] = "🟢 Online"
                    db[uid]["monitors"][index]["response_time"] = rtime
                    db[uid]["monitors"][index]["last_check"] = end.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            db[uid]["monitors"][index]["status"] = "🔴 Down"
            db[uid]["monitors"][index]["response_time"] = "-"
            db[uid]["monitors"][index]["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        save_db()
        await asyncio.sleep(interval)

app.run()
