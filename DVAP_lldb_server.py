import lldb
import threading
import http.server
import socketserver
import queue
import time

# --- SSE ИНФРАСТРУКТУРА ---
class SSEDispatcher:
    def __init__(self):
        self.clients = []
        self.lock = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=100)
        with self.lock:
            self.clients.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.clients: self.clients.remove(q)

    def broadcast(self, data):
        msg = f"data: {data}\n\n".encode('utf-8')
        with self.lock:
            for q in self.clients[:]:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    self.clients.remove(q)

dispatcher = SSEDispatcher()

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

class SSEHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args): return 
    def do_GET(self):
        if self.path != '/events':
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q = dispatcher.subscribe()
        try:
            while True:
                self.wfile.write(q.get())
                self.wfile.flush()
        except: pass
        finally: dispatcher.unsubscribe(q)

# --- СОСТОЯНИЕ ---
state = {"threads": {}, "breakpoints": {}}

def update_lldb_state(debugger):
    target = debugger.GetSelectedTarget()
    if not target or not target.IsValid(): return

    # Breakpoints
    new_bps = {}
    for i in range(target.GetNumBreakpoints()):
        bp = target.GetBreakpointAtIndex(i)
        loc = bp.GetLocationAtIndex(0)
        le = loc.GetAddress().GetLineEntry()
        new_bps[bp.GetID()] = {
            "file": le.GetFileSpec().GetFilename() if le else "unknown",
            "line": le.GetLine() if le else 0,
            "addr": hex(loc.GetLoadAddress()) if loc.GetLoadAddress() != 0xffffffffffffffff else "pending",
            "cond": "1" if bp.GetCondition() is None else "0",
            "enabled": "1" if bp.IsEnabled() else "0"
        }
    state["breakpoints"] = new_bps

    # Threads
    process = target.GetProcess()
    new_threads = {}
    if process and process.IsValid():
        for thread in process:
            frame = thread.GetSelectedFrame()
            le = frame.GetLineEntry()
            new_threads[thread.GetIndexID()] = {
                "file": le.GetFileSpec().GetFilename() if le else "??",
                "line": le.GetLine() if le else 0,
                "tid_raw": thread.GetThreadID()
            }
    state["threads"] = new_threads

def state_to_string():
    res = []
    for tid, t in state["threads"].items():
        res.append(f"thread:{tid}:{t['file']}:{t['line']}:{t['tid_raw']}")
    for bid, b in state["breakpoints"].items():
        res.append(f"bp:{bid}:{b['file']}:{b['line']}:sw:{b['addr']}:{b['cond']}:{b['enabled']}")
    return " ".join(res)

# --- ОСНОВНОЙ ЦИКЛ ---
def background_loop(debugger):
    listener = lldb.SBListener("minimal.dap.listener")
    
    # Запуск сервера (исправленный класс)
    try:
        server = ThreadedHTTPServer(('127.0.0.1', 9000), SSEHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
    except Exception as e:
        print(f"Server error: {e}")

    while True:
        update_lldb_state(debugger)
        dispatcher.broadcast(state_to_string())
        time.sleep(0.03)

def __lldb_init_module(debugger, internal_dict):
    t = threading.Thread(target=background_loop, args=(debugger,), daemon=True)
    t.start()
    print("Minimal DAP (LLDB) extension loaded on port 9000")


