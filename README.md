## DVAP (Debug View Adapter Protocol)

NOTE: Current implementation is still very WIP, but i try my best to make it better.

## About the concept

REPLs are cool, but no matter how well their UI is implemented, they suck at one particular thing: displaying text and, as a consequence, execution flow.

On the other side of the board, you have DAP. It was meant to solve the editor/debugger integration issue but ended up requiring the same amount of configuration variations while significantly reducing debugger features that are language/debugger dependent.

DVAP takes a different approach: let the debugger's native UI fully define the current state of the debugging session and its launch, while the editor stays a passive observer—tracking threads, breakpoints, and their positions.

This minimalistic interface can conform to any combination of editor/debugger/language, requires zero non-UI configuration from the client side, and is more idiomatic for text interfaces than the DAP/IDE approach. All you need to start observing a debug session is pass an endpoint to the DVAP server.

## Debuggers

- [GDB](gdb/)
- [LLDB](lldb/)
- [Go / Dvelve](dvelve/) — fork of Delve with DVAP support

## Clients

At this moment, protocol is only supported for the neovim client.

https://github.com/Isletier/nvim-DVAP-ui

https://github.com/Isletier/nvim-DVAP

## Protocol

The server exposes an SSE endpoint at `http://127.0.0.1:<port>/events` (default port: 56789).

Each message is a single `data:` line containing a sequence of records. Records are separated by `||`; fields within a record by `;;`.

Record types:

```
selected;;{id};;goroutine
selected;;{id};;thread
thread;;{id};;goroutine;;{file};;{line};;{os_thread_id}
thread;;{id};;thread;;{file};;{line};;{goroutine_id}
bp;;{id};;{file};;{line};;{nonconditional};;{enabled}
```

You can inspect the stream directly:

```
curl http://localhost:56789/events
```

## References

https://sourceware.org/gdb/current/onlinedocs/gdb.html/Python-API.html#Python-API

https://lldb.llvm.org/use/python-reference.html

https://microsoft.github.io/debug-adapter-protocol/specification

