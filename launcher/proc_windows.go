//go:build windows

package main

import (
	"os/exec"
	"syscall"
)

// hideWindow évite qu'une fenêtre de console apparaisse pour chaque
// sous-processus: le lanceur est une application graphique sans console.
func hideWindow(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x08000000, // CREATE_NO_WINDOW
	}
}

func openBrowser(url string) error {
	cmd := exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	hideWindow(cmd)
	return cmd.Start()
}
