import socket
import hashlib
import base64
import time
import select
import lldb
import threading

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
                if c in inputs: inputs.remove(c)
                clients.remove(c)
                c.close()

        time.sleep(0.05)


state = {
    "threads": {},      # Key: Thread Num
    "breakpoints": {}   # Key: Breakpoint Num
}
def update_threads(process):
    state["threads"].clear()
    for i in range(process.GetNumThreads()):
        thread = process.GetThreadAtIndex(i)
        frame = thread.GetFrameAtIndex(0)
        line_entry = frame.GetLineEntry()
        
        state["threads"][thread.GetIndexID()] = {
            "file": line_entry.GetFileSpec().GetFilename() if line_entry.IsValid() else "",
            "line": line_entry.GetLine() if line_entry.IsValid() else None,
            "tid": thread.GetThreadID()
        }

def update_breakpoints(target):
    state["breakpoints"].clear()
    for i in range(target.GetNumBreakpoints()):
        bp = target.GetBreakpointAtIndex(i)
        # Use first location to determine file/line info
        loc = bp.GetLocationAtIndex(0)
        address = loc.GetAddress()
        line_entry = address.GetLineEntry()
        
        state["breakpoints"][bp.GetID()] = {
            "file": line_entry.GetFileSpec().GetFilename() if line_entry.IsValid() else "",
            "line": line_entry.GetLine() if line_entry.IsValid() else 0,
            "type": "software", # LLDB doesn't use GDB's integer type constants
            "location": str(address),
            "nonconditional": bp.GetCondition() is None,
            "enabled": bp.IsEnabled()
        }

def lldb_event_loop(debugger):
    # Use the debugger's listener - this allows us to "peek" at events
    # without breaking the main REPL's ability to see them.
    listener = debugger.GetListener()
    
    while True:
        event = lldb.SBEvent()
        # Non-blocking wait (0 seconds) or very short timeout
        if listener.WaitForEvent(1, event):
            if lldb.SBProcess.EventIsProcessEvent(event):
                state_type = lldb.SBProcess.GetStateFromEvent(event)
                
                # Update on stop, but also clear on exit/crash
                if state_type == lldb.eStateStopped:
                    process = lldb.SBProcess.GetProcessFromEvent(event)
                    update_threads(process)
                elif state_type in [lldb.eStateExited, lldb.eStateCrashed, lldb.eStateDetached]:
                    state["threads"].clear()
            
            elif lldb.SBTarget.EventIsTargetEvent(event):
                # Breakpoint events usually don't block the REPL, 
                # but we handle them here for consistency.
                target = lldb.SBTarget.GetTargetFromEvent(event)
                update_breakpoints(target)

        # Crucial: yield control so the debugger can process commands
        time.sleep(0.1)

def __lldb_init_module(debugger, internal_dict):
    debugger.SetAsync(True) 
    # 1. Start the WebSocket server
    t1 = threading.Thread(target=start_websock_server, daemon=True)
    t1.start()

    # 2. Start the Scraper
    # We pass the debugger instance to ensure we are on the right listener
    t2 = threading.Thread(target=lldb_event_loop, args=(debugger,), daemon=True)
    t2.start()
    
    print("DAP Scraper loaded. WebSocket on 9000. REPL active.")

