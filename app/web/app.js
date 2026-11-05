// Allô Paris web companion. All times come from /api (PRIM). No innerHTML with data.
"use strict";

const I18N = {
  fr: {
    tagline: "Prochains départs en temps réel, par téléphone ou ici.",
    ask: "Posez votre question", placeholder: "prochain RER A à Châtelet", send: "OK",
    speak: "Lire la réponse", station: "Station", pick: "Cliquez une station sur la carte.",
    map: "Carte", realtime: "temps réel", scheduled: "théorique", now: "à l'approche",
    min: "min", none: "Aucun départ annoncé pour le moment.",
    feedDown: "Données temps réel indisponibles. Aucun horaire affiché.",
    stale: "Données trop anciennes. Aucun horaire affiché.",
    updated: (s) => `Mis à jour il y a ${s} s · actualisation auto`,
    feedOk: (n, b) => `Données IDFM OK · ${n}/${b} requêtes aujourd'hui`,
    feedErr: (e) => `Problème de données : ${e}`, feedUnknown: "Données IDFM : pas encore interrogées",
    tooMany: "Trop de requêtes, réessayez dans une minute.", error: "Erreur réseau.",
    examples: ["prochain RER A à Châtelet", "ligne 4 Gare du Nord", "perturbations RER B", "tram T2 La Défense"],
    modes: { Metro: "Métro", RapidTransit: "RER", Tramway: "Tram", LocalTrain: "Train" },
    micUnsupported: "Micro non disponible dans ce navigateur.", listening: "J'écoute…",
  },
  en: {
    tagline: "Live next departures, by phone or right here.",
    ask: "Ask a question", placeholder: "next RER A at Châtelet", send: "Go",
    speak: "Read answer aloud", station: "Station", pick: "Click a station on the map.",
    map: "Map", realtime: "real-time", scheduled: "scheduled", now: "arriving",
    min: "min", none: "No departures announced right now.",
    feedDown: "Real-time data unavailable. No times shown.",
    stale: "Data too old. No times shown.",
    updated: (s) => `Updated ${s} s ago · auto-refresh`,
    feedOk: (n, b) => `IDFM data OK · ${n}/${b} requests today`,
    feedErr: (e) => `Data problem: ${e}`, feedUnknown: "IDFM data: not queried yet",
    tooMany: "Too many requests, try again in a minute.", error: "Network error.",
    examples: ["next RER A at Châtelet", "line 4 Gare du Nord", "disruptions RER B", "tram T2 La Défense"],
    modes: { Metro: "Metro", RapidTransit: "RER", Tramway: "Tram", LocalTrain: "Train" },
    micUnsupported: "Microphone not available in this browser.", listening: "Listening…",
  },
};

const $ = (id) => document.getElementById(id);
const state = {
  lang: "fr", stops: [], markers: new Map(), current: null, timer: null,
  modes: new Set(["Metro", "RapidTransit", "Tramway", "LocalTrain"]),
  session: (() => {
    try {
      let s = localStorage.getItem("allo.session");
      if (!s) { s = crypto.randomUUID(); localStorage.setItem("allo.session", s); }
      return s;
    } catch { return Math.random().toString(36).slice(2); }
  })(),
};
const tr = () => I18N[state.lang];

function el(tag, props = {}, ...children) {
  const n = document.createElement(tag);
  Object.assign(n, props);
  for (const c of children) n.append(c);
  return n;
}

function pill(line) {
  const b = el("span", { className: "pill", textContent: line.short, title: line.label });
  if (/^[0-9a-f]{6}$/i.test(line.color)) b.style.background = "#" + line.color;
  if (/^[0-9a-f]{6}$/i.test(line.text_color)) b.style.color = "#" + line.text_color;
  return b;
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (r.status === 429) throw new Error(tr().tooMany);
  if (!r.ok) throw new Error(tr().error);
  return r.json();
}

// ---------- language ----------
function applyLang() {
  const t = tr();
  document.documentElement.lang = state.lang;
  $("tagline").textContent = t.tagline;
  $("askLabel").textContent = t.ask;
  $("q").placeholder = t.placeholder;
  $("send").textContent = t.send;
  $("speakLabel").textContent = t.speak;
  $("boardLabel").textContent = t.station;
  $("boardEmpty").textContent = t.pick;
  $("mapLabel").textContent = t.map;
  $("langFr").setAttribute("aria-pressed", String(state.lang === "fr"));
  $("langEn").setAttribute("aria-pressed", String(state.lang === "en"));
  const ex = $("examples"); ex.replaceChildren();
  for (const q of t.examples) {
    ex.append(el("button", { type: "button", textContent: q, onclick: () => { $("q").value = q; ask(q); } }));
  }
  renderFilters();
  if (state.current) loadDepartures(state.current.stop, state.current.line);
}
$("langFr").onclick = () => { state.lang = "fr"; applyLang(); };
$("langEn").onclick = () => { state.lang = "en"; applyLang(); };

// ---------- map ----------
const map = L.map("map", { zoomControl: true }).setView([48.8566, 2.3522], 12);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18, attribution: "© OpenStreetMap",
}).addTo(map);

function markerColor(stop) {
  const ln = stop.lines.find((l) => state.modes.has(l.mode) && /^[0-9a-f]{6}$/i.test(l.color));
  return ln ? "#" + ln.color : "#666";
}

function drawMarkers() {
  for (const m of state.markers.values()) m.remove();
  state.markers.clear();
  for (const s of state.stops) {
    if (!s.lines.some((l) => state.modes.has(l.mode))) continue;
    const big = s.lines.length > 2;
    const m = L.circleMarker([s.lat, s.lon], {
      radius: big ? 6 : 4, color: "#fff", weight: 1.5, fillColor: markerColor(s), fillOpacity: 0.95,
    }).addTo(map);
    m.bindTooltip(s.name);
    m.on("click", () => selectStop(s));
    state.markers.set(s.id, m);
  }
}

function renderFilters() {
  const f = $("filters"); f.replaceChildren();
  for (const [mode, label] of Object.entries(tr().modes)) {
    const b = el("button", { type: "button", textContent: label });
    b.setAttribute("aria-pressed", String(state.modes.has(mode)));
    b.onclick = () => {
      state.modes.has(mode) ? state.modes.delete(mode) : state.modes.add(mode);
      renderFilters(); drawMarkers();
    };
    f.append(b);
  }
}

// ---------- station board ----------
function selectStop(stop, lineId) {
  const lines = stop.lines.filter((l) => state.modes.has(l.mode));
  const line = lines.find((l) => l.id === lineId) || lines[0] || stop.lines[0];
  map.flyTo([stop.lat, stop.lon], Math.max(map.getZoom(), 14), { duration: 0.6 });
  loadDepartures(stop, line);
}

async function loadDepartures(stop, line) {
  clearTimeout(state.timer);
  state.current = { stop, line };
  $("boardEmpty").hidden = true;
  $("boardBody").hidden = false;
  $("stopName").textContent = stop.name;
  const pills = $("linePills"); pills.replaceChildren();
  for (const l of stop.lines) {
    const b = el("button", { type: "button", className: "pill", onclick: () => loadDepartures(stop, l) });
    b.append(pill(l));
    b.style.padding = "0"; b.style.background = "transparent"; b.style.border = "0";
    if (l.id === line.id) b.style.outline = "2px solid var(--accent)";
    pills.append(b);
  }
  const deps = $("deps");
  try {
    const d = await api(`/api/departures?stop=${encodeURIComponent(stop.id)}&line=${encodeURIComponent(line.id)}&lang=${state.lang}`);
    renderBoard(d);
  } catch (e) {
    deps.replaceChildren(el("div", { className: "empty", textContent: e.message }));
    $("fresh").textContent = "";
  }
  refreshStatus();
  state.timer = setTimeout(() => {
    if (state.current && state.current.stop.id === stop.id) loadDepartures(stop, state.current.line);
  }, 30000);
}

function renderBoard(d) {
  const t = tr(), deps = $("deps");
  deps.replaceChildren();
  if (d.error === "feed_down") { deps.append(el("div", { className: "empty", textContent: t.feedDown })); $("fresh").textContent = ""; return; }
  if (d.stale) { deps.append(el("div", { className: "empty", textContent: t.stale })); $("fresh").textContent = ""; return; }
  if (!d.departures || !d.departures.length) {
    deps.append(el("div", { className: "empty", textContent: t.none }));
  }
  for (const x of d.departures || []) {
    const mins = x.minutes <= 0 ? t.now : `${x.minutes} ${t.min}`;
    deps.append(el("div", { className: "dep" },
      el("span", { textContent: x.destination }),
      el("span", { className: "tag" + (x.realtime ? " rt" : ""), textContent: x.realtime ? t.realtime : t.scheduled }),
      el("span", { className: "min", textContent: mins }),
    ));
  }
  $("fresh").textContent = t.updated(d.age_seconds);
}

// ---------- ask ----------
async function ask(q) {
  q = (q || "").trim();
  if (!q) return;
  $("answer").textContent = "…";
  try {
    const r = await api("/api/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q, session: state.session, lang: state.lang }),
    });
    if (r.lang && r.lang !== state.lang) { state.lang = r.lang; applyLang(); }
    $("answer").textContent = r.answer;
    if ($("speak").checked && "speechSynthesis" in window) {
      const u = new SpeechSynthesisUtterance(r.answer);
      u.lang = state.lang === "fr" ? "fr-FR" : "en-GB";
      speechSynthesis.cancel(); speechSynthesis.speak(u);
    }
    if (r.stop) {
      const s = state.stops.find((x) => x.id === r.stop.id) || r.stop;
      if (s.lat != null) selectStop(s, r.line && r.line.id);
    }
  } catch (e) {
    $("answer").textContent = e.message;
  }
  refreshStatus();
}
$("askForm").onsubmit = (e) => { e.preventDefault(); ask($("q").value); };

// Browser speech recognition (Chrome/Edge). Audio is handled by the browser vendor.
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
$("mic").onclick = () => {
  if (!SR) { $("answer").textContent = tr().micUnsupported; return; }
  const rec = new SR();
  rec.lang = state.lang === "fr" ? "fr-FR" : "en-GB";
  rec.interimResults = false; rec.maxAlternatives = 1;
  $("answer").textContent = tr().listening;
  rec.onresult = (ev) => { const text = ev.results[0][0].transcript; $("q").value = text; ask(text); };
  rec.onerror = () => { $("answer").textContent = tr().micUnsupported; };
  rec.start();
};

// ---------- status ----------
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const p = s.prim, t = tr();
    const dot = $("feedDot");
    const recentError = p.last_error_at && (!p.last_ok_at || p.last_error_at > p.last_ok_at);
    if (!p.configured || recentError) { dot.className = "dot bad"; $("feedText").textContent = t.feedErr(p.last_error || "API key missing"); }
    else if (!p.last_ok_at) { dot.className = "dot warn"; $("feedText").textContent = t.feedUnknown; }
    else { dot.className = "dot ok"; $("feedText").textContent = t.feedOk(p.calls_today, p.daily_budget); }
    if (s.phone) {
      $("phone").hidden = false;
      $("phoneLink").textContent = s.phone;
      $("phoneLink").href = "tel:" + s.phone.replace(/[^+\d]/g, "");
    }
  } catch { /* status is best-effort */ }
}

// ---------- boot ----------
(async () => {
  applyLang();
  try { state.stops = await api("/api/stops"); drawMarkers(); } catch (e) { $("answer").textContent = e.message; }
  refreshStatus();
})();
