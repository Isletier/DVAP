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

def state_to_string():
    lines = []

    for t_num in sorted(state["threads"].keys()):
        t = state["threads"][t_num]
        line = f"thread:{t_num}:{t['file']}:{t['line']}:{t['tid']}"
        lines.append(line)


    for b_num in sorted(state["breakpoints"].keys()):
        b = state["breakpoints"][b_num]
        line = f"bp:{b_num}:{b['file']}:{b['line']}:{b['type']}:{b['location']}:{b['nonconditional']}:{b['enabled']}"
        lines.append(line)

    return "\n".join(lines)


def start_websock_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setblocking(False) # Non-blocking
    server.bind(('localhost', 9000))
    server.listen(5)

    clients = []
    while True:
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

        msg = state_to_string()
        frame = encode_frame(msg)
        for c in clients[:]:
            try:
                c.sendall(frame)
            except:
                print("Client dropped during broadcast.")
                clients.remove(c)
                c.close()

        time.sleep(0.05)


state = {
    "threads": {},      # Key: Thread Num
    "breakpoints": {}   # Key: Breakpoint Num
}

def on_stop(b):
    raw_output = gdb.execute("thread apply all where 1", to_string=True)

    current_thread = None

    for line in raw_output.splitlines():
        line = line.strip()

        if line.startswith("Thread "):
            try:
                parts = line.split()
                t_num = int(parts[1])

                lwp_idx = line.find("LWP ")
                if lwp_idx != -1:
                    tid_str = line[lwp_idx+4:].split(')')[0]
                    tid = int(tid_str)
                else:
                    tid = 0

                current_thread = t_num
                state["threads"][current_thread] = {
                    "file": "",
                    "line": None,
                    "tid": tid,
                }
            except (ValueError, IndexError):
                current_thread = None
            continue

        if current_thread is not None and line.startswith("#0"):
            at_idx = line.rfind(" at ")
            if at_idx != -1:
                location = line[at_idx + 4:].strip()
                if ":" in location:
                    file_path, line_num = location.rsplit(":", 1)
                    state["threads"][current_thread]["file"] = file_path
                    state["threads"][current_thread]["line"] = line_num

            current_thread = None

    return

def get_source_info(b):
    if b.type == gdb.BP_WATCHPOINT or b.type == gdb.BP_HARDWARE_WATCHPOINT or b.type == gdb.BP_READ_WATCHPOINT or b.type == gdb.BP_ACCESS_WATCHPOINT:
        return None, None

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

def register_gdb_events():
    gdb.events.breakpoint_created.connect(on_breakpoint_created)
    gdb.events.breakpoint_modified.connect(on_breakpoint_modified)
    gdb.events.breakpoint_deleted.connect(on_breakpoint_deleted)
    gdb.events.stop.connect(on_stop)


# --- Execution ---
register_gdb_events()
gdb.Thread(target=start_websock_server, daemon=True).start()

