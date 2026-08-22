// Lanceur natif de DubPack Creator.
//
// C'est lui qui fait de l'outil une vraie application: double-clic, page de
// démarrage dans le navigateur, installation silencieuse des dépendances au
// premier lancement, puis supervision du serveur Python. Quand le serveur
// s'arrête avec le code 42 (« mise à jour prête »), il échange l'ancien code
// contre le nouveau — avec retour arrière si la nouvelle version ne démarre
// pas — et relance.
//
// Aucune fenêtre propre: l'interface de l'application EST le navigateur.
package main

import (
	"archive/tar"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"
)

const restartExitCode = 42

// ---------------------------------------------------------------------------
// État partagé avec la page de démarrage
// ---------------------------------------------------------------------------

type status struct {
	mu    sync.Mutex
	Phase string   `json:"phase"` // preparation | installation | maj | demarrage | erreur
	Title string   `json:"title"`
	Lines []string `json:"lines"`
	Error string   `json:"error"`
}

func (s *status) set(phase, title string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.Phase, s.Title = phase, title
	log.Printf("[%s] %s", phase, title)
}

func (s *status) addLine(line string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	line = strings.TrimSpace(line)
	if line == "" {
		return
	}
	s.Lines = append(s.Lines, line)
	if len(s.Lines) > 40 {
		s.Lines = s.Lines[len(s.Lines)-40:]
	}
}

func (s *status) fail(message string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.Phase, s.Error = "erreur", message
	log.Printf("ERREUR: %s", message)
}

func (s *status) snapshot() map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()
	return map[string]any{
		"phase": s.Phase, "title": s.Title,
		"lines": append([]string{}, s.Lines...), "error": s.Error,
	}
}

// ---------------------------------------------------------------------------
// Chemins
// ---------------------------------------------------------------------------

type layout struct {
	data    string // données: projets, modèles, réglages, python, code
	code    string // code de l'application (remplacé par les mises à jour)
	payload string // ressources embarquées (macOS: dans le .app)
}

func resolveLayout() (layout, error) {
	exe, err := os.Executable()
	if err != nil {
		return layout{}, err
	}
	exeDir := filepath.Dir(exe)
	var lay layout
	// Surcharges pour les tests et les usages avancés.
	if override := os.Getenv("DUBPACK_DATA_DIR"); override != "" {
		lay.data = override
		if runtime.GOOS == "darwin" {
			lay.payload = filepath.Join(exeDir, "..", "Resources", "payload")
		}
		if payload := os.Getenv("DUBPACK_PAYLOAD_DIR"); payload != "" {
			lay.payload = payload
		}
		lay.code = filepath.Join(lay.data, "code")
		return lay, os.MkdirAll(lay.data, 0o755)
	}
	if runtime.GOOS == "darwin" {
		home, err := os.UserHomeDir()
		if err != nil {
			return layout{}, err
		}
		lay.data = filepath.Join(home, "Library", "Application Support", "DubPackCreator")
		lay.payload = filepath.Join(exeDir, "..", "Resources", "payload")
	} else {
		// Windows: l'installeur place le lanceur à la racine du dossier de
		// données (%LOCALAPPDATA%\DubPackCreator), code et python à côté.
		lay.data = exeDir
	}
	lay.code = filepath.Join(lay.data, "code")
	return lay, os.MkdirAll(lay.data, 0o755)
}

func (l layout) pythonExe() string {
	if runtime.GOOS == "windows" {
		return filepath.Join(l.data, "python", "python.exe")
	}
	return filepath.Join(l.data, "python", "bin", "python3")
}

var versionRe = regexp.MustCompile(`__version__\s*=\s*"([^"]+)"`)

func codeVersion(codeDir string) string {
	data, err := os.ReadFile(filepath.Join(codeDir, "app", "__init__.py"))
	if err != nil {
		return ""
	}
	if m := versionRe.FindSubmatch(data); m != nil {
		return string(m[1])
	}
	return ""
}

func versionTuple(v string) []int {
	parts := regexp.MustCompile(`\d+`).FindAllString(v, 4)
	out := make([]int, 0, 4)
	for _, p := range parts {
		n := 0
		fmt.Sscanf(p, "%d", &n)
		out = append(out, n)
	}
	return out
}

func versionNewer(a, b string) bool {
	ta, tb := versionTuple(a), versionTuple(b)
	for i := 0; i < len(ta) || i < len(tb); i++ {
		va, vb := 0, 0
		if i < len(ta) {
			va = ta[i]
		}
		if i < len(tb) {
			vb = tb[i]
		}
		if va != vb {
			return va > vb
		}
	}
	return false
}

// ---------------------------------------------------------------------------
// Premier lancement macOS: déballer le code et Python depuis le .app
// ---------------------------------------------------------------------------

func (l layout) unpackPayload(st *status) error {
	if l.payload == "" {
		return nil
	}
	payloadCode := filepath.Join(l.payload, "code")
	if dirExists(payloadCode) {
		embedded := codeVersion(payloadCode)
		installed := codeVersion(l.code)
		// On ne remplace le code que si celui du .app est plus récent: les
		// mises à jour automatiques ont pu aller plus loin que le .dmg.
		if installed == "" || versionNewer(embedded, installed) {
			st.set("preparation", "Installation du code de l'application")
			tmp := l.code + ".new"
			os.RemoveAll(tmp)
			if err := copyDir(payloadCode, tmp); err != nil {
				return fmt.Errorf("copie du code: %w", err)
			}
			os.RemoveAll(l.code + ".old")
			if dirExists(l.code) {
				if err := os.Rename(l.code, l.code+".old"); err != nil {
					return err
				}
			}
			if err := os.Rename(tmp, l.code); err != nil {
				return err
			}
			os.RemoveAll(l.code + ".old")
		}
	}
	pythonTar := filepath.Join(l.payload, "python.tar.gz")
	if !fileExists(l.pythonExe()) && fileExists(pythonTar) {
		st.set("preparation", "Installation de Python (une seule fois)")
		if err := extractTarGz(pythonTar, l.data); err != nil {
			return fmt.Errorf("extraction de Python: %w", err)
		}
	}
	return nil
}

// ---------------------------------------------------------------------------
// Dépendances Python
// ---------------------------------------------------------------------------

func (l layout) ensurePip(st *status) error {
	if runCommand(l.pythonExe(), []string{"-m", "pip", "--version"}, l.data, nil) == nil {
		return nil
	}
	st.set("preparation", "Mise en place de pip")
	return runCommandErr(l.pythonExe(), []string{"-m", "ensurepip", "--upgrade"}, l.data, nil)
}

func fileSHA256(path string) string {
	f, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return ""
	}
	return hex.EncodeToString(h.Sum(nil))
}

func (l layout) ensureDeps(st *status, firstRun bool) error {
	req := filepath.Join(l.code, "requirements.txt")
	stamp := filepath.Join(l.data, "python", ".deps-ok")
	current := fileSHA256(req)
	if current == "" {
		return fmt.Errorf("requirements.txt introuvable dans %s", l.code)
	}
	previous, _ := os.ReadFile(stamp)
	if strings.TrimSpace(string(previous)) == current {
		return nil
	}
	if err := l.ensurePip(st); err != nil {
		return err
	}
	title := "Mise à jour des composants"
	if firstRun {
		title = "Premier lancement : téléchargement des composants (quelques minutes)"
	}
	st.set("installation", title)
	err := l.runPipStreaming(st, []string{
		"install", "--disable-pip-version-check", "--no-warn-script-location",
		"-r", req,
	})
	if err != nil {
		return fmt.Errorf("installation des dépendances: %w", err)
	}
	return os.WriteFile(stamp, []byte(current), 0o644)
}

func (l layout) runPipStreaming(st *status, args []string) error {
	cmd := exec.Command(l.pythonExe(), append([]string{"-m", "pip"}, args...)...)
	cmd.Dir = l.data
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
	hideWindow(cmd)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	cmd.Stderr = cmd.Stdout
	if err := cmd.Start(); err != nil {
		return err
	}
	buf := make([]byte, 4096)
	var partial string
	for {
		n, readErr := stdout.Read(buf)
		if n > 0 {
			partial += string(buf[:n])
			for {
				idx := strings.IndexAny(partial, "\r\n")
				if idx < 0 {
					break
				}
				st.addLine(partial[:idx])
				partial = partial[idx+1:]
			}
		}
		if readErr != nil {
			break
		}
	}
	st.addLine(partial)
	return cmd.Wait()
}

// ---------------------------------------------------------------------------
// Mises à jour (préparées par le serveur dans update/pending)
// ---------------------------------------------------------------------------

func (l layout) applyPendingUpdate(st *status) (string, error) {
	updateDir := filepath.Join(l.data, "update")
	pending := filepath.Join(updateDir, "pending")
	if !dirExists(pending) {
		return "", nil
	}
	version := "?"
	if raw, err := os.ReadFile(filepath.Join(updateDir, "pending.json")); err == nil {
		var info map[string]any
		if json.Unmarshal(raw, &info) == nil {
			if v, ok := info["version"].(string); ok {
				version = v
			}
		}
	}
	st.set("maj", "Application de la mise à jour "+version)

	backup := filepath.Join(updateDir, "backup")
	os.RemoveAll(backup)
	if err := os.MkdirAll(backup, 0o755); err != nil {
		return "", err
	}
	entries, err := os.ReadDir(pending)
	if err != nil {
		return "", err
	}
	moved := []string{}
	for _, entry := range entries {
		target := filepath.Join(l.code, entry.Name())
		if pathExists(target) {
			if err := os.Rename(target, filepath.Join(backup, entry.Name())); err != nil {
				l.restoreBackup()
				os.RemoveAll(pending)
				os.Remove(filepath.Join(updateDir, "pending.json"))
				return "", fmt.Errorf("échange interrompu (%s): retour à la version précédente", err)
			}
		}
		if err := os.Rename(filepath.Join(pending, entry.Name()), target); err != nil {
			l.restoreBackup()
			os.RemoveAll(pending)
			os.Remove(filepath.Join(updateDir, "pending.json"))
			return "", fmt.Errorf("échange interrompu (%s): retour à la version précédente", err)
		}
		moved = append(moved, entry.Name())
	}
	os.RemoveAll(pending)
	os.Remove(filepath.Join(updateDir, "pending.json"))
	applied, _ := json.Marshal(map[string]any{
		"version": version, "at": time.Now().Unix(), "files": moved,
	})
	os.WriteFile(filepath.Join(updateDir, "applied.json"), applied, 0o644)
	log.Printf("mise à jour %s appliquée (%d éléments)", version, len(moved))
	return version, nil
}

func (l layout) restoreBackup() bool {
	backup := filepath.Join(l.data, "update", "backup")
	entries, err := os.ReadDir(backup)
	if err != nil {
		return false
	}
	for _, entry := range entries {
		target := filepath.Join(l.code, entry.Name())
		os.RemoveAll(target)
		os.Rename(filepath.Join(backup, entry.Name()), target)
	}
	os.RemoveAll(backup)
	return true
}

func (l layout) rollbackIfBroken(startedAt time.Time, exitCode int) bool {
	updateDir := filepath.Join(l.data, "update")
	appliedFile := filepath.Join(updateDir, "applied.json")
	if exitCode == 0 || exitCode == restartExitCode || !fileExists(appliedFile) {
		return false
	}
	if time.Since(startedAt) > 30*time.Second {
		return false
	}
	version := "?"
	if raw, err := os.ReadFile(appliedFile); err == nil {
		var info map[string]any
		if json.Unmarshal(raw, &info) == nil {
			if v, ok := info["version"].(string); ok {
				version = v
			}
		}
	}
	log.Printf("le serveur s'est arrêté aussitôt après la mise à jour %s: retour arrière", version)
	if l.restoreBackup() {
		os.Remove(appliedFile)
		message := fmt.Sprintf("La mise à jour %s a été annulée: le serveur s'arrêtait aussitôt (code %d).",
			version, exitCode)
		os.WriteFile(filepath.Join(updateDir, "failed.txt"), []byte(message), 0o644)
		return true
	}
	return false
}

// ---------------------------------------------------------------------------
// Instance unique
// ---------------------------------------------------------------------------

type lockInfo struct {
	Port int `json:"port"`
	PID  int `json:"pid"`
}

func (l layout) lockPath() string { return filepath.Join(l.data, "launcher.json") }

func (l layout) alreadyRunning() (int, bool) {
	raw, err := os.ReadFile(l.lockPath())
	if err != nil {
		return 0, false
	}
	var info lockInfo
	if json.Unmarshal(raw, &info) != nil || info.Port == 0 {
		return 0, false
	}
	client := http.Client{Timeout: 1500 * time.Millisecond}
	resp, err := client.Get(fmt.Sprintf("http://127.0.0.1:%d/api/health", info.Port))
	if err != nil {
		return 0, false
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
	if resp.StatusCode == 200 && strings.Contains(string(body), "dubpack-creator") {
		return info.Port, true
	}
	return 0, false
}

func freePort(preferred int) (int, net.Listener) {
	for port := preferred; port < preferred+25; port++ {
		listener, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
		if err == nil {
			return port, listener
		}
	}
	return 0, nil
}

// ---------------------------------------------------------------------------
// Serveur de la page de démarrage
// ---------------------------------------------------------------------------

func statusServer(listener net.Listener, st *status) *http.Server {
	mux := http.NewServeMux()
	mux.HandleFunc("/launcher-status", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		json.NewEncoder(w).Encode(st.snapshot())
	})
	mux.HandleFunc("/api/health", func(w http.ResponseWriter, r *http.Request) {
		// Le vrai serveur n'est pas encore là: la page saura qu'il faut attendre.
		w.WriteHeader(http.StatusServiceUnavailable)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Cache-Control", "no-store")
		io.WriteString(w, bootPage)
	})
	server := &http.Server{Handler: mux}
	go server.Serve(listener)
	return server
}

// ---------------------------------------------------------------------------
// Boucle principale
// ---------------------------------------------------------------------------

func main() {
	lay, err := resolveLayout()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	logFile, err := os.OpenFile(filepath.Join(lay.data, "launcher.log"),
		os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err == nil {
		if info, statErr := logFile.Stat(); statErr == nil && info.Size() > 2<<20 {
			logFile.Truncate(0)
		}
		log.SetOutput(logFile)
		defer logFile.Close()
	}
	log.Printf("---- lancement (%s %s) ----", runtime.GOOS, runtime.GOARCH)

	// --quit: ferme l'instance en cours puis rend la main (utilisé par
	// l'installeur avant de remplacer les fichiers).
	if len(os.Args) > 1 && os.Args[1] == "--quit" {
		quitRunning(lay)
		return
	}

	// Déjà lancé ? On ouvre simplement un onglet sur l'instance existante.
	if port, running := lay.alreadyRunning(); running {
		log.Printf("instance déjà active sur le port %d", port)
		openBrowser(fmt.Sprintf("http://127.0.0.1:%d", port))
		return
	}

	st := &status{Phase: "preparation", Title: "Démarrage de DubPack Creator"}

	port, listener := freePort(8760)
	if listener == nil {
		st.fail("Aucun port libre entre 8760 et 8785.")
		os.Exit(1)
	}
	lock, _ := json.Marshal(lockInfo{Port: port, PID: os.Getpid()})
	os.WriteFile(lay.lockPath(), lock, 0o644)
	defer os.Remove(lay.lockPath())

	url := fmt.Sprintf("http://127.0.0.1:%d", port)
	boot := statusServer(listener, st)
	openBrowser(url)
	log.Printf("page de démarrage: %s", url)

	firstRun := !fileExists(filepath.Join(lay.data, "python", ".deps-ok"))

	fatal := func(message string) {
		st.fail(message + " — détail dans " + filepath.Join(lay.data, "launcher.log"))
		// On laisse la page d'erreur affichée le temps d'être lue.
		time.Sleep(10 * time.Minute)
		os.Exit(1)
	}

	if err := lay.unpackPayload(st); err != nil {
		fatal(err.Error())
	}
	if !fileExists(lay.pythonExe()) {
		fatal("Python est introuvable dans " + filepath.Join(lay.data, "python") +
			" — réinstalle l'application.")
	}
	if err := lay.ensureDeps(st, firstRun); err != nil {
		fatal(err.Error())
	}

	serverLog, _ := os.OpenFile(filepath.Join(lay.data, "server.log"),
		os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if serverLog != nil {
		if info, statErr := serverLog.Stat(); statErr == nil && info.Size() > 5<<20 {
			serverLog.Truncate(0)
		}
		defer serverLog.Close()
	}

	retriedAfterRollback := false
	handedOff := false
	for {
		if _, err := lay.applyPendingUpdate(st); err != nil {
			log.Printf("mise à jour: %s", err)
		}
		if err := lay.ensureDeps(st, false); err != nil {
			fatal(err.Error())
		}

		st.set("demarrage", "Démarrage du serveur")
		if !handedOff {
			// On libère le port pour le serveur Python; la page de démarrage
			// bascule d'elle-même vers l'application dès qu'il répond.
			boot.Close()
			listener.Close()
			time.Sleep(150 * time.Millisecond)
			handedOff = true
		}

		cmd := exec.Command(lay.pythonExe(),
			filepath.Join(lay.code, "run_server.py"), "--port", fmt.Sprint(port))
		cmd.Dir = lay.code
		cmd.Env = append(os.Environ(),
			"DUBPACK_SUPERVISED=1",
			"DUBPACK_DATA_DIR="+lay.data,
			"PYTHONUTF8=1",
			"PYTHONIOENCODING=utf-8",
		)
		if serverLog != nil {
			fmt.Fprintf(serverLog, "\n---- serveur %s (port %d) ----\n",
				time.Now().Format("2006-01-02 15:04:05"), port)
			cmd.Stdout = serverLog
			cmd.Stderr = serverLog
		}
		hideWindow(cmd)
		startedAt := time.Now()
		if err := cmd.Start(); err != nil {
			fatal("Impossible de démarrer le serveur: " + err.Error())
		}
		log.Printf("serveur démarré (pid %d, port %d)", cmd.Process.Pid, port)
		err := cmd.Wait()
		exitCode := 0
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
		} else if err != nil {
			exitCode = 1
		}
		log.Printf("serveur arrêté (code %d)", exitCode)

		if exitCode == restartExitCode {
			continue
		}
		if !retriedAfterRollback && lay.rollbackIfBroken(startedAt, exitCode) {
			retriedAfterRollback = true
			continue
		}
		break
	}
	log.Printf("---- fin ----")
}

func quitRunning(lay layout) {
	port, running := lay.alreadyRunning()
	if !running {
		return
	}
	log.Printf("--quit: arrêt de l'instance sur le port %d", port)
	client := http.Client{Timeout: 3 * time.Second}
	client.Post(fmt.Sprintf("http://127.0.0.1:%d/api/quit", port),
		"application/json", strings.NewReader(`{"force": true}`))
	for i := 0; i < 30; i++ {
		if _, still := lay.alreadyRunning(); !still {
			return
		}
		time.Sleep(500 * time.Millisecond)
	}
}

// ---------------------------------------------------------------------------
// Utilitaires fichiers
// ---------------------------------------------------------------------------

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func dirExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func pathExists(path string) bool {
	_, err := os.Lstat(path)
	return err == nil
}

func copyDir(src, dst string) error {
	return filepath.WalkDir(src, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(src, path)
		target := filepath.Join(dst, rel)
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		in, err := os.Open(path)
		if err != nil {
			return err
		}
		defer in.Close()
		info, _ := d.Info()
		mode := os.FileMode(0o644)
		if info != nil && info.Mode()&0o111 != 0 {
			mode = 0o755
		}
		out, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, mode)
		if err != nil {
			return err
		}
		defer out.Close()
		_, err = io.Copy(out, in)
		return err
	})
}

func extractTarGz(archive, dest string) error {
	f, err := os.Open(archive)
	if err != nil {
		return err
	}
	defer f.Close()
	gz, err := gzip.NewReader(f)
	if err != nil {
		return err
	}
	defer gz.Close()
	reader := tar.NewReader(gz)
	var links [][2]string
	for {
		header, err := reader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		name := filepath.Clean(header.Name)
		if strings.HasPrefix(name, "..") {
			continue
		}
		target := filepath.Join(dest, name)
		switch header.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0o755); err != nil {
				return err
			}
		case tar.TypeReg:
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return err
			}
			out, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC,
				os.FileMode(header.Mode)&0o777)
			if err != nil {
				return err
			}
			if _, err := io.Copy(out, reader); err != nil {
				out.Close()
				return err
			}
			out.Close()
		case tar.TypeSymlink:
			// Les liens sont posés en dernier: leur cible n'existe pas toujours encore.
			links = append(links, [2]string{header.Linkname, target})
		}
	}
	sort.Slice(links, func(i, j int) bool { return links[i][1] < links[j][1] })
	for _, link := range links {
		os.MkdirAll(filepath.Dir(link[1]), 0o755)
		os.Remove(link[1])
		if err := os.Symlink(link[0], link[1]); err != nil {
			return err
		}
	}
	return nil
}

func runCommand(exe string, args []string, dir string, env []string) error {
	cmd := exec.Command(exe, args...)
	cmd.Dir = dir
	if env != nil {
		cmd.Env = append(os.Environ(), env...)
	}
	hideWindow(cmd)
	return cmd.Run()
}

func runCommandErr(exe string, args []string, dir string, env []string) error {
	cmd := exec.Command(exe, args...)
	cmd.Dir = dir
	if env != nil {
		cmd.Env = append(os.Environ(), env...)
	}
	hideWindow(cmd)
	out, err := cmd.CombinedOutput()
	if err != nil {
		tail := string(out)
		if len(tail) > 400 {
			tail = tail[len(tail)-400:]
		}
		return fmt.Errorf("%s: %s", err, strings.TrimSpace(tail))
	}
	return nil
}
