package main

import "fmt"
import "os"
import "os/exec"
import "strings"
import "strconv"
import "syscall"
import "net"
import "time"

var listen_port = 9200
var listen_arg = fmt.Sprintf("--listen=:%d", listen_port)

var dvap_listen_port = 9000
var dvap_listen_arg = fmt.Sprintf("--dvap_listen=:%d", dvap_listen_port)

var mandatory_args  = []string {"--headless", "", "--api-version", "=2", "--accept-multiclient", ""}
var dvap_arguments  = []string {""}

func check_mandatory(arg string) bool {
	for i := 0; i < len(mandatory_args); i+= 2 {
		if strings.Contains(arg, mandatory_args[i]) {
			return true
		}
	}

	return false;
}

func waitForPort(port int, timeout time.Duration) error {
	address := net.JoinHostPort("localhost", strconv.Itoa(port))
	deadline := time.Now().Add(timeout)

	for time.Now().Before(deadline) {
		conn, err := net.DialTimeout("tcp", address, 100*time.Millisecond)
		if err == nil {
			conn.Close()
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}

	return fmt.Errorf("timeout waiting for port %d", port)
}

func main() {
	user_args := os.Args[1:]

	final_args := []string{}
	for i, arg := range user_args {
		if arg == "--" {
			break;
		}

		if strings.Contains(arg, "--listen=:") {
			var err error
			listen_port, err = strconv.Atoi(arg[9:])
			if err != nil {
				fmt.Printf("Error parsing listen arg")
				return
			}

			listen_arg = fmt.Sprintf("--listen=:%d", listen_port)
			user_args[i] = ""
			continue
		}

		if strings.Contains(arg, "--dvap_listen=:") {
			var err error
			dvap_listen_port, err = strconv.Atoi(arg[9:])
			if err != nil {
				fmt.Printf("Error parsing listen arg")
				return
			}

			dvap_listen_arg = fmt.Sprintf("--listen=:%d", dvap_listen_port)
			user_args[i] = ""
			continue
		}

		if check_mandatory(arg) {
			user_args[i] = ""
			continue
		}
	}

	for i := 0; i < len(mandatory_args); i+=2 {
		final_args = append(final_args, mandatory_args[i] + mandatory_args[i + 1])
	}

	final_args = append(final_args, listen_arg)

	for _, arg := range user_args {
		if arg != "" {
			final_args = append(final_args, arg)
		}
	}

	headless_dlv := exec.Command("dlv", final_args...)
	f, _ := os.OpenFile(os.DevNull, os.O_RDWR, 0)

	headless_dlv.Stdin = f
	headless_dlv.Stdout = os.Stdout
	headless_dlv.Stderr = os.Stderr

	headless_dlv.SysProcAttr = &syscall.SysProcAttr{
		Setpgid: true,
		Noctty:  false,
	}

	if err := headless_dlv.Start(); err != nil {
		fmt.Printf("Error starting process: %v\n", err)
		return
	}

	fmt.Printf("Waiting for Delve on port %d...\n", listen_port)
	if err := waitForPort(listen_port, 10*time.Second); err != nil {
		fmt.Printf("Wait error: %v\n", err)
		headless_dlv.Process.Kill()
		return
	}

	if err := headless_dlv.Process.Release(); err != nil {
		fmt.Printf("Error releasing process: %v\n", err)
	}

	return
}

