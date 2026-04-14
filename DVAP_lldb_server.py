import lldb
import os
import threading
import http.server
import socketserver
import queue

# Stored on the lldb module so the value survives re-source.
# To change: (lldb) script lldb._dvap_port = 12345   then re-source this script.

if not hasattr(lldb, '_dvap_port'):
    lldb._dvap_port = 56789


_SHUTDOWN = object()  # sentinel pushed to queues on shutdown

class SSEDispatcher:
    """Thread-safe fan-out broadcaster to all connected SSE clients."""
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
        pass  # suppress HTTP request logs in the lldb console


class DVAPServer:
    """All state for one DVAP server instance. Stored on lldb._dvap_instance."""
    FS = ";;"   # field separator (within a record)
    RS = "||"   # record separator (between records)

    def __init__(self, port, debugger):
        self._debugger = debugger
        self._disp     = SSEDispatcher()
        self._http     = None

        try:
            self._http = _HTTPServer(('127.0.0.1', port), _SSEHandler, self._disp)
        except OSError as e:
            print(f"[DVAP] Failed to start server on port {port}: {e}")
            return

        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        threading.Thread(target=self._http.serve_forever, daemon=True).start()
        print(f"[DVAP] Listening on 127.0.0.1:{port}")

    def shutdown(self):
        # Dispatcher first: unblocks do_GET threads before server.shutdown()
        # waits on them.
        self._disp.shutdown()
        if self._http:
            self._http.shutdown()
            self._http.server_close()

    def _broadcast_loop(self):
        while not self._disp.stopped.is_set():
            self._disp.broadcast(self._state_str())
            self._disp.stopped.wait(0.030)

    def _state_str(self):
        """Read current debugger state and format it as a protocol string."""
        FS, RS = self.FS, self.RS
        result = ""

        target = self._debugger.GetSelectedTarget()
        if not target or not target.IsValid():
            return result

        # Breakpoints
        for i in range(target.GetNumBreakpoints()):
            bp  = target.GetBreakpointAtIndex(i)
            loc = bp.GetLocationAtIndex(0)
            if not loc.IsValid():  # pending/unresolved
                continue
            le        = loc.GetAddress().GetLineEntry()
            file_path = self._file_path(le.GetFileSpec()) if le.IsValid() else ""
            line      = le.GetLine() if le.IsValid() else 0
            result += (f"bp{FS}{bp.GetID()}{FS}{file_path}{FS}{line}"
                       f"{FS}{'True' if bp.GetCondition() is None else 'False'}"
                       f"{FS}{'True' if bp.IsEnabled() else 'False'}{RS}")

        # Threads — only meaningful when the process is stopped
        process = target.GetProcess()
        if process and process.IsValid() and process.GetState() == lldb.eStateStopped:
            sel = process.GetSelectedThread()
            if sel.IsValid():
                result += f"selected{FS}{sel.GetIndexID()}{RS}"
            for thread in process:
                frame     = thread.GetSelectedFrame()
                le        = frame.GetLineEntry() if frame.IsValid() else None
                file_path = self._file_path(le.GetFileSpec()) if le and le.IsValid() else ""
                line      = le.GetLine() if le and le.IsValid() else 0
                result += (f"thread{FS}{thread.GetIndexID()}{FS}{file_path}"
                           f"{FS}{line}{FS}{thread.GetThreadID()}{RS}")

        return result

    @staticmethod
    def _file_path(file_spec):
        """Construct an absolute path from an SBFileSpec. Returns '' if invalid."""
        if not file_spec or not file_spec.IsValid():
            return ""
        filename = file_spec.GetFilename()
        if not filename:
            return ""
        directory = file_spec.GetDirectory()
        return os.path.join(directory, filename) if directory else filename


def __lldb_init_module(debugger, internal_dict):
    if getattr(lldb, '_dvap_instance', None) is not None:
        print("[DVAP] Re-sourcing: shutting down previous instance...")
        lldb._dvap_instance.shutdown()
    lldb._dvap_instance = DVAPServer(lldb._dvap_port, debugger)
