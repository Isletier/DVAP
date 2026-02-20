## DVAP (debug view adapter protocol)

NOTE: current implementation is very WIP, and partially vibecoded(i really suck at python), DO NOT USE IT unless you want to participate in its development

## gdb usage:

```
shell$ gdb
gdb$ source ./DVAP_gdb_server.py
```

Or alternativly, just add same line to .gdbinit file in your $HOME directory, this will launch server on each start of the gdb:

```
source ./DVAP_gdb_server.py
```

## Neovim client:

https://github.com/Isletier/nvim/tree/dev

## About the concept

Repl's are cool, but no matter how well their ui is implemented they suck at one particular thing - displaying text and, as a consequences, execution flow.

On the other side of the board you have DAP, that ment to solve editors*debuggers integration issue, but end up requiring the same amount of configuration variations as well as significantly reducing debugger features, that are language/debugger dependent.

So,  think that i have a solution for this - let the debugger native ui fully define current state of the debuging session, as well as it's launch, while the editor just stays a passive observer of current state of the things, in particullar - threads, breakpoints and their positions.

I'm pretty sure that this minimalistic interface could conform any possible combination of editor/debugger/language as well as require 0 non-ui configuration from the client side and is generally more idiomatic for text interfaces and editors in general then DAP IDE-like approuch. All what you need to do to start observing the debug session - just pass an enpoint to DVAP server.



## for VS code/DAP victims like me:

- How to start a debugging without ide?

    1. You need to compile it with debug symbols: '-g' option on most of the compilers, or set the debug configuration for your build system.
    2. type this in your shell:

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

or alternetivly:

```
gdb$ c
gdb$ s
gdb$ n
gdb$ f
```

Note that on empty line, enter key will execute previous instruction again, you can also do things like this:
 
```
gdb$ step 5
```

- How can observe an editor and input commands to the debugger?

Use your desktop environment/terminal/tmux/vim terminal mode to split the windows and quickly switch between them.

## References

https://sourceware.org/gdb/current/onlinedocs/gdb.html/Running.html#Running

https://sourceware.org/gdb/current/onlinedocs/gdb.html/Python-API.html#Python-API

https://microsoft.github.io/debug-adapter-protocol/specification



