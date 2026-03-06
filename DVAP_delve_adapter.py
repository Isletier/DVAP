import subprocess
import time
import sys
import os
import signal

def run_delve_wrapper():
    processes = []
    try:
        # 1. Start Headless Delve Server
        print("[*] Starting headless Delve server on :2345...")
        headless_srv = subprocess.Popen(
            ["dlv", "--headless", "--listen=:2345", "--api-version=2", "--accept-multiclient", "--check-go-version=false", "debug"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        processes.append(headless_srv)

        # 2. Start Additional Service
        print("[*] Starting additional service...")
        # Replace ['python', 'service.py'] with your actual service command
        extra_service = subprocess.Popen(["python3", "-c", "import time; [time.sleep(1) for _ in range(3600)]"])
        processes.append(extra_service)

        # Wait briefly for the server to bind to the port
        time.sleep(4)

        # 3. Start Delve REPL and attach to the headless server
        # We use .wait() here so the script stays active as long as the REPL is open
        print("[*] Launching Delve REPL...")
        repl_proc = subprocess.run(["dlv", "connect", "127.0.0.1:2345"])

    finally:
        print("[*] Cleaning up processes...")
        for p in processes:
            try:
                # Attempt graceful termination first
                p.terminate()
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't close
                p.kill()
        print("[*] All processes stopped.")

if __name__ == "__main__":
    run_delve_wrapper()
