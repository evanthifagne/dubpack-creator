//go:build !windows

package main

import (
	"os/exec"
	"runtime"
)

func hideWindow(cmd *exec.Cmd) {}

func openBrowser(url string) error {
	if runtime.GOOS == "darwin" {
		return exec.Command("open", url).Start()
	}
	return exec.Command("xdg-open", url).Start()
}
