import threading
import asyncio
import os
from flask import Flask, render_template
from motor.motor_asyncio import AsyncIOMotorClient

from app import start_bot  # import bot

app = Flask(__name__)

# ===== Mongo =====
mongo = AsyncIOMotorClient(os.getenv("MONGO_URI"))
db = mongo["uptime_bot"]

# ===== Dashboard =====
@app.route("/")
async def index():
    monitors = []
    async for u in db["users"].find():
        monitors += u.get("monitors", [])
    return render_template("index.html", monitors=monitors)

# ===== Bot Thread =====
def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_bot())
    loop.run_forever()

# ===== Start =====
if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()

    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
