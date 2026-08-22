package main

// Page affichée pendant la préparation: même palette que l'application.
// Elle bascule d'elle-même vers l'interface dès que le serveur répond.
const bootPage = `<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DubPack Creator</title>
<style>
:root { --bg:#0f1420; --panel:#171d29; --line:#263042; --text:#e6eaf2;
        --muted:#8b94a7; --accent:#f97316; --ok:#34d399; --err:#fb7185; }
* { box-sizing:border-box; margin:0; }
body { background:var(--bg); color:var(--text); min-height:100vh;
       display:flex; align-items:center; justify-content:center;
       font:15px/1.6 -apple-system, "Segoe UI", system-ui, sans-serif; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:14px;
        padding:34px 38px; width:min(560px, 92vw); }
h1 { font-size:20px; display:flex; align-items:center; gap:10px; }
h1 svg { width:26px; height:26px; stroke:var(--accent); fill:none;
         stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
#title { color:var(--muted); margin:10px 0 18px; min-height:1.5em; }
.bar { height:6px; border-radius:3px; background:var(--line); overflow:hidden; }
.bar i { display:block; height:100%; width:38%; border-radius:3px;
         background:var(--accent); animation:slide 1.3s ease-in-out infinite; }
@keyframes slide { 0%{transform:translateX(-110%)} 100%{transform:translateX(400%)} }
#lines { margin-top:16px; padding:10px 12px; border-radius:8px; background:#10151f;
         font:11.5px/1.65 ui-monospace, Menlo, Consolas, monospace; color:var(--muted);
         max-height:180px; overflow-y:auto; white-space:pre-wrap;
         overflow-wrap:anywhere; display:none; }
#error { display:none; margin-top:16px; padding:12px 14px; border-radius:8px;
         background:rgba(251,113,133,.09); border:1px solid rgba(251,113,133,.35);
         color:var(--err); white-space:pre-wrap; overflow-wrap:anywhere; }
.hint { margin-top:14px; color:var(--muted); font-size:12.5px; }
</style>
</head>
<body>
<div class="card">
  <h1><svg viewBox="0 0 24 24"><path d="M9 5a3 3 0 0 1 3 -3a3 3 0 0 1 3 3v5a3 3 0 0 1 -3 3a3 3 0 0 1 -3 -3l0 -5"/><path d="M5 10a7 7 0 0 0 14 0"/><path d="M8 21l8 0"/><path d="M12 17l0 4"/></svg>
      DubPack Creator</h1>
  <p id="title">Démarrage…</p>
  <div class="bar" id="bar"><i></i></div>
  <div id="lines"></div>
  <div id="error"></div>
  <p class="hint">Cette page s'ouvrira toute seule sur l'application dès qu'elle est prête.
     Le premier lancement télécharge ses composants : compte quelques minutes.</p>
</div>
<script>
async function tick() {
  // Le serveur de l'application a-t-il pris le relais ?
  try {
    const health = await fetch('/api/health', { cache: 'no-store' });
    if (health.ok) { location.reload(); return; }
  } catch {}
  try {
    const res = await fetch('/launcher-status', { cache: 'no-store' });
    if (res.ok) {
      const s = await res.json();
      document.getElementById('title').textContent = s.title || 'Préparation…';
      const lines = document.getElementById('lines');
      if (s.lines && s.lines.length) {
        lines.style.display = 'block';
        lines.textContent = s.lines.join('\n');
        lines.scrollTop = lines.scrollHeight;
      }
      if (s.phase === 'erreur') {
        const box = document.getElementById('error');
        box.style.display = 'block';
        box.textContent = s.error || 'Une erreur est survenue.';
        document.getElementById('bar').style.display = 'none';
        return; // on arrête de tourner: l'erreur doit rester lisible
      }
    }
  } catch {}
  setTimeout(tick, 700);
}
tick();
</script>
</body>
</html>`
