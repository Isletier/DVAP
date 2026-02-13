import socket
import hashlib
import base64
import time
import select

def get_handshake_response(raw_request):
    try:
        # Decode and split by lines
        lines = raw_request.decode('utf-8').split('\r\n')
        key = None

        for line in lines:
            if line.lower().startswith('sec-websocket-key:'):
                # Split at colon and strip whitespace/extra chars
                key = line.split(':', 1)[1].strip()
                break

        if not key:
            return b"HTTP/1.1 400 Bad Request\r\n\r\n"

        # The logic MUST be: Base64(SHA1(Key + MagicString))
        MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        accept_val = base64.b64encode(hashlib.sha1((key + MAGIC).encode('utf-8')).digest()).decode('utf-8')
        
        # Build the response string manually
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: " + accept_val + "\r\n\r\n"
        )
        return response.encode('utf-8')
    except Exception as e:
        return b"HTTP/1.1 500 Internal Server Error\r\n\r\n"

def encode_frame(message):
    data = message.encode('utf-8')
    length = len(data)

    header = bytearray([0x81])

    if length <= 125:
        header.append(length)
    elif length <= 65535:
        header.append(126)
        header.extend(length.to_bytes(2, byteorder='big'))
    else:
        header.append(127)
        header.extend(length.to_bytes(8, byteorder='big'))

    return bytes(header + data)

state = {
    "threads": {},      # Key: Thread Num
    "breakpoints": {}   # Key: Breakpoint Num
}

def scrape_all_threads():
    # Get the current inferior (the process)
    inf = gdb.selected_inferior()

    state["threads"] = {}

    # Iterate through all threads in this process
    for thread in inf.threads():
        # Ensure the thread is valid and stopped so we can inspect it
        if not thread.is_valid():
            continue
        try:
            thread.switch()
            frame = gdb.newest_frame()
            sal = frame.find_sal() # Symbol-and-Line

            filename = sal.symtab.fullname() if (sal.symtab and sal.symtab.is_valid()) else "Unknown"
            line = sal.line

            state["threads"][thread.num] = {
                "tid": thread.ptid[1], # LWP ID
                "file": filename,
                "line": line,
                "name": thread.name or "Unnamed"
            }
        except gdb.error as e:
            state["threads"][thread.num] = {"error": str(e)}

    return

# Example of how to trigger this safely from a background context
def safe_scrape():
    original_thread = gdb.selected_thread()

    try:
        scrape_all_threads()
    finally:
        if original_thread and original_thread.is_valid():
            original_thread.switch()


def start_websock_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setblocking(False) # Non-blocking
    server.bind(('localhost', 9000))
    server.listen(5)

    clients = []
    while True:
        gdb.post_event(safe_scrape)

        try:
            conn, addr = server.accept()
            conn.setblocking(False)
            clients.append(conn)
        except BlockingIOError:
            pass

        # Handle existing clients
        for c in clients[:]:
            try:
                data = c.recv(1024)
                if data:
                    c.sendall(get_handshake_response(data))
                else:
                    clients.remove(c)
                    c.close()
            except BlockingIOError:
                pass
            except Exception:
                clients.remove(c)
                c.close()

        msg = f"GDB Event: {time.time()}"
        frame = encode_frame(msg)
        for c in clients[:]:
            try:
                c.sendall(frame)
            except:
                print("Client dropped during broadcast.")
                if c in inputs: inputs.remove(c)
                clients.remove(c)
                c.close()

        time.sleep(0.05)


# Global event buffer

#state = {
#    "threads": {},      # Key: Thread Num
#    "breakpoints": {}   # Key: Breakpoint Num
#}

# --- Event Handlers ---

#def queue_event(method, params=None):
#    """Formats and queues a JSON-RPC notification."""
#    payload = {
#        "jsonrpc": "2.0",
#        "method": method,
#        "params": params or {}
#    }
#    event_buffer.append(payload)
#
#def on_stop(event):
#    reason = "breakpoint" if isinstance(event, gdb.BreakpointEvent) else "signal"
#    queue_event("stopped", {
#        "reason": reason,
#        "threadId": gdb.selected_thread().num if gdb.selected_thread() else None
#    })
#
#def on_continue(event):
#    queue_event("continued", {"threadId": gdb.selected_thread().num if gdb.selected_thread() else "all"})
#
#def on_exit(event):
#    queue_event("terminated", {"exitCode": getattr(event, 'exit_code', 0)})

#def get_location(frame):
#    try:
#        sal = frame.find_sal()
#        if not sal.symtab:
#            return None
#        return sal.symtab.fullname() + ':' + sal.line + ':0'
#    except:
#        return None
#
#def on_new_thread(event):
#    return 

def on_breakpoint_created():
    

def register_gdb_events():
    gdb.events.breakpoint_created(on_breakpoint_created)


# --- Execution ---
register_gdb_events()
gdb.Thread(target=start_websock_server, daemon=True).start()

