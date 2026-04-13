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

    def broadcast(self, data):
        msg = f"data: {data}\n\n".encode('utf-8')
        with self.lock:
            for q in self.clients[:]:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    self.clients.remove(q)


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
                self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            dispatcher.unsubscribe(client_q)

    def do_HEAD(self):
        if not self.is_valid_request():
            return
        self.send_sse_headers()

    def log_message(self, format, *args):
        pass  # suppress default request logging to gdb console


FS = ";;"   # field separator (within a record)
RS = "||"   # record separator (between records)

state = {
    "threads":         {},
    "breakpoints":     {},
    "selected_thread": None,
}
state_lock = threading.Lock()


def state_to_string():
    with state_lock:
        result = ""
        if state["selected_thread"] is not None:
            result += f"selected{FS}{state['selected_thread']}{RS}"
        for t_num, t in state["threads"].items():
            result += f"thread{FS}{t_num}{FS}{t['file']}{FS}{t['line']}{FS}{t['tid']}{RS}"
        for b_num, b in state["breakpoints"].items():
            result += f"bp{FS}{b_num}{FS}{b['file']}{FS}{b['line']}{FS}{b['type']}{FS}{b['location']}{FS}{b['nonconditional']}{FS}{b['enabled']}{RS}"
    return result


def on_stop(b):
    inf             = gdb.selected_inferior()
    selected_thread = gdb.selected_thread()

    new_threads = {}
    try:
        for thread in inf.threads():
            if not thread.is_valid():
                continue

            if thread.is_running():
                new_threads[thread.num] = {
                    "file": "",
                    "line": None,
                    "tid":  thread.ptid[1],
                }
                continue

            if thread != gdb.selected_thread():
                thread.switch()

            try:
                frame = gdb.selected_frame()
                sal   = frame.find_sal()
                if sal and sal.symtab:
                    new_threads[thread.num] = {
                        "file": sal.symtab.filename,
                        "line": sal.line,
                        "tid":  thread.ptid[1],
                    }
                else:
                    new_threads[thread.num] = {
                        "file": "",
                        "line": None,
                        "tid":  thread.ptid[1],
                    }
            except Exception as e:
                print(f"[DVAP] Error reading frame for thread {thread.num}: {e}")

    finally:
        # Always restore the originally selected thread, even after exceptions.
        if selected_thread and selected_thread != gdb.selected_thread():
            selected_thread.switch()

    with state_lock:
        state["selected_thread"] = selected_thread.num if selected_thread else None
        state["threads"]         = new_threads


def get_source_info(b):
    if b.type in (gdb.BP_WATCHPOINT, gdb.BP_HARDWARE_WATCHPOINT,
                  gdb.BP_READ_WATCHPOINT, gdb.BP_ACCESS_WATCHPOINT):
        return "", ""

    if hasattr(b, 'locations') and b.locations:
        source = b.locations[0].source
        if source:
            return source[0], source[1]  # (fullname, line)

    if b.location:
        try:
            sals = gdb.decode_line(b.location)[1]
            if sals:
                return sals[0].symtab.fullname(), sals[0].line
        except Exception:
            pass

    return "", ""


def on_breakpoint_created(b):
    file_path, line_num = get_source_info(b)

    is_nonconditional = (b.condition is None and
                         b.thread is None and
                         getattr(b, 'task', None) is None)

    with state_lock:
        state["breakpoints"][b.number] = {
            "file":           file_path,
            "line":           line_num,
            "type":           b.type,
            "location":       b.location if b.location else "",
            "nonconditional": is_nonconditional,
            "enabled":        b.enabled,
        }


def on_breakpoint_modified(b):
    on_breakpoint_created(b)


def on_breakpoint_deleted(b):
    with state_lock:
        state["breakpoints"].pop(b.number, None)


def on_inferior_exited(event):
    with state_lock:
        state["threads"]         = {}
        state["selected_thread"] = None


def loop_wrapper():
    while not stop_token.is_set():
        dispatcher.broadcast(state_to_string())
        stop_token.wait(0.030)


stop_token = threading.Event()
server     = GDBThreadedHTTPServer(('127.0.0.1', 9000), SSEHandler)

gdb.Thread(target=loop_wrapper,        daemon=True).start()
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
