import http.server
import socketserver
import threading
import queue
import gdb

# ─── Port parameter ───────────────────────────────────────────────────────────
# Created once and stored on the gdb module so it survives re-sourcing.
# Usage: (gdb) set dvap-port 12345   then re-source this script.

if not hasattr(gdb, '_dvap_port_param'):
    class _DVAPPortParam(gdb.Parameter):
        """DVAP SSE server port (default 56789). Re-source the script to apply changes."""
        def __init__(self):
            super().__init__('dvap-port', gdb.COMMAND_NONE, gdb.PARAM_INTEGER)
            self.value = 56789
        def get_set_string(self):
            return f"DVAP port set to {self.value} (re-source script to apply)"
        def get_show_string(self, sval):
            return f"DVAP port is {self.value}"
    gdb._dvap_port_param = _DVAPPortParam()


# ─── Re-source cleanup ────────────────────────────────────────────────────────
# Stop the previous broadcast loop, shut down the HTTP server, and disconnect
# all event handlers before re-registering everything.

def _cleanup_previous():
    prev = getattr(gdb, '_dvap_instance', None)
    if prev is None:
        return
    print("[DVAP] Re-sourcing: shutting down previous instance...")
    prev['stop_token'].set()
    if prev['server']:
        try:
            prev['server'].shutdown()
            prev['server'].server_close()
        except Exception as e:
            print(f"[DVAP] Warning during server shutdown: {e}")
    for event, fn in prev.get('handlers', {}).items():
        try:
            event.disconnect(fn)
        except Exception:
            pass

_cleanup_previous()


# ─── SSE infrastructure ───────────────────────────────────────────────────────

class SSEDispatcher:
    """Thread-safe fan-out broadcaster to all connected SSE clients."""
    def __init__(self):
        self.clients = []
        self.lock    = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=100)
        with self.lock:
            self.clients.append(q)
        return q

    def unsubscribe(self, q):
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
    allow_reuse_address = True   # avoids "address already in use" on quick restart
    daemon_threads      = True

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
        self.send_header("Content-Type",               "text/event-stream")
        self.send_header("Cache-Control",              "no-cache, no-transform")
        self.send_header("Connection",                 "keep-alive")
        self.send_header("X-Accel-Buffering",          "no")
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()

    def do_GET(self):
        if not self.is_valid_request():
            return
        self.send_sse_headers()
        self.wfile.flush()
        client_q = dispatcher.subscribe()
        try:
            while True:
                self.wfile.write(client_q.get())
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
        pass  # suppress HTTP request logs in the gdb console


# ─── Debug state ──────────────────────────────────────────────────────────────

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
            result += (f"bp{FS}{b_num}{FS}{b['file']}{FS}{b['line']}"
                       f"{FS}{b['nonconditional']}{FS}{b['enabled']}{RS}")
    return result


# ─── GDB event handlers ───────────────────────────────────────────────────────

def on_stop(b):
    inf             = gdb.selected_inferior()
    selected_thread = gdb.selected_thread()

    new_threads = {}
    try:
        for thread in inf.threads():
            if not thread.is_valid() or thread.is_running():
                continue  # running threads have no meaningful source position

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
                    # Stopped but no source (e.g. inside a library without debug symbols).
                    # Send with empty location so the client can fall back to the last
                    # known position for this thread.
                    new_threads[thread.num] = {
                        "file": "",
                        "line": 0,
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
    is_nonconditional   = (b.condition is None and
                           b.thread   is None and
                           getattr(b, 'task', None) is None)
    with state_lock:
        state["breakpoints"][b.number] = {
            "file":           file_path,
            "line":           line_num,
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


# ─── Broadcast loop ───────────────────────────────────────────────────────────

def _make_loop(token):
    """Returns a loop function bound to a specific stop token.
    This prevents a stale thread from picking up a replacement token after re-source."""
    def _loop():
        while not token.is_set():
            dispatcher.broadcast(state_to_string())
            token.wait(0.030)
    return _loop


# ─── Startup ──────────────────────────────────────────────────────────────────

port       = gdb._dvap_port_param.value
stop_token = threading.Event()
server     = None

try:
    server = GDBThreadedHTTPServer(('127.0.0.1', port), SSEHandler)
except OSError as e:
    print(f"[DVAP] Failed to start server on port {port}: {e}")

if server:
    gdb.Thread(target=_make_loop(stop_token), daemon=True).start()
    gdb.Thread(target=server.serve_forever,   daemon=True).start()
    print(f"[DVAP] Listening on 127.0.0.1:{port}")


def _on_gdb_exit(code, _token=stop_token, _server=server):
    """Captures this instance's token and server via default args to avoid
    picking up replacements after re-source."""
    _token.set()
    if _server:
        try:
            _server.shutdown()
            _server.server_close()
        except Exception:
            pass


handlers = {
    gdb.events.breakpoint_created:  on_breakpoint_created,
    gdb.events.breakpoint_modified: on_breakpoint_modified,
    gdb.events.breakpoint_deleted:  on_breakpoint_deleted,
    gdb.events.exited:              on_inferior_exited,
    gdb.events.gdb_exiting:        _on_gdb_exit,
    gdb.events.stop:               on_stop,
}
for event, fn in handlers.items():
    event.connect(fn)

# Store instance state for cleanup on next re-source.
gdb._dvap_instance = {
    'stop_token': stop_token,
    'server':     server,
    'handlers':   handlers,
}
