import http.server
import socketserver
import threading
import queue
import gdb

# Created once on the gdb module so the value survives re-sourcing.
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

_SHUTDOWN = object()  # sentinel pushed to queues on shutdown

class SSEDispatcher:
    """Thread-safe fan-out broadcaster to all connected SSE clients."""
    _SHUTDOWN = object()  # sentinel pushed to queues on shutdown

    def __init__(self):
        self._clients = []
        self._lock    = threading.Lock()
        self.stopped  = threading.Event()

    def subscribe(self):
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._clients.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def broadcast(self, data):
        msg = f"data: {data}\n\n".encode('utf-8')
        with self._lock:
            for q in self._clients[:]:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    self._clients.remove(q)

    def shutdown(self):
        """Signal all do_GET threads to exit and close their connections."""
        self.stopped.set()
        with self._lock:
            for q in self._clients:
                try:
                    q.put_nowait(_SHUTDOWN)
                except queue.Full:
                    pass
            self._clients.clear()


class _HTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads      = True

    def __init__(self, addr, handler, dispatcher):
        super().__init__(addr, handler)
        self.dispatcher = dispatcher

    def process_request(self, request, client_address):
        t = gdb.Thread(target=self.process_request_thread,
                       args=(request, client_address))
        t.daemon = self.daemon_threads
        t.start()


class _SSEHandler(http.server.BaseHTTPRequestHandler):
    def _check_request(self):
        host = self.headers.get('Host', '')
        if not (host.startswith('127.0.0.1') or host.startswith('localhost')):
            self.send_error(403, "Access Denied: Invalid Host header")
            return False
        if self.path != '/events':
            self.send_error(404, "Not Found")
            return False
        return True

    def _send_sse_headers(self):
        self.send_response(200)
        self.send_header("Content-Type",               "text/event-stream")
        self.send_header("Cache-Control",              "no-cache, no-transform")
        self.send_header("Connection",                 "keep-alive")
        self.send_header("X-Accel-Buffering",          "no")
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()

    def do_GET(self):
        if not self._check_request():
            return
        self._send_sse_headers()
        self.wfile.flush()
        disp = self.server.dispatcher
        q    = disp.subscribe()
        try:
            while not disp.stopped.is_set():
                try:
                    msg = q.get(timeout=0.05)
                except queue.Empty:
                    continue
                if msg is _SHUTDOWN:
                    break
                self.wfile.write(msg)
                self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            disp.unsubscribe(q)
            # Prevent BaseHTTPRequestHandler.handle() from looping back into
            # handle_one_request() → rfile.readline(), which blocks forever
            # waiting for a second HTTP request that never arrives.
            # Causes handle() to return → shutdown_request() → socket close → EOF.
            self.close_connection = True

    def do_HEAD(self):
        if not self._check_request():
            return
        self._send_sse_headers()

    def log_message(self, format, *args):
        pass  # suppress HTTP request logs in the gdb console


class DVAPServer:
    """All state for one DVAP server instance. Stored on gdb._dvap_instance."""
    FS = ";;"   # field separator (within a record)
    RS = "||"   # record separator (between records)

    def __init__(self, port):
        self._state = {"threads": {}, "breakpoints": {}, "selected_thread": None}
        self._lock  = threading.Lock()
        self._disp  = SSEDispatcher()
        self._http  = None
        self._evts  = {}

        try:
            self._http = _HTTPServer(('127.0.0.1', port), _SSEHandler, self._disp)
        except OSError as e:
            print(f"[DVAP] Failed to start server on port {port}: {e}")
            return

        self._sync_gdb_state()
        gdb.Thread(target=self._broadcast_loop, daemon=True).start()
        gdb.Thread(target=self._http.serve_forever, daemon=True).start()
        print(f"[DVAP] Listening on 127.0.0.1:{port}")
        self._connect_events()

    def shutdown(self):
        # Dispatcher first: unblocks do_GET threads before server.shutdown()
        # waits on them.
        self._disp.shutdown()
        if self._http:
            self._http.shutdown()
            self._http.server_close()
        for event, fn in self._evts.items():
            try:
                event.disconnect(fn)
            except Exception:
                pass

    def _connect_events(self):
        self._evts = {
            gdb.events.stop:                self._on_stop,
            gdb.events.breakpoint_created:  self._on_bp_created,
            gdb.events.breakpoint_modified: self._on_bp_modified,
            gdb.events.breakpoint_deleted:  self._on_bp_deleted,
            gdb.events.exited:              self._on_inferior_exited,
            gdb.events.gdb_exiting:         self._on_gdb_exiting,
        }
        for event, fn in self._evts.items():
            event.connect(fn)

    def _on_gdb_exiting(self, event):
        self.shutdown()

    def _broadcast_loop(self):
        while not self._disp.stopped.is_set():
            self._disp.broadcast(self._state_str())
            self._disp.stopped.wait(0.030)

    def _state_str(self):
        FS, RS = self.FS, self.RS
        with self._lock:
            result = ""
            if self._state["selected_thread"] is not None:
                result += f"selected{FS}{self._state['selected_thread']}{RS}"
            for t_num, t in self._state["threads"].items():
                result += f"thread{FS}{t_num}{FS}{t['file']}{FS}{t['line']}{FS}{t['tid']}{RS}"
            for b_num, b in self._state["breakpoints"].items():
                result += (f"bp{FS}{b_num}{FS}{b['file']}{FS}{b['line']}"
                           f"{FS}{b['nonconditional']}{FS}{b['enabled']}{RS}")
        return result

    def _sync_gdb_state(self):
        """Populate state from the current GDB session on (re-)source."""
        self._on_stop(None)
        for bp in gdb.breakpoints() or []:
            self._on_bp_created(bp)

    def _on_stop(self, event):
        inf = gdb.selected_inferior()
        if inf is None:
            return
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

        with self._lock:
            self._state["selected_thread"] = selected_thread.num if selected_thread else None
            self._state["threads"]         = new_threads

    def _get_bp_source(self, b):
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

    def _on_bp_created(self, b):
        file_path, line_num = self._get_bp_source(b)
        is_nonconditional   = (b.condition is None and
                               b.thread   is None and
                               getattr(b, 'task', None) is None)
        with self._lock:
            self._state["breakpoints"][b.number] = {
                "file":           file_path,
                "line":           line_num,
                "nonconditional": is_nonconditional,
                "enabled":        b.enabled,
            }

    def _on_bp_modified(self, b):
        self._on_bp_created(b)

    def _on_bp_deleted(self, b):
        with self._lock:
            self._state["breakpoints"].pop(b.number, None)

    def _on_inferior_exited(self, event):
        with self._lock:
            self._state["threads"]         = {}
            self._state["selected_thread"] = None


if getattr(gdb, '_dvap_instance', None) is not None:
    print("[DVAP] Re-sourcing: shutting down previous instance...")
    gdb._dvap_instance.shutdown()

gdb._dvap_instance = DVAPServer(gdb._dvap_port_param.value)

