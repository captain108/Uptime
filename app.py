import os
import asyncio
import random
import time
from datetime import datetime
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient

# ================= CONFIG ================= #
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

SLOW_THRESHOLD = 2000  # ms

app = Client("UptimeX_Bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo["uptime_bot"]
users_col = db["users"]

tasks = {}
user_states = {}

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
def start_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Register", callback_data="reg")],
        [InlineKeyboardButton("Login", callback_data="login")]
    ])

def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("My Monitors", callback_data="my"),
            InlineKeyboardButton("Add Monitor", callback_data="add")
        ],
        [
            InlineKeyboardButton("Check All", callback_data="check_all")
        ]
    ])

# ================= START ================= #
@app.on_message(filters.command("start"))
async def start(client, message):
    uid = message.from_user.id
    user = await get_user(uid)

    if user and user.get("logged_in"):
        await message.reply("Welcome back!", reply_markup=main_menu())
    else:
        await message.reply("Welcome! Choose an option:", reply_markup=start_buttons())

# ================= CALLBACK ================= #
@app.on_callback_query()
async def cb(client, q):
    uid = q.from_user.id
    data = q.data
    user = await get_user(uid)

    # ===== AUTH =====
    if data == "reg":
        user_states[uid] = {"state": "reg_user"}
        await q.message.reply("Enter username:")

    elif data == "login":
        user_states[uid] = {"state": "login_user"}
        await q.message.reply("Enter username:")

    # ===== MAIN =====
    elif data == "add":
        if not user.get("logged_in"):
            return await q.message.reply("Please login first")

        user_states[uid] = {"state": "url"}
        await q.message.reply("Enter URL:")

    elif data == "my":
        if not user["monitors"]:
            return await q.message.reply("No monitors found")

        for i, m in enumerate(user["monitors"]):
            await q.message.reply(
                f"""
URL: {m['url']}
Status: {m['status']}
Ping: {m.get('ping','-')} ms
Avg: {m.get('avg_ping','-')} ms
Uptime: {m['uptime']}%
""",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Details", callback_data=f"detail_{i}")],
                    [InlineKeyboardButton("Delete", callback_data=f"del_{i}")]
                ])
            )

    elif data.startswith("detail_"):
        i = int(data.split("_")[1])
        m = user["monitors"][i]

        await q.message.reply(f"""
Detailed Report

URL: {m['url']}
Status: {m['status']}
Ping: {m.get('ping','-')} ms
Average Ping: {m.get('avg_ping','-')} ms
Uptime: {m['uptime']}%
Total Checks: {m['total']}
Success: {m['success']}
""")

    elif data.startswith("del_"):
        i = int(data.split("_")[1])
        user["monitors"].pop(i)
        await update_user(uid, {"monitors": user["monitors"]})
        await q.message.reply("Deleted")

    elif data == "check_all":
        async def check(m):
            try:
                start = datetime.now()
                async with aiohttp.ClientSession() as s:
                    async with s.head(m["url"], timeout=5):
                        end = datetime.now()
                        ms = int((end - start).total_seconds() * 1000)
                        return f"🟢 {m['url']} ({ms} ms)"
            except:
                return f"🔴 {m['url']}"

        results = await asyncio.gather(*[check(m) for m in user["monitors"]])
        await q.message.reply("\n".join(results[:20]))

# ================= INPUT ================= #
@app.on_message(filters.text)
async def input_handler(client, message):
    uid = message.from_user.id
    text = message.text

    if uid not in user_states:
        return

    state = user_states[uid]["state"]
    user = await get_user(uid)

    # REGISTER
    if state == "reg_user":
        user_states[uid] = {"state": "reg_pass", "username": text}
        await message.reply("Enter password:")

    elif state == "reg_pass":
        await users_col.update_one(
            {"user_id": str(uid)},
            {"$set": {"username": user_states[uid]["username"], "password": text, "logged_in": True, "monitors": []}},
            upsert=True
        )
        await message.reply("Registered successfully!", reply_markup=main_menu())
        user_states.pop(uid)

    # LOGIN
    elif state == "login_user":
        user_states[uid] = {"state": "login_pass", "username": text}
        await message.reply("Enter password:")

    elif state == "login_pass":
        if user and user.get("username") == user_states[uid]["username"] and user.get("password") == text:
            await update_user(uid, {"logged_in": True})
            await message.reply("Login successful!", reply_markup=main_menu())
        else:
            await message.reply("Invalid credentials")
        user_states.pop(uid)

    # ADD MONITOR
    elif state == "url":
        user_states[uid] = {"state": "interval", "url": text}
        await message.reply("Enter interval (seconds):")

    elif state == "interval":
        interval = int(text)
        url = user_states[uid]["url"]

        monitor = {
            "url": url,
            "interval": interval,
            "status": "🟡",
            "uptime": 100,
            "total": 0,
            "success": 0,
            "alerts": True,
            "ping_history": []
        }

        user["monitors"].append(monitor)
        await update_user(uid, {"monitors": user["monitors"]})

        i = len(user["monitors"]) - 1
        tasks[(uid, i)] = asyncio.create_task(ping(uid, i))

        await message.reply("Monitor added!")
        user_states.pop(uid)

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
                    end = datetime.now()
                    ms = int((end - start).total_seconds() * 1000)

                    status = "🟢"
                    m["success"] += 1
                    m["ping"] = ms
        except:
            status = "🔴"
            m["ping"] = "-"

        m["total"] += 1
        m["uptime"] = round((m["success"] / m["total"]) * 100, 2)
        m["status"] = status

        # avg ping
        if m["ping"] != "-":
            m["ping_history"].append(m["ping"])
            m["ping_history"] = m["ping_history"][-20:]
            m["avg_ping"] = int(sum(m["ping_history"]) / len(m["ping_history"]))

        # slow alert
        now = time.time()
        if m.get("ping") != "-" and m["ping"] > SLOW_THRESHOLD:
            if now - m.get("last_slow_alert", 0) > 300:
                await app.send_message(uid, f"⚠️ Slow response: {m['url']} ({m['ping']} ms)")
                m["last_slow_alert"] = now

        # prediction
        if len(m["ping_history"]) >= 5:
            if all(p > SLOW_THRESHOLD for p in m["ping_history"][-5:]):
                await app.send_message(uid, f"⚠️ Prediction: {m['url']} may go DOWN")

        if last != status:
            await update_user(uid, {"monitors": user["monitors"]})

        last = status
        await asyncio.sleep(m["interval"])

# ================= RUN ================= #
app.run()
