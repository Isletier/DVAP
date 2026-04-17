## LLDB

## Loading the server

```
(lldb) command script import /path/to/DVAP_lldb_server.py
```

To load it automatically on every lldb start, add the same line to `~/.lldbinit`:

```
command script import /path/to/DVAP_lldb_server.py
```

The server prints `[DVAP] Listening on 127.0.0.1:56789` on success. If the port is already in use, it will say so and skip starting.

## DVAP commands

Once the script is loaded, the following commands are available inside lldb:

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
(lldb) script lldb._dvap_port = 12345
(lldb) command script import /path/to/DVAP_lldb_server.py
```

Or if the server is already running:

```
(lldb) dvap-set port 12345
(lldb) dvap-start
```

## If you're coming from an IDE

Compile with debug symbols — the `-g` flag on most compilers:

```
cc -g -o myprogram myprogram.c
```

For build systems, set the debug configuration (CMake: `-DCMAKE_BUILD_TYPE=Debug`, etc.).

Start a session:

```
shell$ lldb ./myprogram
(lldb) run arg1 arg2
```

Or attach to a running process:

```
shell$ lldb -p <pid>
```

Set a breakpoint:

```
(lldb) b main.c:20
(lldb) b my_function
```

Navigate execution:

```
(lldb) continue   (or: c)     — resume
(lldb) step       (or: s)     — step into
(lldb) next       (or: n)     — step over
(lldb) finish                 — step out
```

How to use the editor and debugger at the same time: split your terminal with tmux, your desktop environment, or Vim's terminal mode. The editor observes the session passively — you only ever type into the debugger.

If you want a richer in-terminal UI on the lldb side, lldbinit is a heavily extended `.lldbinit` configuration that adds formatted output, convenience commands, and better disassembly display. It works entirely through lldb's scripting layer and coexists with DVAP without conflicts.

https://github.com/gdbinit/lldbinit

## References

https://lldb.llvm.org/use/tutorial.html

https://lldb.llvm.org/use/python-reference.html

