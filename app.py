import os
import asyncio
import random
from datetime import datetime
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient

# ===== CONFIG =====
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

app = Client("UptimeX_Bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo["uptime_bot"]
users_col = db["users"]

tasks = {}
user_states = {}

# ===== PROXY =====
def load_proxies():
    if not os.path.exists("proxy.txt"):
        return []
    return [x.strip() for x in open("proxy.txt") if x.strip()]

proxies = load_proxies()
proxy_index = 0

def get_proxy():
    global proxy_index
    if not proxies:
        return None
    p = proxies[proxy_index % len(proxies)]
    proxy_index += 1
    return p

# ===== DB =====
async def get_user(uid):
    return await users_col.find_one({"user_id": str(uid)})

async def create_user(uid):
    await users_col.insert_one({"user_id": str(uid), "monitors": []})

async def update_user(uid, data):
    await users_col.update_one({"user_id": str(uid)}, {"$set": data})

# ===== UI =====
def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 My Monitors", callback_data="my")],
        [InlineKeyboardButton("➕ Add Monitor", callback_data="add")]
    ])

# ===== START =====
@app.on_message(filters.command("start"))
async def start(c, m):
    uid = m.from_user.id
    if not await get_user(uid):
        await create_user(uid)

    await m.reply("🚀 UptimeX Bot\nKeep your links alive 24/7", reply_markup=menu())

# ===== BUTTONS =====
@app.on_callback_query()
async def cb(c, q):
    uid = q.from_user.id
    data = q.data
    user = await get_user(uid)

    if data == "add":
        user_states[uid] = {"state": "url"}
        await q.message.reply("🌐 Send URL")

    elif data == "my":
        for i, m in enumerate(user["monitors"]):
            await q.message.reply(
                f"""╭━━ 🚀 Monitor ━━╮
🔗 {m['url']}
📶 {m['status']}
📊 {m['uptime']}%
⏱ {m['interval']}s
╰━━━━━━━━━━━━━━╯""",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✏️ Edit", callback_data=f"e_{i}"),
                        InlineKeyboardButton("🔔 Alert", callback_data=f"a_{i}")
                    ],
                    [
                        InlineKeyboardButton("🗑 Delete", callback_data=f"d_{i}")
                    ]
                ])
            )

    elif data.startswith("d_"):
        i = int(data.split("_")[1])
        user["monitors"].pop(i)
        await update_user(uid, {"monitors": user["monitors"]})
        await q.message.reply("🗑 Deleted")

    elif data.startswith("e_"):
        i = int(data.split("_")[1])
        user_states[uid] = {"state": "edit", "i": i}
        await q.message.reply("✏️ Send new URL")

    elif data.startswith("a_"):
        i = int(data.split("_")[1])
        cur = user["monitors"][i].get("alerts", True)
        user["monitors"][i]["alerts"] = not cur
        await update_user(uid, {"monitors": user["monitors"]})
        await q.message.reply(f"🔔 {'ON' if not cur else 'OFF'}")

# ===== INPUT =====
@app.on_message(filters.text)
async def input_handler(c, m):
    uid = m.from_user.id
    if uid not in user_states:
        return

    state = user_states[uid]["state"]
    user = await get_user(uid)

    if state == "url":
        user_states[uid] = {"state": "int", "url": m.text}
        await m.reply("⏱ Interval (sec)")

    elif state == "int":
        url = user_states[uid]["url"]
        interval = int(m.text)

        mon = {
            "url": url,
            "interval": interval,
            "status": "🟡",
            "uptime": 100,
            "total": 0,
            "success": 0,
            "alerts": True
        }

        user["monitors"].append(mon)
        await update_user(uid, {"monitors": user["monitors"]})

        i = len(user["monitors"]) - 1
        tasks[(uid, i)] = asyncio.create_task(ping(uid, i))

        await m.reply("✅ Added")
        user_states.pop(uid)

    elif state == "edit":
        i = user_states[uid]["i"]
        user["monitors"][i]["url"] = m.text
        await update_user(uid, {"monitors": user["monitors"]})

        tasks[(uid, i)] = asyncio.create_task(ping(uid, i))
        await m.reply("✅ Updated")
        user_states.pop(uid)

# ===== PING =====
async def ping(uid, i):
    last = None
    while True:
        user = await get_user(uid)
        if not user or i >= len(user["monitors"]):
            return

        m = user["monitors"][i]
        proxy = get_proxy()

        try:
            async with aiohttp.ClientSession() as s:
                async with s.head(m["url"], proxy=proxy, timeout=10):
                    status = "🟢"
                    m["success"] += 1
        except:
            status = "🔴"

        m["total"] += 1
        m["uptime"] = round((m["success"]/m["total"])*100,2)
        m["status"] = status

        if last and last != status and m.get("alerts"):
            await app.send_message(uid, f"{status} {m['url']}")

        last = status
        await update_user(uid, {"monitors": user["monitors"]})

        await asyncio.sleep(m["interval"])

# ===== START BOT =====
async def start_bot():
    await app.start()
    print("🤖 Bot Started")
