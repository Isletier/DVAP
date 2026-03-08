package main

import (
	"encoding/json"
	"fmt"
	"net"
)

// Структура JSON-RPC запроса для Delve
type RPCRequest struct {
	Method string        `json:"method"`
	Params []interface{} `json:"params"`
	ID     int           `json:"id"`
}

type RPCResponse struct {
	Result json.RawMessage `json:"result"`
	Error  interface{}     `json:"error"`
}

type Goroutine struct {
	ID   int    `json:"id"`
	File string `json:"file"`
	Line int    `json:"line"`
}

type Breakpoint struct {
	ID        int    `json:"id"`
	File      string `json:"file"`
	Line      int    `json:"line"`
	Addr      uint64 `json:"addr"`
	Enabled   bool   `json:"enabled"`
	Cond      string `json:"Cond"`
	WatchExpr string `json:"WatchExpr"`
}

// Общий стейт вашего адаптера
type DebugState struct {
	Goroutines  []Goroutine
	Breakpoints []Breakpoint
}

func call(conn net.Conn, method string, params []interface{}, id int) {
	req := RPCRequest{Method: method, Params: params, ID: id}
	json.NewEncoder(conn).Encode(req)

	var res interface{}
	json.NewDecoder(conn).Decode(&res)
	
	fmt.Printf("--- %s ---\n", method)
	out, _ := json.MarshalIndent(res, "", "  ")
	fmt.Println(string(out))
}

func main() {
	// 1. Подключаемся к Delve по TCP
	conn, err := net.Dial("tcp", "localhost:9200")
	if err != nil {
		panic(err)
	}
	defer conn.Close()

	// 1. Точки останова (Breakpoints)
	// Параметр: bool (true - включить скрытые внутренние точки dlv)
	call(conn, "RPCServer.ListBreakpoints", []interface{}{map[string]bool{"All": true}}, 1)

	// 2. Потоки (Threads)
	call(conn, "RPCServer.ListThreads", []interface{}{nil}, 2)

	// 3. Горутины (Goroutines)
	// Параметры: start (индекс), count (количество)
	call(conn, "RPCServer.ListGoroutines", []interface{}{map[string]int{"Start": 0, "Count": 10}}, 3)
}
