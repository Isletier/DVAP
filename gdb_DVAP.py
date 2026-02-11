import gdb
import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# Global event buffer
event_buffer = []

# --- Event Handlers ---

def queue_event(method, params=None):
    """Formats and queues a JSON-RPC notification."""
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {}
    }
    event_buffer.append(payload)
    # Optional: Print to GDB console for local debugging
    # gdb.write(f"[DAP] Event: {method}\n")

def on_stop(event):
    reason = "breakpoint" if isinstance(event, gdb.BreakpointEvent) else "signal"
    queue_event("stopped", {
        "reason": reason,
        "threadId": gdb.selected_thread().num if gdb.selected_thread() else None
    })

def on_continue(event):
    queue_event("continued", {"threadId": gdb.selected_thread().num if gdb.selected_thread() else "all"})

def on_exit(event):
    queue_event("terminated", {"exitCode": getattr(event, 'exit_code', 0)})

def on_new_objfile(event):
    queue_event("module", {"newModule": event.new_objfile.filename})

def on_clear_objfiles(event):
    queue_event("module", {"event": "cleared"})

# --- Registry Function ---

def register_gdb_events():
    # Stop/Run events
    gdb.events.stop.connect(on_stop)
    gdb.events.cont.connect(on_continue)
    gdb.events.exited.connect(on_exit)
    
    # Symbols/Binary loading
    gdb.events.new_objfile.connect(on_new_objfile)
    gdb.events.clear_objfiles.connect(on_clear_objfiles)
    
    # Note: thread events and breakpoint changes can also be added here
    # gdb.events.new_thread.connect(lambda e: queue_event("thread", {"reason": "started"}))

# --- Server Infrastructure ---

class GDBEventHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        while True:
            if event_buffer:
                event = event_buffer.pop(0)
                try:
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode('utf-8'))
                    self.wfile.flush()
                except (ConnectionResetError, BrokenPipeError):
                    break
            time.sleep(0.05)

    def log_message(self, format, *args): return

def start_server():
    server = HTTPServer(('127.0.0.1', 8000), GDBEventHandler)
    server.serve_forever()

# --- Execution ---

register_gdb_events()
threading.Thread(target=start_server, daemon=True).start()
gdb.write("DAP Minimal Server: Monitoring all GDB events on port 8000\n")
