import os
import sys
import signal
import time
import subprocess
import threading

# чтобы Flask слушал нужный порт на Railway (если не задан)
os.environ.setdefault("PORT", "5000")

procs = []

def stream_output(proc: subprocess.Popen, name: str):
    """Читает stdout процесса и печатает в логи с префиксом."""
    for line in iter(proc.stdout.readline, ''):
        if not line:
            break
        print(f"[{name}] {line.rstrip()}", flush=True)

def spawn(name: str, args: list[str]) -> subprocess.Popen:
    """Стартует подпроцесс с неблокирующим stdout."""
    cmd = [sys.executable, "-u", *args]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=os.environ.copy()
    )
    procs.append((name, proc))
    t = threading.Thread(target=stream_output, args=(proc, name), daemon=True)
    t.start()
    print(f"[RUN] Started {name}: PID={proc.pid}", flush=True)
    return proc

def terminate_all():
    """Аккуратно гасим все подпроцессы."""
    for name, p in procs:
        if p.poll() is None:
            try:
                print(f"[RUN] Terminate {name} (PID={p.pid})", flush=True)
                p.terminate()
            except Exception:
                pass
    time.sleep(2)
    for name, p in procs:
        if p.poll() is None:
            try:
                print(f"[RUN] Kill {name} (PID={p.pid})", flush=True)
                p.kill()
            except Exception:
                pass

def handle_signal(signum, frame):
    print(f"[RUN] Caught signal {signum}, shutting down…", flush=True)
    terminate_all()
    sys.exit(0)

def main():
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print("[RUN] Starting Flask API…", flush=True)
    api = spawn("API", ["app.py"])

    print("[RUN] Starting Telegram BOT…", flush=True)
    bot = spawn("BOT", ["main.py"])

    while True:
        api_ret = api.poll()
        bot_ret = bot.poll()
        if api_ret is not None or bot_ret is not None:
            print(f"[RUN] A process exited (API={api_ret}, BOT={bot_ret}), stopping the other…", flush=True)
            break
        time.sleep(0.3)

    terminate_all()

if __name__ == "__main__":
    main()

