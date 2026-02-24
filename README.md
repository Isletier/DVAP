## DVAP (debug view adapter protocol)

NOTE: Current implementation is very WIP and partially vibecoded (I really suck at Python). DO NOT USE IT unless you want to participate in its development.

## gdb usage:

```
shell$ gdb
gdb$ source ./DVAP_gdb_server.py
```

Or alternatively, just add the same line to the .gdbinit file in your $HOME directory; this will launch the server every time gdb starts:

```
source ./DVAP_gdb_server.py
```

## Neovim client:

https://github.com/Isletier/nvim-DVAP-ui

https://github.com/Isletier/nvim-DVAP

## About the concept

REPLs are cool, but no matter how well their UI is implemented, they suck at one particular thing: displaying text and, as a consequence, execution flow.

On the other side of the board, you have DAP. It was meant to solve the editor*debugger integration issue but ended up requiring same amount of configuration variations while significantly reducing debugger features that are language/debugger dependent.

So, I think I have a solution: let the debugger's native UI fully define the current state of the debugging session and its launch, while the editor just stays a passive observer of the current state of things—in particular, threads, breakpoints, and their positions.

I'm pretty sure this minimalistic interface could conform to any possible combination of editor/debugger/language, require zero non-UI configuration from the client side, and is generally more idiomatic for text interfaces and editors than the DAP IDE-like approach. All you need to do to start observing the debug session is just pass an endpoint to the DVAP server.

## for VS code/DAP victims like me:

- How to start debugging without an IDE?

    1. You need to compile with debug symbols: the `-g` option on most compilers, or set the debug configuration for your build system.
    2. Type this in your shell:

```
shell$ gdb { path_to_debugee }
gdb$   run { args_for_debugee }
```

- How to set a breakpoint?

```
gdb$ b main.c:20
```

- How to continue/step in/step out/step over?

```
gdb$ continue
gdb$ step
gdb$ next
gdb$ finish
```

Or alternetivly:

```
gdb$ c
gdb$ s
gdb$ n
gdb$ f
```

Note that on an empty line, the Enter key will execute the previous instruction again. You can also do things like this:

```
gdb$ step 5
```

- How can I observe an editor and input commands to the debugger at the same time?

Use your desktop environment, terminal, tmux, or Vim terminal mode to split the windows and quickly switch between them.

## References

https://sourceware.org/gdb/current/onlinedocs/gdb.html/Running.html#Running

https://sourceware.org/gdb/current/onlinedocs/gdb.html/Python-API.html#Python-API

https://microsoft.github.io/debug-adapter-protocol/specification

