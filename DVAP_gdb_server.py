import errno
import http.server
import socketserver
import threading
import queue
import time
import gdb

class SSEDispatcher:
    """Thread-safe manager for all connected clients."""
    def __init__(self):
        self.clients = []
        self.lock = threading.Lock()

    def subscribe(self):
        """Register a new client queue."""
        q = queue.Queue(maxsize=100)
        with self.lock:
            self.clients.append(q)
        return q

    def unsubscribe(self, q):
        """Remove a client queue on disconnect."""
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)

    def broadcast(self, data, event=None, id=None):
        msg = f"data: {data}\n\n"
        
        encoded_msg = msg.encode('utf-8')
        with self.lock:
            for q in self.clients[:]:
                try:
                    q.put_nowait(encoded_msg)
                except queue.Full:
                    self.clients.remove(q)

# Global dispatcher instance
dispatcher = SSEDispatcher()

class GDBThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

    def process_request(self, request, client_address):
        t = gdb.Thread(target=self.process_request_thread, 
                       args=(request, client_address))
        t.daemon = self.daemon_threads
        t.start()

class SSEHandler(http.server.BaseHTTPRequestHandler):
    def is_valid_request(self):
        host = self.headers.get('Host', '')
        if not (host.startswith('127.0.0.1') or host.startswith('localhost')):
            self.send_error(403, "Access Denied: Invalid Host header")
            return False

        if self.path != '/events':
            self.send_error(404, "Not Found")
            return False

        return True

    def send_sse_headers(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_GET(self):
        if not self.is_valid_request():
            return

        self.send_sse_headers()
        self.wfile.flush()

        client_q = dispatcher.subscribe()
        try:
            while True:
                message = client_q.get()
                self.wfile.write(message)
                self.wfile.flush() # Push data immediately
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            dispatcher.unsubscribe(client_q)

    def do_HEAD(self):
        if not self.is_valid_request():
            return

        self.send_sse_headers()

state = {
    "threads": {},      # Key: Thread Num
    "breakpoints": {}   # Key: Breakpoint Num
}

def state_to_string():
    result = ""

    for t_num in state["threads"].keys():
        t = state["threads"][t_num]
        result += f"thread:{t_num}:{t['file']}:{t['line']}:{t['tid']} "

    for b_num in state["breakpoints"].keys():
        b = state["breakpoints"][b_num]
        result += f"bp:{b_num}:{b['file']}:{b['line']}:{b['type']}:{b['location']}:{b['nonconditional']}:{b['enabled']} "

    return result

def on_stop(b):
    inf = gdb.selected_inferior()
    selected_thread = gdb.selected_thread()
    state["threads"] = {}
    for thread in inf.threads():
        if not thread.is_valid():
            continue

        if thread.is_running():
            state["threads"][thread.num] = {
                "file": "",
                "line": None,
                "tid":  thread.ptid[1]
            }

            continue

        if thread != gdb.selected_thread():
            thread.switch()

        try:
            frame = gdb.selected_frame()
            sal = frame.find_sal()
            
            if sal and sal.symtab:
                filename = sal.symtab.filename
                line = sal.line
                state["threads"][thread.num] = {
                    "file": filename,
                    "line": line,
                    "tid":  thread.ptid[1]
                }
            else:
                state["threads"][thread.num] = {
                    "file": "",
                    "line": None,
                    "tid":  thread.ptid[1]
                }
        except gdb.error as e:
            print(e)

    if selected_thread != gdb.selected_thread():
        selected_thread.switch()

    return

def get_source_info(b):
    if b.type == gdb.BP_WATCHPOINT or b.type == gdb.BP_HARDWARE_WATCHPOINT or b.type == gdb.BP_READ_WATCHPOINT or b.type == gdb.BP_ACCESS_WATCHPOINT:
        return "", ""

    if hasattr(b, 'locations') and b.locations:
        source = b.locations[0].source
        if source:
            return source[0], source[1] # (fullname, line)

    if b.location:
        try:
            sals = gdb.decode_line(b.location)[1]
            if sals and len(sals) > 0:
                return sals[0].symtab.fullname(), sals[0].line
        except:
            pass
            
    return "", ""

def on_breakpoint_created(b):
    file_path, line_num = get_source_info(b)

    is_nonconditional = (b.condition is None and 
                         b.thread is None and 
                         getattr(b, 'task', None) is None)

    state["breakpoints"][b.number] = {
        "file":           file_path,
        "line":           line_num,
        "type":           b.type,
        "location":       b.location if b.location else "",
        "nonconditional": is_nonconditional,
        "enabled":        b.enabled
    }


def on_breakpoint_modified(b):
    on_breakpoint_created(b)

def on_breakpoint_deleted(b):
    if b.number in state["breakpoints"]:
        del state["breakpoints"][b.number]


def loop_wrapper():
    while not stop_token.is_set():
        start_time = time.perf_counter()

        elapsed = time.perf_counter() - start_time
        sleep_time = max(0, 0.030 - elapsed)

        dispatcher.broadcast(state_to_string())
        if stop_token.wait(sleep_time):
            break

def on_inferior_exited(inferior):
    state["threads"] = {}


stop_token = threading.Event()
server = GDBThreadedHTTPServer(('127.0.0.1', 9000), SSEHandler)
gdb.Thread(target=loop_wrapper, daemon=True).start()
gdb.Thread(target=server.serve_forever, daemon=True).start()

def on_gdb_exit(code):
    stop_token.set()
    server.shutdown() 
    server.server_close()

def register_gdb_events():
    gdb.events.breakpoint_created.connect(on_breakpoint_created)
    gdb.events.breakpoint_modified.connect(on_breakpoint_modified)
    gdb.events.breakpoint_deleted.connect(on_breakpoint_deleted)
    gdb.events.exited.connect(on_inferior_exited)
    gdb.events.gdb_exiting.connect(on_gdb_exit)
    gdb.events.stop.connect(on_stop)

register_gdb_events()

