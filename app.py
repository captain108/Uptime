import os
import asyncio
import time
from datetime import datetime
import aiohttp
from flask import Flask
import threading

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient

# ================= CONFIG ================= #
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

SLOW_THRESHOLD = 2000

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
        {"$setOnInsert": {"monitors": [], "logged_in": True}},
        upsert=True
    )

async def update_user(uid, data):
    await users_col.update_one({"user_id": str(uid)}, {"$set": data})

# ================= UI ================= #
def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Monitors", callback_data="my")],
        [InlineKeyboardButton("➕ Add Monitor", callback_data="add")],
        [InlineKeyboardButton("⚡ Check All", callback_data="check_all")]
    ])

def monitor_card(i, m):
    return f"""
╭━━ 🌐 Monitor #{i+1} ━━╮
🔗 {m['url']}
🟢 Status : {m['status']}
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
        "🚀 Uptime Monitor\nKeep your sites alive 24/7",
        reply_markup=menu()
    )

# ================= CALLBACK ================= #
@app.on_callback_query()
async def cb(client, q):
    uid = q.from_user.id
    data = q.data
    user = await get_user(uid)

    # ===== ADD =====
    if data == "add":
        user_states[uid] = {"state": "url"}
        return await q.message.edit_text("🌐 Send URL:")

    # ===== MY MONITORS =====
    elif data == "my":
        if not user["monitors"]:
            return await q.message.edit_text("❌ No monitors found", reply_markup=menu())

        text = ""
        for i, m in enumerate(user["monitors"]):
            text += monitor_card(i, m) + "\n"

        return await q.message.edit_text(
            text[:4000],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="my")]
            ])
        )

    # ===== DETAIL =====
    elif data.startswith("detail_"):
        i = int(data.split("_")[1])
        m = user["monitors"][i]

        return await q.message.edit_text(f"""
🔍 Monitor Details

🔗 {m['url']}
🟢 Status : {m['status']}
⚡ Ping   : {m.get('ping','-')} ms
📊 Uptime : {m['uptime']}%

🧠 Checks : {m['total']}
""",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅ Back", callback_data="my")]
        ]))

    # ===== DELETE =====
    elif data.startswith("del_"):
        i = int(data.split("_")[1])
        user["monitors"].pop(i)
        await update_user(uid, {"monitors": user["monitors"]})

        return await q.message.edit_text("🗑 Deleted", reply_markup=menu())

    # ===== CHECK ALL =====
    elif data == "check_all":
        await q.message.edit_text("⚡ Checking...")

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
                [InlineKeyboardButton("⬅ Back", callback_data="my")]
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

    if state == "url":
        user_states[uid] = {"state": "interval", "url": message.text}
        return await message.reply("⏱ Interval (seconds):")

    elif state == "interval":
        url = user_states[uid]["url"]
        interval = int(message.text)

        monitor = {
            "url": url,
            "interval": interval,
            "status": "🟡",
            "uptime": 100,
            "total": 0,
            "success": 0,
            "alerts": True
        }

        user["monitors"].append(monitor)
        await update_user(uid, {"monitors": user["monitors"]})

        i = len(user["monitors"]) - 1
        tasks[(uid, i)] = asyncio.create_task(ping(uid, i))

        user_states.pop(uid)

        return await message.reply("✅ Monitor Added", reply_markup=menu())

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

        # slow alert
        now = time.time()
        if m.get("ping") != "-" and m["ping"] > SLOW_THRESHOLD:
            if now - m.get("last_slow_alert", 0) > 300:
                await app.send_message(uid, f"⚠️ Slow: {m['url']} ({m['ping']} ms)")
                m["last_slow_alert"] = now

        if last != status:
            await update_user(uid, {"monitors": user["monitors"]})

        last = status
        await asyncio.sleep(m["interval"])

# ================= RUN ================= #
app.run()
