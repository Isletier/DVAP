import lldb
import threading
import http.server
import socketserver
import queue
import time
import os

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

state = {
    "threads": {},
    "breakpoints": {},
    "selected_thread": None  # Add this
}

def update_lldb_state(debugger):
    target = debugger.GetSelectedTarget()
    if not target or not target.IsValid(): return

    new_bps = {}
    for i in range(target.GetNumBreakpoints()):
        bp = target.GetBreakpointAtIndex(i)
        loc = bp.GetLocationAtIndex(0)
        addr = loc.GetAddress()
        le = addr.GetLineEntry()

        full_path = ""
        if le and le.GetFileSpec().IsValid():
            fs = le.GetFileSpec()
            full_path = os.path.join(fs.GetDirectory(), fs.GetFilename()) if fs.GetDirectory() else fs.GetFilename()

        new_bps[bp.GetID()] = {
            "file": full_path,
            "line": le.GetLine() if le else 0,
            "nonconditional": "0" if bp.GetCondition() is None else "1",
            "enabled": "1" if bp.IsEnabled() else "0"
        }

    state["breakpoints"] = new_bps

    process = target.GetProcess()
    new_threads = {}
    if process and process.IsValid() and process.GetState() == lldb.eStateStopped:
        sel_thread = process.GetSelectedThread()
        state["selected_thread"] = sel_thread.GetIndexID() if sel_thread.IsValid() else None

        for thread in process:
            frame = thread.GetSelectedFrame()
            le = frame.GetLineEntry()
            
            thread_full_path = ""
            if le and le.GetFileSpec().IsValid():
                fs = le.GetFileSpec()
                thread_full_path = os.path.join(fs.GetDirectory(), fs.GetFilename()) if fs.GetDirectory() else fs.GetFilename()

            new_threads[thread.GetIndexID()] = {
                "file": thread_full_path,
                "line": le.GetLine() if le else 0,
                "tid": thread.GetThreadID()
            }

    state["threads"] = new_threads

FS = ";;"   # field separator (within a record)
RS = "||"   # record separator (between records)

def state_to_string():
    result = ""
    if state["selected_thread"] is not None:
        result += f"selected{FS}{state['selected_thread']}{RS}"
    for t_num, t in state["threads"].items():
        result += f"thread{FS}{t_num}{FS}{t['file']}{FS}{t['line']}{FS}{t['tid']}{RS}"
    for b_num, b in state["breakpoints"].items():
        result += (f"bp{FS}{b_num}{FS}{b['file']}{FS}{b['line']}"
                   f"{FS}{b['nonconditional']}{FS}{b['enabled']}{RS}")
    return result

def background_loop(debugger):
    listener = lldb.SBListener("dvap.listener")

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
    print("DVAP extension loaded on port 9000")

