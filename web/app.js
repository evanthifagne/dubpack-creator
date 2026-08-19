/* DubPack Creator — interface locale */
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  caps: null,
  project: null,
  selected: null,
  pollTimer: null,
  saveTimer: null,
  peaks: [],
  pendingFile: null,
  previewAudio: new Audio(),
  filter: '',
  settings: {},
  jobs: new Map(),
  watching: null,
  jobTicker: null,
  gameCandidates: [],
};

/* ----------------------------------------------------------------- utils */
const fmt = (s) => {
  s = Math.max(0, Number(s) || 0);
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(2).padStart(5, '0')}`;
};
const num = (v, fallback = 0) => {
  const n = parseFloat(String(v).replace(',', '.'));
  return Number.isFinite(n) ? n : fallback;
};

function toast(message, kind = '') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = message;
  $('#toasts').append(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, kind === 'err' ? 8000 : 4000);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = `Erreur ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch { /* réponse non JSON */ }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

/* ------------------------------------------------------------ diagnostic */
async function loadCaps() {
  state.caps = await api('/api/capabilities');
  const c = state.caps;
  const badges = [
    ['ffmpeg', !!c.ffmpeg],
    ['Theora', !!c.theora],
    [c.asr_engines[0] || 'Whisper manquant', c.asr_engines.length > 0],
    ['yt-dlp', !!c.yt_dlp],
    [c.demucs ? 'Demucs' : 'Demucs absent', !!c.demucs],
  ];
  $('#caps').innerHTML = badges
    .map(([label, ok]) => `<span class="cap ${ok ? 'ok' : 'no'}">${ok ? '●' : '○'} ${label}</span>`)
    .join('');

  for (const sel of ['#set-model', '#re-model']) {
    $(sel).innerHTML = c.models
      .map((m) => `<option value="${m}"${m === c.default_model ? ' selected' : ''}>${m}</option>`)
      .join('');
  }
  if (!c.picker) {
    // Sans tkinter, pas de boîte de dialogue système: on saisit le chemin à la main.
    const note = "Boîte de dialogue système indisponible sur cette installation de Python. "
      + 'Colle le chemin du dossier dans le champ juste en dessous.';
    ['#btn-pick-game', '#btn-pick-folder'].forEach((sel) => {
      const btn = $(sel);
      if (!btn) return;
      btn.disabled = true;
      btn.title = note;
    });
  }
  if (!c.ffmpeg) {
    toast(c.ffmpeg_error || 'ffmpeg est introuvable.', 'err');
    // Sans ffmpeg rien ne marche: on montre directement quoi faire.
    setTimeout(openDiagnostics, 400);
  }
  if (!c.asr_engines.length) toast('Aucun moteur de transcription installé (pip install faster-whisper).', 'err');
  else if (!c.theora) toast("ffmpeg n'a pas libtheora : l'export vidéo échouera.", 'err');
}

/* --------------------------------------------------------------- accueil */
function settingsFromForm() {
  return {
    model: $('#set-model').value,
    language: $('#set-language').value,
    speakers: $('#set-speakers').value,
    max_line: num($('#set-maxline').value, 9),
  };
}

function refreshCreateButton() {
  const ready = !!state.pendingFile || $('#url-input').value.trim().length > 8;
  $('#btn-create').disabled = !ready;
  const busy = state.jobs.size;
  $('#create-hint').textContent = !ready
    ? 'Ajoute d\'abord un fichier ou un lien.'
    : busy
      ? `Tout se passe en local. ${busy} tâche(s) en cours : celle-ci se mettra à la suite.`
      : 'Tout se passe en local sur ta machine.';
}

function setupHome() {
  const dz = $('#dropzone');
  const input = $('#file-input');

  ['dragenter', 'dragover'].forEach((ev) => dz.addEventListener(ev, (e) => {
    e.preventDefault(); dz.classList.add('over');
  }));
  ['dragleave', 'drop'].forEach((ev) => dz.addEventListener(ev, (e) => {
    e.preventDefault(); dz.classList.remove('over');
  }));
  dz.addEventListener('drop', (e) => {
    const file = e.dataTransfer?.files?.[0];
    if (file) pickFile(file);
  });
  $('#btn-pick').addEventListener('click', () => input.click());
  input.addEventListener('change', () => { if (input.files[0]) pickFile(input.files[0]); });
  $('#url-input').addEventListener('input', () => {
    if ($('#url-input').value.trim()) { state.pendingFile = null; $('#picked').hidden = true; }
    refreshCreateButton();
  });
  $('#btn-create').addEventListener('click', createProject);
  $('#btn-home').addEventListener('click', () => showHome());
  refreshCreateButton();
}

function pickFile(file) {
  state.pendingFile = file;
  $('#url-input').value = '';
  const mb = (file.size / 1048576).toFixed(1);
  $('#picked').textContent = `✓ ${file.name} (${mb} Mo)`;
  $('#picked').hidden = false;
  refreshCreateButton();
}

async function createProject() {
  const settings = settingsFromForm();
  const body = new FormData();
  body.append('settings', JSON.stringify(settings));
  if (state.pendingFile) body.append('file', state.pendingFile);
  else body.append('url', $('#url-input').value.trim());

  $('#btn-create').disabled = true;
  try {
    const res = await api('/api/projects/import', { method: 'POST', body });
    openJob(res.job, res.job.title || 'Création du dub pack', async () => {
      // Si l'utilisateur travaille ailleurs, on ne lui vole pas l'ecran.
      const onHome = !$('#view-home').hidden;
      if (onHome) {
        await openProject(res.project_id);
        toast('Dub pack généré. Vérifie les répliques et les personnages.', 'ok');
      } else {
        loadProjects();
        toast('Un dub pack est prêt : retrouve-le dans « Mes projets ».', 'ok');
      }
    });
    // On libere le formulaire: l'utilisateur peut en lancer un autre tout de suite.
    state.pendingFile = null;
    $('#url-input').value = '';
    $('#picked').hidden = true;
    $('#file-input').value = '';
    refreshCreateButton();
  } catch (err) {
    toast(err.message, 'err');
  } finally {
    $('#btn-create').disabled = false;
  }
}

async function loadProjects() {
  const list = await api('/api/projects');
  const box = $('#project-list');
  if (!list.length) {
    box.innerHTML = '<p class="muted small">Aucun projet pour le moment.</p>';
    return;
  }
  box.innerHTML = '';
  for (const p of list) {
    const card = document.createElement('div');
    card.className = 'project-card';
    const chars = p.characters?.filter(Boolean).join(', ') || '—';
    card.innerHTML = `<div style="min-width:0">
        <h3>${escapeHtml(p.name)}</h3>
        <p>${p.lines} répliques · ${escapeHtml(chars)}</p>
      </div>
      <button class="pc-del" title="Supprimer">🗑</button>`;
    card.addEventListener('click', (e) => {
      if (e.target.closest('.pc-del')) return;
      openProject(p.id);
    });
    $('.pc-del', card).addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!confirm(`Supprimer « ${p.name} » et tous ses fichiers ?`)) return;
      await api(`/api/projects/${p.id}`, { method: 'DELETE' });
      loadProjects();
    });
    box.append(card);
  }
}

const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ------------------------------------------------------------------ jobs */
/* Les taches vivent cote serveur dans une file a un seul poste. Ici on les
   suit toutes en parallele: la fenetre de detail n'est qu'une vue sur l'une
   d'elles, et sa fermeture n'interrompt rien. */
const clock = (seconds) => {
  seconds = Math.max(0, Math.round(seconds));
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m >= 60) return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
};

function trackJob(job, title, onDone) {
  state.jobs.set(job.id, {
    id: job.id,
    title: title || job.title || 'Traitement',
    onDone,
    started: Date.now(),
    lastProgress: 0,
    lastMove: Date.now(),
    samples: [],
    snapshot: job,
  });
  startJobWatcher();
}

function openJob(job, title, onDone) {
  trackJob(job, title, onDone);
  showJobWindow(job.id);
}

function showJobWindow(jobId) {
  const entry = state.jobs.get(jobId);
  if (!entry) return;
  state.watching = jobId;
  $('#job-title').textContent = entry.title;
  $('#job-overlay').hidden = false;
  $('#btn-cancel-job').onclick = async () => {
    if (!confirm('Annuler cette tâche ?')) return;
    await api(`/api/jobs/${jobId}/cancel`, { method: 'POST' }).catch(() => {});
  };
  $('#btn-background-job').onclick = hideJobWindow;
  renderJobWindow();
}

function hideJobWindow() {
  state.watching = null;
  $('#job-overlay').hidden = true;
}

/* --- boucle unique de surveillance ------------------------------------- */
function startJobWatcher() {
  if (state.jobTicker) return;
  state.jobTicker = setInterval(() => {
    renderJobWindow();
    renderDock();
  }, 500);
  pollJobs();
}

function stopJobWatcher() {
  clearInterval(state.jobTicker);
  state.jobTicker = null;
  clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

async function pollJobs() {
  clearTimeout(state.pollTimer);
  const ids = [...state.jobs.keys()];
  if (!ids.length) { stopJobWatcher(); renderDock(); return; }

  await Promise.all(ids.map(async (id) => {
    const entry = state.jobs.get(id);
    if (!entry) return;
    let job;
    try {
      job = await api(`/api/jobs/${id}`);
    } catch {
      state.jobs.delete(id);
      return;
    }
    if (job.progress > entry.lastProgress + 0.0005) {
      entry.lastProgress = job.progress;
      entry.lastMove = Date.now();
      entry.samples.push({ at: Date.now(), p: job.progress });
      if (entry.samples.length > 30) entry.samples.shift();
    }
    entry.snapshot = job;

    if (['done', 'error', 'cancelled'].includes(job.status)) {
      state.jobs.delete(id);
      if (state.watching === id) hideJobWindow();
      finishJob(entry, job);
    }
  }));

  renderJobWindow();
  renderDock();
  if (state.jobs.size) state.pollTimer = setTimeout(pollJobs, 700);
  else stopJobWatcher();
}

function finishJob(entry, job) {
  if (job.status === 'done') {
    entry.onDone?.(job.result);
  } else if (job.status === 'error') {
    toast(`${entry.title} — ${job.error || 'échec'}`, 'err');
  } else {
    toast(`${entry.title} — annulé`);
  }
}

/* --- estimation du temps restant --------------------------------------- */
function estimateRemaining(entry) {
  if (!entry || entry.samples.length < 2) return null;
  // On se cale sur les dernieres mesures: le chargement du modele au debut
  // n'est pas representatif du rythme reel.
  const recent = entry.samples.slice(-8);
  const first = recent[0];
  const last = recent[recent.length - 1];
  const dp = last.p - first.p;
  const dt = (last.at - first.at) / 1000;
  if (dp <= 0.004 || dt <= 0) return null;
  const remaining = (1 - last.p) * (dt / dp) - (Date.now() - last.at) / 1000;
  if (!Number.isFinite(remaining) || remaining < 1 || remaining > 6 * 3600) return null;
  return Math.max(0, remaining);
}

function noteFor(job, elapsed) {
  const label = (job.label || '').toLowerCase();
  if (label.includes('téléchargement du modèle')) {
    return 'Premier lancement avec ce modèle : il se télécharge une seule fois, '
      + 'ensuite il est réutilisé instantanément.';
  }
  if (label.includes('modèle') && elapsed > 20) {
    return 'Le modèle de transcription se met en place. Cette étape ne montre pas '
      + "d'avancement, c'est normal.";
  }
  if (label.includes('theora') || label.includes('dub_video')) {
    return "L'encodage de la vidéo est l'étape la plus lente : elle dépend de la "
      + 'durée du clip, pas du nombre de répliques.';
  }
  if (job.kind === 'setup-demucs' && elapsed > 20) {
    return "PyTorch pèse environ 2 Go : laisse tourner, il n'y a rien à faire.";
  }
  if (job.status === 'queued') {
    return 'Cette tâche démarrera dès que la précédente sera terminée. '
      + 'Les tâches lourdes se font une par une pour ne pas se ralentir entre elles.';
  }
  return null;
}

/* --- rendu -------------------------------------------------------------- */
function renderJobWindow() {
  if (!state.watching) return;
  const entry = state.jobs.get(state.watching);
  if (!entry) { hideJobWindow(); return; }
  const job = entry.snapshot || {};
  const queued = job.status === 'queued';
  const elapsed = (Date.now() - entry.started) / 1000;
  const stalled = (Date.now() - entry.lastMove) / 1000 > 6;

  const bar = $('#job-bar');
  const waiting = queued || (stalled && entry.lastProgress < 0.995);
  bar.classList.toggle('waiting', waiting);
  if (!waiting) bar.style.width = `${((job.progress || 0) * 100).toFixed(1)}%`;

  $('#job-pct').textContent = queued
    ? 'en attente'
    : `${Math.round((job.progress || 0) * 100)} %`;

  let time = `écoulé ${clock(elapsed)}`;
  const eta = queued ? null : estimateRemaining(entry);
  if (eta !== null) time += ` · restant ~${clock(eta)}`;
  else if (!queued && stalled) time += ' · en cours…';
  $('#job-time').textContent = time;

  $('#job-label').textContent = job.label || '…';
  const note = noteFor(job, elapsed);
  $('#job-note').hidden = !note;
  if (note) $('#job-note').textContent = note;
  $('#job-steps').innerHTML = (job.steps || []).slice(-8)
    .map((s) => `<div>${escapeHtml(s.label)}</div>`).join('');
}

function renderDock() {
  const dock = $('#job-dock');
  const entries = [...state.jobs.values()]
    .filter((e) => e.id !== state.watching)
    .sort((a, b) => a.started - b.started);
  if (!entries.length) { dock.hidden = true; dock.innerHTML = ''; return; }
  dock.hidden = false;

  dock.innerHTML = entries.map((entry) => {
    const job = entry.snapshot || {};
    const queued = job.status === 'queued';
    const elapsed = (Date.now() - entry.started) / 1000;
    const stalled = (Date.now() - entry.lastMove) / 1000 > 6;
    const waiting = queued || (stalled && entry.lastProgress < 0.995);
    const eta = queued ? null : estimateRemaining(entry);
    const right = queued ? 'en attente'
      : `${Math.round((job.progress || 0) * 100)} %`;
    const time = eta !== null ? `${clock(elapsed)} · ~${clock(eta)} restant`
      : `${clock(elapsed)}`;
    return `<div class="dock-item ${queued ? 'queued' : ''}" data-id="${entry.id}"
                 title="Cliquer pour voir le détail">
      <div class="dock-top">
        <span class="spinner sm"></span>
        <span class="dock-title">${escapeHtml(entry.title)}</span>
        <span class="dock-pct">${escapeHtml(right)}</span>
      </div>
      <div class="dock-bar"><div class="dock-fill ${waiting ? 'waiting' : ''}"
           style="width:${((job.progress || 0) * 100).toFixed(1)}%"></div></div>
      <div class="dock-label">${escapeHtml(job.label || '…')} — ${escapeHtml(time)}</div>
    </div>`;
  }).join('');

  $$('.dock-item', dock).forEach((item) => item.addEventListener('click',
    () => showJobWindow(item.dataset.id)));
}

/* ---------------------------------------------------------------- écrans */
function showHome() {
  $('#view-home').hidden = false;
  $('#view-editor').hidden = true;
  $('#btn-home').hidden = true;
  $('#video').pause();
  state.project = null;
  loadProjects();
}

async function openProject(id) {
  const project = await api(`/api/projects/${id}`);
  state.project = project;
  state.selected = null;
  $('#view-home').hidden = true;
  $('#view-editor').hidden = false;
  $('#btn-home').hidden = false;

  const video = $('#video');
  video.src = `/api/projects/${id}/media`;
  video.load();

  try { state.peaks = (await api(`/api/projects/${id}/waveform`)).peaks || []; } catch { state.peaks = []; }

  fillPackForm();
  renderCharacters();
  renderLines();
  drawWave();
  renderTimeline();
  refreshBacking();
  validate();
  const running = project._job;
  if (running && ['running', 'queued'].includes(running.status)
      && !state.jobs.has(running.id)) {
    trackJob(running, running.title || 'Traitement en cours', () => openProject(id));
  }
}

/* --------------------------------------------------------------- édition */
const lines = () => state.project?.lines || [];
const chars = () => state.project?.characters || [];

function charOf(id) { return chars().find((c) => c.id === id); }
function colorOf(id) { return charOf(id)?.color || '#f97316'; }
function nameOf(id) { return charOf(id)?.name || id || 'Personnage'; }

function sortLines() {
  lines().sort((a, b) => a.start - b.start);
}

function scheduleSave() {
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(save, 700);
}

async function save() {
  if (!state.project) return;
  const p = state.project;
  try {
    await api(`/api/projects/${p.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: p.name, pack: p.pack, characters: p.characters,
        lines: p.lines, options: p.options,
      }),
    });
  } catch (err) {
    toast(`Sauvegarde impossible : ${err.message}`, 'err');
  }
}

function fillPackForm() {
  const p = state.project;
  const pack = p.pack || {};
  $('#pack-title').value = pack.title || p.name || '';
  $('#pack-subtitle').value = pack.subtitle || '';
  $('#pack-authors').value = (pack.authors || []).join(', ');
  $('#pack-description').value = pack.description || '';
  const o = p.options || {};
  $('#opt-normalize').checked = o.normalize_clips !== false;
  $('#opt-timestamp').checked = !!o.include_timestamp_in_name;
  $('#opt-dubonly').checked = !!o.dub_only;
  $('#opt-height').value = String(o.video_height || 720);
  $('#opt-vq').value = String(o.video_quality || 7);
  const asr = p.asr || {};
  $('#stats').textContent = asr.engine
    ? `${asr.engine} · ${asr.model} · ${asr.language || '?'} · voix : ${asr.diarization || '—'}`
    : '';
  if (asr.model) $('#re-model').value = asr.model;
}

function readPackForm() {
  const p = state.project;
  p.pack = {
    title: $('#pack-title').value.trim(),
    subtitle: $('#pack-subtitle').value.trim(),
    authors: $('#pack-authors').value.split(',').map((s) => s.trim()).filter(Boolean),
    description: $('#pack-description').value.trim(),
  };
  p.name = p.pack.title || p.name;
  p.options = {
    ...(p.options || {}),
    normalize_clips: $('#opt-normalize').checked,
    include_timestamp_in_name: $('#opt-timestamp').checked,
    dub_only: $('#opt-dubonly').checked,
    video_height: num($('#opt-height').value, 720),
    video_quality: num($('#opt-vq').value, 7),
  };
  scheduleSave();
}

/* ---------------------------------------------------------- personnages */
function renderCharacters() {
  const box = $('#characters');
  box.innerHTML = '';
  const counts = {};
  for (const l of lines()) counts[l.speaker] = (counts[l.speaker] || 0) + 1;

  for (const c of chars()) {
    const row = document.createElement('div');
    row.className = 'char-row';
    const stamp = Date.now();
    row.innerHTML = `<span class="char-swatch" style="background:${c.color}"></span>
      ${c.image
        ? `<img class="char-portrait" src="/api/projects/${state.project.id}/character-image/${encodeURIComponent(c.id)}?t=${stamp}" alt="">`
        : ''}
      <input type="text" value="${escapeHtml(c.name)}" placeholder="Nom du personnage">
      <button class="line-btn char-shot" title="Utiliser l'image actuelle de la vidéo comme portrait">📷</button>
      ${c.image ? '<button class="line-btn char-shot-del" title="Retirer le portrait">✕</button>' : ''}
      <span class="char-count">${counts[c.id] || 0} rép.</span>`;
    const input = $('input', row);
    input.addEventListener('input', () => {
      c.name = input.value;
      renderLines(); renderTimeline(); scheduleSave();
    });
    $('.char-shot', row).addEventListener('click', async () => {
      try {
        await api(`/api/projects/${state.project.id}/character-image`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ speaker_id: c.id, at: $('#video').currentTime }),
        });
        state.project = await api(`/api/projects/${state.project.id}`);
        renderCharacters();
        toast(`Portrait de ${c.name} enregistré.`, 'ok');
      } catch (err) { toast(err.message, 'err'); }
    });
    $('.char-shot-del', row)?.addEventListener('click', async () => {
      await api(`/api/projects/${state.project.id}/character-image/${encodeURIComponent(c.id)}`, { method: 'DELETE' });
      c.image = null;
      renderCharacters();
    });
    box.append(row);
  }
  if (!chars().length) box.innerHTML = '<p class="muted small">Aucun personnage détecté.</p>';

  const sugg = state.project.suggestions || [];
  $('#suggestions-box').hidden = sugg.length === 0;
  $('#suggestions').innerHTML = sugg
    .map((s) => `<button class="chip" data-name="${escapeHtml(s.name)}">${escapeHtml(s.name)} <span class="muted">×${s.count}</span></button>`)
    .join('');
  $$('#suggestions .chip').forEach((chip) => chip.addEventListener('click', () => {
    const target = chars().find((c) => c.name === c.id) || chars()[0];
    if (!target) return;
    target.name = chip.dataset.name;
    renderCharacters(); renderLines(); renderTimeline(); scheduleSave();
  }));
}

/* --------------------------------------------------------------- lignes */
function renderLines() {
  const box = $('#lines');
  const tpl = $('#tpl-line');
  box.innerHTML = '';
  sortLines();
  const filter = state.filter.toLowerCase();
  const all = lines();
  $('#line-count').textContent = all.length;

  all.forEach((line, index) => {
    if (filter && !(line.text || '').toLowerCase().includes(filter)
        && !nameOf(line.speaker).toLowerCase().includes(filter)) return;

    const node = tpl.content.cloneNode(true).firstElementChild;
    node.dataset.id = line.id;
    $('.line-bar', node).style.background = colorOf(line.speaker);
    $('.line-index', node).textContent = index + 1;

    const sel = $('.line-speaker', node);
    sel.innerHTML = chars().map((c) =>
      `<option value="${escapeHtml(c.id)}"${c.id === line.speaker ? ' selected' : ''}>${escapeHtml(c.name)}</option>`).join('');
    sel.addEventListener('change', () => {
      line.speaker = sel.value;
      $('.line-bar', node).style.background = colorOf(line.speaker);
      renderCharacters(); renderTimeline(); scheduleSave();
    });

    const startEl = $('.line-start', node);
    const endEl = $('.line-end', node);
    startEl.value = line.start.toFixed(2);
    endEl.value = line.end.toFixed(2);
    const commitTimes = () => {
      const s = Math.max(0, num(startEl.value, line.start));
      const e = Math.max(s + 0.05, num(endEl.value, line.end));
      line.start = Math.round(s * 1000) / 1000;
      line.end = Math.round(e * 1000) / 1000;
      startEl.value = line.start.toFixed(2);
      endEl.value = line.end.toFixed(2);
      updateDuration(node, line);
      renderTimeline(); validate(); scheduleSave();
    };
    startEl.addEventListener('change', commitTimes);
    endEl.addEventListener('change', commitTimes);
    updateDuration(node, line);

    const text = $('.line-text', node);
    text.value = line.text || '';
    text.addEventListener('input', () => { line.text = text.value; scheduleSave(); });
    text.addEventListener('focus', () => selectLine(line.id, false));

    const chk = $('.line-enabled input', node);
    chk.checked = line.enabled !== false;
    chk.addEventListener('change', () => {
      line.enabled = chk.checked;
      node.classList.toggle('off', !chk.checked);
      renderTimeline(); validate(); scheduleSave();
    });
    node.classList.toggle('off', line.enabled === false);

    $('.line-play', node).addEventListener('click', () => playLine(line));
    $('.line-split', node).addEventListener('click', () => splitLine(line));
    $('.line-merge', node).addEventListener('click', () => mergeLine(line));
    $('.line-del', node).addEventListener('click', () => {
      state.project.lines = all.filter((l) => l.id !== line.id);
      renderLines(); renderTimeline(); renderCharacters(); validate(); scheduleSave();
    });
    node.addEventListener('click', (e) => {
      if (!e.target.closest('button, input, select, textarea')) selectLine(line.id, true);
    });
    if (line.id === state.selected) node.classList.add('sel');
    box.append(node);
  });
}

function updateDuration(node, line) {
  const d = line.end - line.start;
  const el = $('.line-dur', node);
  el.textContent = `${d.toFixed(2)}s`;
  el.className = `line-dur${d > 60 ? ' bad' : d > 12 ? ' long' : ''}`;
}

function selectLine(id, seek) {
  state.selected = id;
  $$('#lines .line').forEach((n) => n.classList.toggle('sel', n.dataset.id === id));
  $$('#tl-lines .tl-line').forEach((n) => n.classList.toggle('sel', n.dataset.id === id));
  const line = lines().find((l) => l.id === id);
  if (line && seek) $('#video').currentTime = line.start;
}

function splitLine(line) {
  const at = $('#video').currentTime;
  if (at <= line.start + 0.1 || at >= line.end - 0.1) {
    toast('Place le curseur de lecture à l\'intérieur de la réplique pour la couper.');
    return;
  }
  const words = (line.text || '').split(/\s+/);
  const ratio = (at - line.start) / (line.end - line.start);
  const cut = Math.max(1, Math.round(words.length * ratio));
  const second = {
    ...line,
    id: Math.random().toString(36).slice(2, 12),
    start: Math.round(at * 1000) / 1000,
    text: words.slice(cut).join(' '),
  };
  line.end = Math.round(at * 1000) / 1000;
  line.text = words.slice(0, cut).join(' ');
  state.project.lines.push(second);
  renderLines(); renderTimeline(); validate(); scheduleSave();
}

function mergeLine(line) {
  sortLines();
  const all = lines();
  const idx = all.findIndex((l) => l.id === line.id);
  const next = all[idx + 1];
  if (!next) { toast('Pas de réplique suivante à fusionner.'); return; }
  line.end = next.end;
  line.text = `${line.text || ''} ${next.text || ''}`.trim();
  state.project.lines = all.filter((l) => l.id !== next.id);
  renderLines(); renderTimeline(); renderCharacters(); validate(); scheduleSave();
}

function addLine() {
  const at = $('#video').currentTime;
  const dur = state.project.source?.duration || 0;
  const line = {
    id: Math.random().toString(36).slice(2, 12),
    start: Math.round(at * 1000) / 1000,
    end: Math.round(Math.min(at + 2, dur || at + 2) * 1000) / 1000,
    text: '', speaker: chars()[0]?.id || null, enabled: true, tags: [], dub_only: false,
  };
  if (!chars().length) {
    state.project.characters = [{ id: 'Personnage 1', name: 'Personnage 1', color: '#f97316', image: null }];
    line.speaker = 'Personnage 1';
  }
  state.project.lines.push(line);
  renderCharacters(); renderLines(); renderTimeline(); scheduleSave();
  selectLine(line.id, false);
}

function playLine(line) {
  const audio = state.previewAudio;
  audio.pause();
  audio.src = `/api/projects/${state.project.id}/preview?start=${line.start}&end=${line.end}`;
  audio.play().catch(() => toast('Lecture impossible pour cet extrait.'));
  selectLine(line.id, false);
}

/* ------------------------------------------------------------- timeline */
function drawWave() {
  const canvas = $('#wave');
  const box = $('#timeline');
  const dpr = window.devicePixelRatio || 1;
  const w = box.clientWidth;
  const h = box.clientHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  const peaks = state.peaks;
  if (!peaks.length) {
    ctx.fillStyle = '#8b98ad';
    ctx.font = '12px sans-serif';
    ctx.fillText('Forme d\'onde indisponible', 12, h / 2);
    return;
  }
  const mid = h * 0.28;
  ctx.fillStyle = 'rgba(148,163,184,.55)';
  for (let x = 0; x < w; x++) {
    const p = peaks[Math.floor((x / w) * peaks.length)] || 0;
    const amp = Math.max(1, p * mid * 0.95);
    ctx.fillRect(x, mid - amp, 1, amp * 2);
  }
}

function renderTimeline() {
  const box = $('#tl-lines');
  const dur = state.project?.source?.duration || 0;
  box.innerHTML = '';
  if (!dur) return;
  for (const line of lines()) {
    const el = document.createElement('div');
    el.className = `tl-line${line.enabled === false ? ' off' : ''}${line.id === state.selected ? ' sel' : ''}`;
    el.dataset.id = line.id;
    el.style.left = `${(line.start / dur) * 100}%`;
    el.style.width = `${Math.max(((line.end - line.start) / dur) * 100, 0.35)}%`;
    el.style.background = colorOf(line.speaker);
    el.title = `${nameOf(line.speaker)} — ${line.text || ''}`;
    el.textContent = nameOf(line.speaker);
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      selectLine(line.id, true);
      const node = $(`#lines .line[data-id="${line.id}"]`);
      node?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
    box.append(el);
  }
}

function setupTimeline() {
  const box = $('#timeline');
  box.addEventListener('click', (e) => {
    if (e.target.closest('.tl-line')) return;
    const dur = state.project?.source?.duration || 0;
    const rect = box.getBoundingClientRect();
    $('#video').currentTime = ((e.clientX - rect.left) / rect.width) * dur;
  });
  window.addEventListener('resize', () => { drawWave(); });
}

/* --------------------------------------------------------------- lecture */
function setupPlayer() {
  const video = $('#video');
  $('#btn-play').addEventListener('click', () => (video.paused ? video.play() : video.pause()));
  $('#btn-prev').addEventListener('click', () => jumpLine(-1));
  $('#btn-next').addEventListener('click', () => jumpLine(1));
  video.addEventListener('play', () => { $('#btn-play').textContent = '❚❚'; });
  video.addEventListener('pause', () => { $('#btn-play').textContent = '▶︎'; });

  video.addEventListener('timeupdate', () => {
    const dur = state.project?.source?.duration || video.duration || 0;
    $('#playhead').style.left = `${(video.currentTime / dur) * 100}%`;
    $('#timecode').textContent = `${fmt(video.currentTime)} / ${fmt(dur)}`;

    const current = lines().find((l) => video.currentTime >= l.start && video.currentTime < l.end);
    const overlay = $('#subtitle-overlay');
    if (current) {
      overlay.innerHTML = `<span class="who" style="color:${colorOf(current.speaker)}">${escapeHtml(nameOf(current.speaker))}</span>${escapeHtml(current.text || '')}`;
    } else {
      overlay.innerHTML = '';
    }
    if ($('#chk-loop').checked && state.selected) {
      const line = lines().find((l) => l.id === state.selected);
      if (line && (video.currentTime >= line.end || video.currentTime < line.start - 0.05)) {
        video.currentTime = line.start;
      }
    }
  });

  document.addEventListener('keydown', (e) => {
    if (state.project === null || $('#view-editor').hidden) return;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
    if (e.code === 'Space' && !typing) { e.preventDefault(); video.paused ? video.play() : video.pause(); }
    if (typing) return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); video.currentTime = Math.max(0, video.currentTime - (e.shiftKey ? 5 : 1)); }
    if (e.key === 'ArrowRight') { e.preventDefault(); video.currentTime += e.shiftKey ? 5 : 1; }
    if (e.key === 'j') jumpLine(-1);
    if (e.key === 'k') jumpLine(1);
  });
}

function jumpLine(delta) {
  sortLines();
  const all = lines();
  if (!all.length) return;
  const video = $('#video');
  let idx = all.findIndex((l) => l.id === state.selected);
  if (idx === -1) idx = all.findIndex((l) => l.end > video.currentTime);
  idx = Math.max(0, Math.min(all.length - 1, (idx === -1 ? 0 : idx) + delta));
  const line = all[idx];
  selectLine(line.id, true);
  $(`#lines .line[data-id="${line.id}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

/* ---------------------------------------------------------------- export */
async function validate() {
  if (!state.project) return;
  try {
    const { issues } = await api(`/api/projects/${state.project.id}/validate`);
    const box = $('#issues');
    if (!issues.length) {
      box.innerHTML = '<div class="issue ok">Tout est prêt pour l\'export.</div>';
    } else {
      box.innerHTML = issues.map((i) =>
        `<div class="issue ${i.level}">${escapeHtml(i.message)}</div>`).join('');
    }
    $('#btn-export').disabled = issues.some((i) => i.level === 'error');
  } catch { /* la validation est indicative */ }
}

function refreshBacking() {
  const assets = state.project.assets || {};
  const box = $('#backing-state');
  if (assets.backing_track) {
    const mode = assets.backing_mode === 'demucs' ? 'voix séparées (Demucs)' : 'audio d\'origine';
    box.className = 'backing-state on';
    box.innerHTML = `✓ <code>_backing_track.ogg</code> prêt — ${mode}. <button class="link" id="btn-drop-backing">retirer</button>`;
    $('#btn-drop-backing').addEventListener('click', async () => {
      await api(`/api/projects/${state.project.id}/backing`, { method: 'DELETE' });
      state.project.assets.backing_track = null;
      delete state.project.assets.backing_track;
      refreshBacking();
    });
  } else {
    box.className = 'backing-state';
    box.textContent = 'Aucun fond sonore : le pack utilisera uniquement ta voix.';
  }
  $('#btn-demucs').disabled = !state.caps?.demucs;
  $('#btn-demucs').title = state.caps?.demucs ? '' : 'Demucs n\'est pas installé (pip install demucs)';
}

function setupExport() {
  $('#btn-demucs').addEventListener('click', () => runBacking('demucs'));
  $('#btn-backing-orig').addEventListener('click', () => runBacking('original'));

  $('#btn-export').addEventListener('click', async () => {
    readPackForm();
    await save();
    const destination = currentDestination();
    const body = {
      reuse_video: true,
      destination,
      overwrite: $('#opt-overwrite').checked,
      make_zip: $('#opt-makezip').checked,
    };
    if (destination === 'game') body.target_path = $('#game-path').value.trim();
    if (destination === 'folder') body.target_path = $('#folder-path').value.trim();

    if (destination === 'game' && !body.target_path) {
      toast('Indique d\'abord le dossier du jeu (Détecter ou Choisir).', 'err');
      return;
    }
    if (destination === 'folder' && !body.target_path) {
      toast('Choisis le dossier de destination.', 'err');
      return;
    }
    if (destination === 'game' && !confirm(
      `Le pack va être écrit dans les fichiers du jeu :\n\n${body.target_path}\n\nContinuer ?`)) return;

    saveSettings({
      export_destination: destination,
      export_folder: destination === 'folder' ? body.target_path : state.settings.export_folder,
      game_dir: destination === 'game' ? body.target_path : state.settings.game_dir,
    });
    try {
      const res = await api(`/api/projects/${state.project.id}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      // On fige le projet concerne: l'utilisateur peut avoir navigue ailleurs
      // avant la fin de l'export.
      const projectId = state.project.id;
      openJob(res.job, res.job.title || 'Export du dub pack',
        (result) => showExportResult(result, projectId));
    } catch (err) {
      toast(err.message, 'err');
    }
  });

  $('#btn-reanalyze').addEventListener('click', async () => {
    if (!confirm('Retranscrire ? Les répliques actuelles seront remplacées.')) return;
    try {
      const res = await api(`/api/projects/${state.project.id}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: $('#re-model').value,
          speakers: $('#re-speakers').value,
          language: $('#set-language').value,
          max_line: state.project.asr?.max_line || 9,
          keep_names: true,
        }),
      });
      const projectId = state.project.id;
      openJob(res.job, res.job.title || 'Nouvelle transcription', () => {
        if (state.project?.id === projectId) openProject(projectId);
        else toast('Nouvelle transcription terminée.', 'ok');
      });
    } catch (err) {
      toast(err.message, 'err');
    }
  });

  ['#pack-title', '#pack-subtitle', '#pack-authors', '#pack-description',
   '#opt-normalize', '#opt-timestamp', '#opt-dubonly', '#opt-height', '#opt-vq']
    .forEach((sel) => $(sel).addEventListener('change', readPackForm));
  $('#pack-title').addEventListener('input', readPackForm);

  $$('.tab').forEach((tab) => tab.addEventListener('click', () => {
    $$('.tab').forEach((t) => t.classList.toggle('active', t === tab));
    $$('.tab-body').forEach((b) => { b.hidden = b.dataset.body !== tab.dataset.tab; });
  }));

  $('#line-filter').addEventListener('input', (e) => {
    state.filter = e.target.value;
    renderLines();
  });
  $('#btn-add-line').addEventListener('click', addLine);
}

async function runBacking(mode) {
  try {
    const res = await api(`/api/projects/${state.project.id}/backing`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
    const projectId = state.project.id;
    openJob(res.job, mode === 'demucs' ? 'Séparation des voix' : 'Préparation du fond sonore',
      async () => {
        if (state.project?.id !== projectId) {
          toast('Fond sonore prêt.', 'ok');
          return;
        }
        state.project = await api(`/api/projects/${projectId}`);
        refreshBacking();
        toast('Fond sonore prêt.', 'ok');
      });
  } catch (err) {
    toast(err.message, 'err');
  }
}

function showExportResult(result, projectId) {
  projectId = projectId || state.project?.id;
  if (state.project?.id !== projectId) {
    // L'utilisateur regarde un autre projet: on se contente de le prevenir.
    toast(result.destination === 'game'
      ? `Pack installé dans le jeu : ${result.pack_name}`
      : `Pack exporté : ${result.pack_name}`, 'ok');
    return;
  }
  const box = $('#export-result');
  box.hidden = false;
  const installed = result.destination === 'game';
  const zipLink = result.zip
    ? `<a class="btn btn-primary" href="/api/projects/${state.project.id}/download">Télécharger le ZIP</a>`
    : '';
  const steps = installed
    ? `<ol>
        <li>Le pack est déjà en place dans <code>packs_voice</code>.</li>
        <li>Lance Choicer Voicer (ou reviens au menu principal).</li>
        <li>Sélectionne le pack en mode Dub.</li>
       </ol>`
    : `<ol>
        <li>${result.zip ? 'Décompresse le ZIP (ou prends le dossier directement).' : 'Ouvre le dossier exporté.'}</li>
        <li>Copie le dossier <code>${escapeHtml(result.pack_name)}</code> dans <code>packs_voice</code> du jeu.</li>
        <li>Vérifie que <code>packs_voice/${escapeHtml(result.pack_name)}/dub_video.ogv</code> existe (pas de dossier en trop).</li>
        <li>Lance Choicer Voicer et sélectionne le pack en mode Dub.</li>
       </ol>`;
  box.innerHTML = `<h3>${installed ? 'Pack installé dans le jeu' : 'Pack exporté'}</h3>
    <p>${result.clips} clips · ${result.characters.length} personnage(s) · ${result.files} fichiers</p>
    <p class="path">${escapeHtml(result.folder)}</p>
    <div class="btn-row">
      ${zipLink}
      <button class="btn btn-ghost" id="btn-reveal">Ouvrir le dossier</button>
    </div>
    ${steps}`;
  $('#btn-reveal').addEventListener('click', () =>
    api(`/api/projects/${projectId}/reveal`, { method: 'POST' }).catch((e) => toast(e.message, 'err')));
  toast(installed ? 'Pack installé dans le jeu.' : 'Export terminé.', 'ok');
}

/* ----------------------------------------------------------- diagnostic */
const flag = (value, okText, noText, warn = false) => value
  ? `<span class="diag-val ok">${escapeHtml(okText)}</span>`
  : `<span class="diag-val ${warn ? 'warn' : 'no'}">${escapeHtml(noText)}</span>`;

function diagRow(key, valueHtml) {
  return `<div class="diag-row"><span class="diag-key">${escapeHtml(key)}</span>${valueHtml}</div>`;
}

async function openDiagnostics() {
  $('#diag-overlay').hidden = false;
  $('#diag-body').innerHTML = '<p class="muted">Analyse…</p>';
  let d;
  try {
    d = await api('/api/diagnostics');
  } catch (err) {
    $('#diag-body').innerHTML = `<p class="diag-val no">${escapeHtml(err.message)}</p>`;
    return;
  }
  state.diag = d;

  const fixes = [];
  if (!d.ffmpeg_used || !d.encoders.libtheora) {
    const missing = !d.ffmpeg_used ? 'ffmpeg est introuvable' : "ffmpeg n'a pas l'encodeur Theora";
    fixes.push(`<div class="diag-fix">
      <h3>${missing}</h3>
      <p>Sans lui, impossible de produire <code>dub_video.ogv</code>, le fichier vidéo
         que le jeu exige. ${d.can_download_ffmpeg
           ? 'Le bouton ci-dessous télécharge la bonne version (environ 110 Mo) et la place dans <code>bin\\</code>.'
           : 'Sur macOS : <code>brew install ffmpeg</code> puis relance l\'outil.'}</p>
      ${d.can_download_ffmpeg
        ? '<button class="btn btn-primary" id="btn-fix-ffmpeg">Installer ffmpeg automatiquement</button>'
        : ''}
    </div>`);
  }
  if (!d.demucs) {
    fixes.push(`<div class="diag-fix">
      <h3>Demucs n'est pas installé (facultatif)</h3>
      <p>Demucs sépare les voix de la musique pour produire un
         <code>_backing_track.ogg</code> : ta voix se pose alors sur la bande-son
         d'origine, sans les dialogues. Sans lui, tout le reste fonctionne —
         tu peux aussi utiliser l'audio d'origine tel quel.
         Téléchargement d'environ 2 Go (PyTorch).</p>
      <button class="btn btn-ghost" id="btn-fix-demucs">Installer Demucs</button>
    </div>`);
  }
  if (!d.asr_engines.length) {
    fixes.push(`<div class="diag-fix">
      <h3>Aucun moteur de transcription</h3>
      <p>Relance <code>INSTALLER.bat</code> : l'installation des dépendances a échoué.</p>
    </div>`);
  }
  if (!fixes.length) {
    fixes.push('<div class="diag-fix"><h3>Tout est en ordre</h3>'
      + '<p>ffmpeg, Theora et la transcription répondent. Rien à réparer.</p></div>');
  }

  const rows = [
    diagRow('ffmpeg utilisé', flag(d.ffmpeg_used, d.ffmpeg_used || '', d.ffmpeg_error || 'introuvable')),
    diagRow('encodeur Theora', flag(d.encoders.libtheora, 'présent', 'ABSENT - export vidéo impossible')),
    diagRow('encodeur Vorbis', flag(d.encoders.libvorbis, 'présent', 'absent')),
    diagRow('ffprobe', flag(d.tools.ffprobe.resolved, d.tools.ffprobe.resolved || '', 'absent (optionnel)', true)),
    diagRow('dossier bin', `<span class="diag-val">${escapeHtml(d.bin_dir)}</span>`),
    diagRow('contenu de bin', d.bin_contents.length
      ? `<span class="diag-val">${escapeHtml(d.bin_contents.join(', '))}</span>`
      : '<span class="diag-val warn">vide</span>'),
    diagRow('ffmpeg attendu dans bin', flag(d.tools.ffmpeg.found_in_bin,
      d.tools.ffmpeg.expected_in_bin, `absent : ${d.tools.ffmpeg.expected_in_bin}`, true)),
    diagRow('ffmpeg dans le PATH', flag(d.tools.ffmpeg.found_on_path,
      d.tools.ffmpeg.found_on_path || '', 'non', true)),
    diagRow('repli imageio-ffmpeg', flag(d.imageio_ffmpeg.binary,
      d.imageio_ffmpeg.binary || '', d.imageio_ffmpeg.error || 'indisponible', true)),
    diagRow('transcription', flag(d.asr_engines.length, d.asr_engines.join(', '), 'ABSENTE')),
    diagRow('liens vidéo (yt-dlp)', flag(d.yt_dlp, 'prêt', 'absent')),
    diagRow('Demucs (fond sonore)', flag(d.demucs, 'installé', 'non installé (facultatif)', true)),
    diagRow('empreintes ECAPA', flag(d.embeddings, 'installées', 'non installées (facultatif)', true)),
    diagRow('sélecteur de dossier', flag(d.picker, 'disponible', 'indisponible - colle les chemins', true)),
    diagRow('Python', `<span class="diag-val">${escapeHtml(d.python)} — ${escapeHtml(d.python_exe)}</span>`),
    diagRow('dossier de l\'outil', `<span class="diag-val">${escapeHtml(d.root)}</span>`),
  ].join('');

  $('#diag-body').innerHTML = fixes.join('') + rows;

  $('#btn-fix-ffmpeg')?.addEventListener('click', () => runSetup('/api/setup/ffmpeg', {},
    'Installation de ffmpeg'));
  $('#btn-fix-demucs')?.addEventListener('click', () => runSetup('/api/setup/extras',
    { which: 'demucs' }, 'Installation de Demucs'));
}

async function runSetup(path, body, title) {
  try {
    const res = await api(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    $('#diag-overlay').hidden = true;
    openJob(res.job, title, async (result) => {
      await loadCaps();
      if (result?.restart_needed) {
        toast('Installé. Ferme la fenêtre noire et relance DEMARRER.bat pour l\'activer.', 'ok');
      } else {
        toast('Installé.', 'ok');
      }
      openDiagnostics();
    });
  } catch (err) {
    toast(err.message, 'err');
  }
}

function setupDiagnostics() {
  $('#btn-diag').addEventListener('click', openDiagnostics);
  $('#caps').addEventListener('click', openDiagnostics);
  $('#btn-diag-close').addEventListener('click', () => { $('#diag-overlay').hidden = true; });
  $('#diag-overlay').addEventListener('click', (e) => {
    if (e.target.id === 'diag-overlay') $('#diag-overlay').hidden = true;
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') $('#diag-overlay').hidden = true;
  });
}

/* ---------------------------------------------------------- destination */
function currentDestination() {
  return $$('input[name="dest"]').find((r) => r.checked)?.value || 'zip';
}

function refreshDestination() {
  const dest = currentDestination();
  $$('.dest-body').forEach((b) => { b.hidden = b.dataset.dest !== dest; });
  $('#zip-too-row').hidden = dest !== 'game';
  $('#btn-export').textContent = dest === 'game'
    ? 'Exporter et installer dans le jeu'
    : dest === 'folder' ? 'Exporter dans ce dossier' : 'Exporter le dub pack';
}

async function saveSettings(patch) {
  state.settings = { ...state.settings, ...patch };
  try {
    await api('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
  } catch { /* réglage non bloquant */ }
}

async function loadSettings() {
  try {
    state.settings = await api('/api/settings');
  } catch {
    state.settings = {};
  }
  const s = state.settings;
  if (s.game_dir) {
    $('#game-path').value = s.game_dir;
    setGameState(`✓ Jeu sélectionné : ${s.game_dir}`, true);
  }
  if (s.export_folder) $('#folder-path').value = s.export_folder;
  const dest = s.export_destination || (s.game_dir ? 'game' : 'zip');
  const radio = $$('input[name="dest"]').find((r) => r.value === dest);
  if (radio) radio.checked = true;
  if (s.make_zip) $('#opt-makezip').checked = true;
  refreshDestination();
}

function setGameState(message, ok) {
  const box = $('#game-state');
  box.className = `backing-state${ok ? ' on' : ''}`;
  box.textContent = message;
}

function renderCandidates(list) {
  const box = $('#game-candidates');
  state.gameCandidates = list;
  if (!list.length) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.innerHTML = list.map((c, i) => `<button class="candidate" data-i="${i}">
      <strong>${escapeHtml(c.path.split(/[\\/]/).filter(Boolean).pop() || c.path)}</strong>
      <span class="cpath">${escapeHtml(c.path)}</span>
      <span class="creasons">${escapeHtml(c.reasons.join(' · '))}${c.packs_voice ? '' : ' · packs_voice sera créé'}</span>
    </button>`).join('');
  $$('.candidate', box).forEach((btn) => btn.addEventListener('click', () => {
    const c = list[Number(btn.dataset.i)];
    $$('.candidate', box).forEach((b) => b.classList.toggle('sel', b === btn));
    selectGameDir(c.path);
  }));
}

async function selectGameDir(path) {
  try {
    const res = await api('/api/game/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    $('#game-path').value = res.game_dir;
    state.settings.game_dir = res.game_dir;
    setGameState(res.looks_like_game
      ? `✓ Jeu reconnu : ${res.game_dir}`
      : `⚠ Dossier accepté, mais il ne ressemble pas à une installation du jeu : ${res.game_dir}`,
      res.looks_like_game);
  } catch (err) {
    setGameState(err.message, false);
    toast(err.message, 'err');
  }
}

function setupDestination() {
  $$('input[name="dest"]').forEach((r) => r.addEventListener('change', () => {
    refreshDestination();
    saveSettings({ export_destination: currentDestination() });
  }));

  $('#btn-detect-game').addEventListener('click', async () => {
    const btn = $('#btn-detect-game');
    btn.disabled = true;
    setGameState('Recherche du jeu sur cette machine…', false);
    try {
      const res = await api('/api/game/detect');
      renderCandidates(res.candidates);
      if (!res.candidates.length) {
        setGameState("Jeu introuvable automatiquement. Utilise « Choisir le dossier… » — "
          + 'astuce : dans le jeu, Modpack Guides → Dub Mode Packs → Open Folder.', false);
      } else {
        setGameState(`${res.candidates.length} installation(s) trouvée(s) — choisis la bonne.`, true);
        if (res.candidates.length === 1) {
          $$('.candidate')[0]?.classList.add('sel');
          selectGameDir(res.candidates[0].path);
        }
      }
    } catch (err) {
      setGameState(err.message, false);
    } finally {
      btn.disabled = false;
    }
  });

  const pick = async (title, initial) => {
    const res = await api('/api/pick-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, initial }),
    });
    return res.path;
  };

  $('#btn-pick-game').addEventListener('click', async () => {
    try {
      const path = await pick('Dossier du jeu Choicer Voicer', $('#game-path').value);
      if (path) { $('#game-path').value = path; await selectGameDir(path); }
    } catch (err) { toast(err.message, 'err'); }
  });

  $('#btn-pick-folder').addEventListener('click', async () => {
    try {
      const path = await pick('Dossier de destination du pack', $('#folder-path').value);
      if (path) {
        $('#folder-path').value = path;
        saveSettings({ export_folder: path });
      }
    } catch (err) { toast(err.message, 'err'); }
  });

  $('#game-path').addEventListener('change', () => {
    const value = $('#game-path').value.trim();
    if (value) selectGameDir(value);
  });
  $('#folder-path').addEventListener('change', () =>
    saveSettings({ export_folder: $('#folder-path').value.trim() }));
  $('#opt-makezip').addEventListener('change', () =>
    saveSettings({ make_zip: $('#opt-makezip').checked }));
}

/* --- reprise des taches deja en cours ---------------------------------- */
async function adoptRunningJobs() {
  /* Le serveur garde ses taches en cours meme si la page est rechargee ou
     fermee. Au demarrage on les recupere pour que le suivi reapparaisse. */
  try {
    const { jobs } = await api('/api/jobs');
    for (const job of jobs) {
      if (state.jobs.has(job.id)) continue;
      const onDone = job.project_id && job.kind === 'import'
        ? () => { loadProjects(); toast(`« ${job.title} » est prêt.`, 'ok'); }
        : job.project_id && !job.project_id.startsWith('_')
          ? () => { if (state.project?.id === job.project_id) openProject(job.project_id); }
          : null;
      trackJob(job, job.title, onDone);
    }
    if (jobs.length) {
      toast(`${jobs.length} tâche(s) déjà en cours, suivi repris.`);
    }
  } catch { /* pas bloquant */ }
}

/* ------------------------------------------------------------------ init */
(async function init() {
  setupHome();
  setupPlayer();
  setupTimeline();
  setupExport();
  setupDestination();
  setupDiagnostics();
  await loadSettings();
  try {
    await loadCaps();
  } catch (err) {
    toast(`Serveur injoignable : ${err.message}`, 'err');
  }
  await loadProjects();
  await adoptRunningJobs();
  window.addEventListener('beforeunload', () => { if (state.saveTimer) save(); });
})();
