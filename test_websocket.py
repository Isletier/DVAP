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
    
    # Byte 1: Fin=1 (0x80), Opcode=1 (Text) -> 0x81
    header = bytearray([0x81])
    
    if length <= 125:
        header.append(length)
    elif length <= 65535:
        # 126 is the signal for a 2-byte extended length
        header.append(126)
        # Add the length as a 16-bit unsigned integer (big-endian)
        header.extend(length.to_bytes(2, byteorder='big'))
    else:
        # 127 is the signal for an 8-byte extended length
        header.append(127)
        header.extend(length.to_bytes(8, byteorder='big'))
        
    return bytes(header + data)

def start_websock_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('localhost', 9000))
    server.listen(5)
    server.setblocking(False)

    inputs = [server] # Sockets we want to read from
    clients = []      # Sockets that have finished handshake

    print("Server running on ws://localhost:9000 using select()")

    while True:
        # select(read_list, write_list, x_list, timeout)
        # It blocks for 0.1s or until a socket is ready
        readable, _, exceptional = select.select(inputs, [], inputs, 0.01)

        for s in readable:
            if s is server:
                # A new connection is waiting on the main server socket
                conn, addr = s.accept()
                conn.setblocking(False)
                inputs.append(conn)
                print(f"Accepted potential client from {addr}")
            else:
                # An existing client has sent data (likely the handshake)
                try:
                    data = s.recv(1024)
                    if data:
                        # Perform handshake only once
                        s.sendall(get_handshake_response(data))
                        clients.append(s)
                        inputs.remove(s) # Stop monitoring for reads, we only want to write now
                        print("Handshake successful. Client moved to broadcast list.")
                    else:
                        # Empty data means they closed the connection
                        inputs.remove(s)
                        s.close()
                except:
                    inputs.remove(s)
                    s.close()

        # BROADCAST: Send to everyone who has finished the handshake
        if clients:
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


# --- Execution ---
register_gdb_events()
gdb.Thread(target=start_websock_server, daemon=True).start()

