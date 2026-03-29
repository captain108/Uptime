import os
import subprocess
import time
import threading
from flask import Flask

app = Flask(__name__)

APP_SCRIPT = "app.py"
CHECK_INTERVAL = 60  # check every 1 minute
process = None

# ================= START PROCESS ================= #
def start_app():
    global process

    if process is None or process.poll() is not None:
        print(f"🚀 Starting {APP_SCRIPT}...")
        process = subprocess.Popen(
            ["python3", APP_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

# ================= MONITOR ================= #
def monitor_app():
    global process

    while True:
        if process is None:
            print("⚠️ Process not started yet")
            start_app()

        elif process.poll() is not None:
            print(f"❌ {APP_SCRIPT} crashed. Restarting...")
            start_app()

        else:
            print(f"✅ {APP_SCRIPT} is running")

        time.sleep(CHECK_INTERVAL)

# ================= ROUTE ================= #
@app.route("/")
def status():
    if process and process.poll() is None:
        return f"{APP_SCRIPT} is running ✅"
    return f"{APP_SCRIPT} is not running ❌"

# ================= MAIN ================= #
if __name__ == "__main__":
    # start bot immediately
    start_app()

    # start monitor thread
    thread = threading.Thread(target=monitor_app)
    thread.daemon = True
    thread.start()

    # start flask
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
