## GDB

## Loading the server

```
gdb$ source /path/to/DVAP_gdb_server.py
```

To load it automatically on every gdb start, add the same line to `~/.gdbinit`:

```
source /path/to/DVAP_gdb_server.py
```

The server prints `[DVAP] Listening on 127.0.0.1:56789` on success. If the port is already in use, it will say so and skip starting.

## DVAP commands

Once the script is loaded, the following commands are available inside gdb:

```
dvap-help            Show usage information
dvap-show            Show server status and current port
dvap-start           Start or restart the server
dvap-stop            Stop the server
dvap-set port <N>    Change the port (then dvap-start to apply)
```

## Changing the port

The default port is 56789. To use a different one, set it before sourcing the script:

```
gdb$ set dvap-port 12345
gdb$ source /path/to/DVAP_gdb_server.py
```

Or if the server is already running:

```
gdb$ dvap-set port 12345
gdb$ dvap-start
```

## If you're coming from an IDE

Compile with debug symbols — the `-g` flag on most compilers:

```
cc -g -o myprogram myprogram.c
```

For build systems, set the debug configuration (CMake: `-DCMAKE_BUILD_TYPE=Debug`, etc.).

Start a session:

```
shell$ gdb ./myprogram
gdb$   run arg1 arg2
```

Set a breakpoint:

```
gdb$ b main.c:20
gdb$ b my_function
```

Navigate execution:

```
gdb$ continue   (or: c)     — resume
gdb$ step       (or: s)     — step into
gdb$ next       (or: n)     — step over
gdb$ finish     (or: fin)   — step out
```

Pressing Enter on an empty line re-runs the previous command, which is useful for stepping repeatedly. You can also step multiple times at once:

```
gdb$ step 5
```

How to use the editor and debugger at the same time: split your terminal with tmux, your desktop environment, or Vim's terminal mode. The editor observes the session passively — you only ever type into the debugger.

If you want a richer in-terminal UI on the gdb side, gdb-dashboard slots in cleanly. It renders threads, breakpoints, source context, and registers as a live dashboard inside gdb without touching the Python API that DVAP hooks into, so the two coexist without conflicts and together feel close to a full IDE setup.

https://github.com/cyrus-and/gdb-dashboard

## References

https://sourceware.org/gdb/current/onlinedocs/gdb.html/Running.html#Running

https://sourceware.org/gdb/current/onlinedocs/gdb.html/Python-API.html#Python-API

