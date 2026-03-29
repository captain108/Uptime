import os
import asyncio
import time
from datetime import datetime
import aiohttp
from flask import Flask
import threading

from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient

# ================= CONFIG ================= #
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

SLOW_THRESHOLD = 2000
PAGE_SIZE = 3

app = Client("UptimeX", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo["uptime_bot"]
users_col = db["users"]

tasks = {}
user_states = {}

# ================= FLASK ================= #
web = Flask(__name__)

@web.route("/")
def home():
    return "🚀 Bot Running"

def run_web():
    web.run(host="0.0.0.0", port=8000)

threading.Thread(target=run_web, daemon=True).start()

# ================= DB ================= #
async def get_user(uid):
    return await users_col.find_one({"user_id": str(uid)})

async def create_user(uid):
    await users_col.update_one(
        {"user_id": str(uid)},
        {"$setOnInsert": {"monitors": []}},
        upsert=True
    )

async def update_user(uid, data):
    await users_col.update_one({"user_id": str(uid)}, {"$set": data})

# ================= UI ================= #
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Monitors", callback_data="my_0")],
        [InlineKeyboardButton("➕ Add Monitor", callback_data="add")],
        [InlineKeyboardButton("⚡ Check All", callback_data="check_all")]
    ])

def monitor_card(i, m):
    icon = "🟢" if m["status"] == "🟢" else "🔴"
    return f"""
╭━━ 🌐 Monitor #{i+1} ━━╮
🔗 {m['url']}
{icon} Status : {m['status']}
⚡ Ping   : {m.get('ping','-')} ms
📊 Uptime : {m['uptime']}%
╰━━━━━━━━━━━━━━━━━━╯
"""

# ================= START ================= #
@app.on_message(filters.command("start"))
async def start(client, message):
    uid = message.from_user.id
    await create_user(uid)

    await message.reply(
        "🚀 UptimeX Monitor",
        reply_markup=main_menu()
    )

# ================= CALLBACK ================= #
@app.on_callback_query()
async def cb(client, q):
    uid = q.from_user.id
    data = q.data
    user = await get_user(uid)

    # ADD
    if data == "add":
        user_states[uid] = {"state": "url"}
        return await q.message.edit_text("🌐 Send URL:")

    # MONITORS
    elif data.startswith("my_"):
        page = int(data.split("_")[1])
        monitors = user["monitors"]

        if not monitors:
            return await q.message.edit_text("❌ No monitors", reply_markup=main_menu())

        start_i = page * PAGE_SIZE
        end_i = start_i + PAGE_SIZE

        text = f"📊 Monitors (Page {page+1})\n\n"

        for i, m in enumerate(monitors[start_i:end_i], start=start_i):
            text += monitor_card(i, m)

        buttons = []

        for i in range(start_i, min(end_i, len(monitors))):
            buttons.append([
                InlineKeyboardButton("✏️ Edit", callback_data=f"edit_{i}"),
                InlineKeyboardButton("🗑 Delete", callback_data=f"del_{i}")
            ])

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅ Prev", callback_data=f"my_{page-1}"))
        if end_i < len(monitors):
            nav.append(InlineKeyboardButton("Next ➡", callback_data=f"my_{page+1}"))

        if nav:
            buttons.append(nav)

        buttons.append([
            InlineKeyboardButton("🔄 Refresh", callback_data=f"my_{page}"),
            InlineKeyboardButton("🏠 Menu", callback_data="menu")
        ])

        return await q.message.edit_text(text[:4000], reply_markup=InlineKeyboardMarkup(buttons))

    # EDIT MENU
    elif data.startswith("edit_"):
        i = int(data.split("_")[1])
        return await q.message.edit_text(
            "✏️ Edit Options",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 Edit URL", callback_data=f"editurl_{i}")],
                [InlineKeyboardButton("⏱ Edit Interval", callback_data=f"editint_{i}")],
                [InlineKeyboardButton("⬅ Back", callback_data="my_0")]
            ])
        )

    # EDIT URL
    elif data.startswith("editurl_"):
        i = int(data.split("_")[1])
        user_states[uid] = {"state": "edit_url", "index": i}
        return await q.message.edit_text("🌐 Send new URL:")

    # EDIT INTERVAL
    elif data.startswith("editint_"):
        i = int(data.split("_")[1])
        user_states[uid] = {"state": "edit_interval", "index": i}
        return await q.message.edit_text("⏱ Send new interval:")

    # DELETE
    elif data.startswith("del_"):
        i = int(data.split("_")[1])

        task = tasks.get((uid, i))
        if task:
            task.cancel()

        user["monitors"].pop(i)
        await update_user(uid, {"monitors": user["monitors"]})

        return await q.message.edit_text("🗑 Deleted", reply_markup=main_menu())

    # MENU
    elif data == "menu":
        return await q.message.edit_text("🏠 Menu", reply_markup=main_menu())

    # CHECK ALL
    elif data == "check_all":
        await q.message.edit_text("⏳ Checking...")

        async def check(m):
            try:
                start = datetime.now()
                async with aiohttp.ClientSession() as s:
                    async with s.head(m["url"], timeout=5):
                        ms = int((datetime.now() - start).total_seconds() * 1000)
                        return f"🟢 {m['url']} ({ms} ms)"
            except:
                return f"🔴 {m['url']}"

        results = await asyncio.gather(*[check(m) for m in user["monitors"]])

        return await q.message.edit_text(
            "📊 Results\n\n" + "\n".join(results[:15]),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Menu", callback_data="menu")]
            ])
        )

# ================= INPUT ================= #
@app.on_message(filters.text)
async def input_handler(client, message):
    uid = message.from_user.id

    if uid not in user_states:
        return

    state = user_states[uid]["state"]
    user = await get_user(uid)

    # ADD
    if state == "url":
        user_states[uid] = {"state": "interval", "url": message.text}
        return await message.reply("⏱ Interval:")

    elif state == "interval":
        url = user_states[uid]["url"]
        interval = int(message.text)

        monitor = {
            "url": url,
            "interval": interval,
            "status": "🟡",
            "uptime": 100,
            "total": 0,
            "success": 0
        }

        user["monitors"].append(monitor)
        await update_user(uid, {"monitors": user["monitors"]})

        i = len(user["monitors"]) - 1
        tasks[(uid, i)] = asyncio.create_task(ping(uid, i))

        user_states.pop(uid)
        return await message.reply("✅ Added", reply_markup=main_menu())

    # EDIT URL
    elif state == "edit_url":
        i = user_states[uid]["index"]

        user["monitors"][i]["url"] = message.text
        await update_user(uid, {"monitors": user["monitors"]})

        # restart task
        if (uid, i) in tasks:
            tasks[(uid, i)].cancel()

        tasks[(uid, i)] = asyncio.create_task(ping(uid, i))

        user_states.pop(uid)
        return await message.reply("✅ URL Updated", reply_markup=main_menu())

    # EDIT INTERVAL
    elif state == "edit_interval":
        i = user_states[uid]["index"]

        try:
            interval = int(message.text)
        except:
            return await message.reply("❌ Invalid number")

        user["monitors"][i]["interval"] = interval
        await update_user(uid, {"monitors": user["monitors"]})

        # restart task
        if (uid, i) in tasks:
            tasks[(uid, i)].cancel()

        tasks[(uid, i)] = asyncio.create_task(ping(uid, i))

        user_states.pop(uid)
        return await message.reply("✅ Interval Updated", reply_markup=main_menu())

# ================= PING ================= #
async def ping(uid, i):
    last = None

    while True:
        user = await get_user(uid)
        if not user or i >= len(user["monitors"]):
            return

        m = user["monitors"][i]

        try:
            start = datetime.now()
            async with aiohttp.ClientSession() as s:
                async with s.head(m["url"], timeout=10):
                    ms = int((datetime.now() - start).total_seconds() * 1000)
                    status = "🟢"
                    m["success"] += 1
                    m["ping"] = ms
        except:
            status = "🔴"
            m["ping"] = "-"

        m["total"] += 1
        m["uptime"] = round((m["success"] / m["total"]) * 100, 2)
        m["status"] = status

        if last != status:
            await update_user(uid, {"monitors": user["monitors"]})

        last = status
        await asyncio.sleep(m["interval"])

# ================= RUN ================= #
async def main():
    await app.start()
    print("🤖 Bot Started")
    await idle()

asyncio.run(main())
