package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"
)

func main() {
	// Create a new Reader to read from os.Stdin
	reader := bufio.NewReader(os.Stdin)

	fmt.Print("Enter a line: ")

	// ReadString reads until the delimiter '\n' is found
	input, err := reader.ReadString('\n')

	if err != nil {
		fmt.Fprintln(os.Stderr, "reading stdin:", err)
		return
	}

	// Remove the trailing newline character (or CRLF)
	// strings.TrimSpace also works if you want to remove all leading/trailing whitespace
	line := strings.TrimRight(input, "\r\n")

	fmt.Println("You entered:", line)
}
