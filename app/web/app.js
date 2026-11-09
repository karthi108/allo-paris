// Allô Paris web app. Every time shown comes from /api (IDFM PRIM). DOM is built with
// textContent only: no HTML is ever built from data.
"use strict";

const I18N = {
  fr: {
    search: "Station ou question : ligne 4 Gare du Nord",
    call: "Appeler", nearMe: "Près de moi", favorites: "Favoris", tryAsking: "Essayez",
    noFav: "Touchez ☆ sur une station pour l'ajouter ici.",
    back: "← Retour", to: "Direction", live: "Temps réel", sched: "Théorique",
    now: "à quai", min: "min", none: "Aucun départ annoncé pour le moment.",
    feedDown: "Données temps réel indisponibles. Aucun horaire affiché.",
    stale: "Données trop anciennes. Aucun horaire affiché.",
    updated: (s) => `Mis à jour il y a ${s} s · actualisation auto`,
    disruption: "Info trafic", more: "Lire la suite", less: "Réduire",
    feedOk: (n, b) => `Données IDFM OK · ${n}/${b} requêtes aujourd'hui`,
    feedErr: (e) => `Problème de données : ${e}`, feedUnknown: "Données IDFM prêtes",
    tooMany: "Trop de requêtes, réessayez dans une minute.", error: "Erreur réseau.",
    ask: (q) => `Demander : « ${q} »`,
    pathRules: "⚡ Règles", pathAi: "✦ IA vérifiée", pathAiFb: "✦ IA → modèle sûr", pathRulesFb: "⚡ Règles (IA indisponible)", tools: "outils",
    examples: ["prochain RER A à Châtelet", "comment aller à la tour Eiffel depuis Gare du Nord", "perturbations RER B", "Vélib près de la tour Eiffel", "bornes près du Panthéon"],
    velib: "Vélib à proximité", bikes: "vélos", ebikes: "élec.", docks: "places", closed: "fermée", velibNone: "Aucune station Vélib à moins de 500 m.",
    ev: "Bornes", chargers: "Bornes Belib' à proximité", free: "libre(s)", charging: "en charge", out: "hors service",
    evNone: "Aucune borne Belib' à moins de 500 m.", evWarn: "signalée peu fiable (historique)",
    legend: [["ok", "au moins une libre"], ["busy", "toutes occupées"], ["down", "toutes hors service"], ["flag", "signalée peu fiable"]],
    speakOn: "Lecture à voix haute activée.", speakNo: "Aucune voix française installée dans ce navigateur : la lecture à voix haute est indisponible.",
    modes: { Metro: "Métro", RapidTransit: "RER", Tramway: "Tram", LocalTrain: "Train" },
    micNo: "Micro non disponible dans ce navigateur.", listening: "J'écoute…",
    geoNo: "Position indisponible.", nearNone: "Aucune station à moins de 2 km.",
    m: (d) => d < 1000 ? `${Math.round(d / 10) * 10} m` : `${(d / 1000).toFixed(1)} km`,
    disclaimer: "Projet indépendant utilisant les données temps réel officielles d'Île-de-France Mobilités (open data PRIM). Non affilié à IDFM ni à la RATP.",
  },
  en: {
    search: "Station or question: line 4 Gare du Nord",
    call: "Call", nearMe: "Near me", favorites: "Favourites", tryAsking: "Try",
    noFav: "Tap ☆ on a station to pin it here.",
    back: "← Back", to: "Towards", live: "Real-time", sched: "Scheduled",
    now: "now", min: "min", none: "No departures announced right now.",
    feedDown: "Real-time data unavailable. No times shown.",
    stale: "Data too old. No times shown.",
    updated: (s) => `Updated ${s} s ago · auto-refresh`,
    disruption: "Service update", more: "Read more", less: "Show less",
    feedOk: (n, b) => `IDFM data OK · ${n}/${b} requests today`,
    feedErr: (e) => `Data problem: ${e}`, feedUnknown: "IDFM data ready",
    tooMany: "Too many requests, try again in a minute.", error: "Network error.",
    ask: (q) => `Ask: “${q}”`,
    pathRules: "⚡ Rules", pathAi: "✦ AI, verified", pathAiFb: "✦ AI → safe template", pathRulesFb: "⚡ Rules (AI unavailable)", tools: "tools",
    examples: ["next RER A at Châtelet", "fastest way from Gare du Nord to the Eiffel Tower", "disruptions RER B", "Vélib near the Eiffel Tower", "EV chargers near Bastille"],
    velib: "Vélib nearby", bikes: "bikes", ebikes: "e-bikes", docks: "docks", closed: "closed", velibNone: "No Vélib station within 500 m.",
    ev: "EV chargers", chargers: "Belib' chargers nearby", free: "free", charging: "charging", out: "out of service",
    evNone: "No Belib' charger within 500 m.", evWarn: "flagged unreliable (history)",
    legend: [["ok", "at least one free"], ["busy", "all in use"], ["down", "all out of service"], ["flag", "flagged unreliable"]],
    speakOn: "Read aloud is on.", speakNo: "No English voice is installed in this browser, so read aloud is unavailable.",
    modes: { Metro: "Metro", RapidTransit: "RER", Tramway: "Tram", LocalTrain: "Train" },
    micNo: "Microphone not available in this browser.", listening: "Listening…",
    geoNo: "Location unavailable.", nearNone: "No station within 2 km.",
    m: (d) => d < 1000 ? `${Math.round(d / 10) * 10} m` : `${(d / 1000).toFixed(1)} km`,
    disclaimer: "Independent project using official Île-de-France Mobilités real-time open data (PRIM). Not affiliated with or endorsed by IDFM or RATP.",
  },
};

// ---------- helpers ----------
const $ = (id) => document.getElementById(id);
const HEX = /^[0-9a-f]{6}$/i;
function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k === "attrs") for (const [a, b] of Object.entries(v)) n.setAttribute(a, b);
    else n[k] = v;
  }
  for (const k of kids) if (k != null) n.append(k);
  return n;
}
const norm = (s) => s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};
function haversine(a, b) {
  const R = 6371e3, r = Math.PI / 180;
  const dLat = (b.lat - a.lat) * r, dLon = (b.lon - a.lon) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

const state = {
  lang: store.get("allo.lang", (navigator.language || "fr").startsWith("fr") ? "fr" : "en"),
  stops: [], byId: new Map(), markers: new Map(), selected: null, timer: null,
  modes: new Set(store.get("allo.modes", ["Metro", "RapidTransit", "Tramway", "LocalTrain"])),
  favs: store.get("allo.favs", []), near: null, suggest: [], active: -1,
  ev: store.get("allo.ev", false), evLayer: null, evData: null, evAt: 0,
  session: store.get("allo.session", null) || (() => { const s = (crypto.randomUUID && crypto.randomUUID()) || String(Math.random()).slice(2); store.set("allo.session", s); return s; })(),
};
const tr = () => I18N[state.lang];
// No mode selected (e.g. chargers only): the map shows no stations, but search, Near me and
// station panels still cover every line.
const modeOn = (m) => !state.modes.size || state.modes.has(m);

function badge(line) {
  const b = el("span", { class: `badge ${line.mode}`, textContent: line.short, title: line.label });
  if (HEX.test(line.color)) b.style.background = "#" + line.color;
  if (HEX.test(line.text_color)) b.style.color = "#" + line.text_color;
  return b;
}
function badges(stop, max = 8) {
  const w = el("span", { class: "badges" });
  stop.lines.filter((l) => modeOn(l.mode)).slice(0, max).forEach((l) => w.append(badge(l)));
  return w;
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (r.status === 429) throw new Error(tr().tooMany);
  if (!r.ok) throw new Error(tr().error);
  return r.json();
}

// ---------- map ----------
const map = L.map("map", { zoomControl: true, attributionControl: true }).setView([48.8566, 2.3522], 12);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, attribution: "© OpenStreetMap contributors",
}).addTo(map);
let ring = null;

function stopColor(s) {
  const l = s.lines.find((x) => modeOn(x.mode) && HEX.test(x.color));
  return l ? "#" + l.color : "#777";
}
function drawMarkers() {
  for (const m of state.markers.values()) m.remove();
  state.markers.clear();
  for (const s of state.stops) {
    const visible = s.lines.filter((l) => state.modes.has(l.mode));
    if (!visible.length) continue;
    const hub = visible.length >= 3;
    const m = L.circleMarker([s.lat, s.lon], {
      radius: hub ? 7 : 5, color: "#ffffff", weight: hub ? 2.5 : 2, fillColor: stopColor(s), fillOpacity: 1,
    }).addTo(map);
    m.bindTooltip(s.name, { direction: "top", offset: [0, -6] });
    m.on("click", () => openStation(s));
    state.markers.set(s.id, m);
  }
}
function highlight(s) {
  if (ring) ring.remove();
  ring = L.circleMarker([s.lat, s.lon], { radius: 14, color: stopColor(s), weight: 3, fill: false, interactive: false }).addTo(map);
}

function renderFilters() {
  const f = $("filters"); f.replaceChildren();
  for (const [mode, label] of Object.entries(tr().modes)) {
    const on = state.modes.has(mode);
    f.append(el("button", {
      type: "button", class: "chip" + (on ? " on" : ""), textContent: label, attrs: { "aria-pressed": String(on) },
      onclick: () => {
        // Any combination is allowed, including none (e.g. chargers only)
        on ? state.modes.delete(mode) : state.modes.add(mode);
        store.set("allo.modes", [...state.modes]); renderFilters(); drawMarkers();
      },
    }));
  }
  f.append(el("button", {
    type: "button", class: "chip ev" + (state.ev ? " on" : ""), textContent: "⚡ " + tr().ev,
    attrs: { "aria-pressed": String(state.ev) }, onclick: () => setEv(!state.ev),
  }));
}

// ---------- Belib' chargers (live status + reliability flags from the collector) ----------
function setEv(on) {
  state.ev = on; store.set("allo.ev", on); renderFilters(); drawChargers(); renderLegend();
  document.body.classList.toggle("ev-mode", on); // stations fade so chargers stand out
}
function chargerSummary(a) {
  const t = tr();
  let s = `${a.available} ${t.free} / ${a.in_service}`;
  if (a.charging) s += ` · ${a.charging} ${t.charging}`;
  if (a.out_of_service) s += ` · ${a.out_of_service} ${t.out}`;
  return s;
}
function chargerCard(a) {
  const t = tr();
  const box = el("div", { class: "evcard" }, el("strong", { textContent: a.name }), el("div", { textContent: chargerSummary(a) }));
  if (a.warnings.length) {
    box.append(el("div", { class: "evwarn", textContent: "⚠ " + t.evWarn }));
    for (const w of a.warnings) box.append(el("div", { class: "evdetail", textContent: w }));
  }
  return box;
}
async function drawChargers() {
  if (state.evLayer) { state.evLayer.remove(); state.evLayer = null; }
  if (!state.ev) return;
  try {
    if (!state.evData || Date.now() - state.evAt > 60000) {
      state.evData = await api("/api/chargers/map"); state.evAt = Date.now();
    }
  } catch (e) { $("answer").textContent = e.message; return; }
  if (!state.ev || state.evData.error) return;
  const layer = L.layerGroup();
  for (const a of state.evData.addresses) {
    // Square ⚡ pins, so chargers never look like station dots. The icon markup is a fixed
    // string; no data goes into HTML.
    const kind = a.available > 0 ? "ok" : a.out_of_service >= a.in_service ? "down" : "busy";
    const icon = L.divIcon({ className: `evpin ${kind}${a.warnings.length ? " flag" : ""}`, html: "⚡", iconSize: [20, 20] });
    const m = L.marker([a.lat, a.lon], { icon, keyboard: true, title: a.name, riseOnHover: true });
    m.bindTooltip(a.name, { direction: "top", offset: [0, -6] });
    m.bindPopup(() => chargerCard(a));
    layer.addLayer(m);
  }
  if (state.evLayer) state.evLayer.remove();
  state.evLayer = layer.addTo(map);
  renderLegend();
}
function renderLegend() {
  const box = $("legend"); box.replaceChildren();
  box.hidden = !state.ev;
  if (!state.ev) return;
  box.append(el("div", { class: "legend-title", textContent: "⚡ Belib'" }));
  for (const [kind, label] of tr().legend) {
    box.append(el("div", { class: "legend-row" }, el("span", { class: `evpin ${kind === "flag" ? "ok flag" : kind}`, textContent: "⚡" }), el("span", { textContent: label })));
  }
}
async function loadChargers() {
  const sel = state.selected; if (!sel) return;
  try {
    const d = await api(`/api/chargers?stop=${encodeURIComponent(sel.stop.id)}`);
    if (state.selected !== sel) return;
    const box = $("chargers"); if (!box || d.error) return;
    const t = tr();
    box.replaceChildren(el("div", { class: "section-title", textContent: t.chargers }));
    if (!d.addresses.length) { box.append(el("div", { class: "empty", textContent: t.evNone })); return; }
    const ul = el("ul", { class: "list" });
    for (const a of d.addresses) {
      ul.append(el("li", { onclick: () => { if (!state.ev) setEv(true); map.flyTo([a.lat, a.lon], 17, { duration: 0.5 }); } },
        el("span", { class: "name", textContent: a.name }),
        el("span", { class: "meta" + (a.warnings.length ? " warn" : ""),
          textContent: `${a.distance_m} m · ${chargerSummary(a)}` + (a.warnings.length ? ` · ⚠ ${t.evWarn}` : "") })));
    }
    box.append(ul);
  } catch { /* optional section */ }
}

// ---------- home ----------
function renderHome() {
  const t = tr(), h = $("home"); h.replaceChildren();
  const favs = state.favs.map((id) => state.byId.get(id)).filter(Boolean);
  h.append(el("div", { class: "section-title", textContent: t.favorites }));
  if (!favs.length) h.append(el("div", { class: "empty", textContent: t.noFav }));
  else h.append(stationList(favs));

  if (state.near) {
    h.append(el("div", { class: "section-title", textContent: t.nearMe }));
    if (!state.near.length) h.append(el("div", { class: "empty", textContent: t.nearNone }));
    else h.append(stationList(state.near.map((n) => n.stop), state.near.map((n) => t.m(n.d))));
  }

  h.append(el("div", { class: "section-title", textContent: t.tryAsking }));
  const chips = el("div", { class: "chips" });
  t.examples.forEach((q) => chips.append(el("button", { type: "button", class: "chip", textContent: q, onclick: () => { $("q").value = q; ask(q); } })));
  h.append(chips);
  h.append(el("p", { class: "empty", textContent: t.disclaimer, style: "font-size:12px;margin-top:16px" }));
}
function stationList(stops, metas = []) {
  const ul = el("ul", { class: "list" });
  stops.forEach((s, i) => ul.append(el("li", { onclick: () => openStation(s) },
    el("span", { class: "name", textContent: s.name }), metas[i] ? el("span", { class: "meta", textContent: metas[i] }) : null, badges(s, 5))));
  return ul;
}

// ---------- station ----------
function openStation(s, lineId) {
  const lines = s.lines.filter((l) => modeOn(l.mode));
  const line = lines.find((l) => l.id === lineId) || lines[0] || s.lines[0];
  state.selected = { stop: s, line };
  map.flyTo([s.lat, s.lon], Math.max(map.getZoom(), 15), { duration: 0.6 });
  highlight(s);
  $("home").hidden = true; $("station").hidden = false;
  $("card").classList.remove("collapsed");
  renderStation();
  loadBoard();
  loadTraffic();
  loadVelib(); loadChargers();
}
function closeStation() {
  clearTimeout(state.timer); state.selected = null;
  if (ring) { ring.remove(); ring = null; }
  $("station").hidden = true; $("home").hidden = false; $("answer").textContent = ""; $("answerMeta").replaceChildren(); renderHome();
}
function renderStation() {
  const t = tr(), { stop, line } = state.selected, v = $("station");
  v.replaceChildren();
  const fav = state.favs.includes(stop.id);
  v.append(el("button", { type: "button", class: "back", textContent: t.back, onclick: closeStation }));
  v.append(el("div", { class: "station-head" },
    el("h2", { textContent: stop.name }),
    el("button", { type: "button", class: "star", textContent: fav ? "★" : "☆", attrs: { "aria-pressed": String(fav), "aria-label": t.favorites },
      onclick: () => { state.favs = fav ? state.favs.filter((x) => x !== stop.id) : [stop.id, ...state.favs].slice(0, 12); store.set("allo.favs", state.favs); renderStation(); loadBoard(); loadTraffic(); loadVelib(); loadChargers(); } })));
  const tabs = el("div", { class: "tabs", attrs: { role: "tablist" } });
  for (const l of stop.lines) {
    tabs.append(el("button", { type: "button", class: "tab", attrs: { role: "tab", "aria-selected": String(l.id === line.id), "aria-label": l.label },
      onclick: () => { state.selected.line = l; renderStation(); loadBoard(); loadTraffic(); loadVelib(); loadChargers(); } }, badge(l)));
  }
  v.append(tabs);
  v.append(el("div", { id: "banner" }));
  v.append(el("div", { class: "board", id: "board" }, el("div", { class: "skeleton" }), el("div", { class: "skeleton", style: "border-top:1px solid var(--line)" })));
  v.append(el("div", { class: "fresh", id: "fresh" }));
  v.append(el("div", { id: "velib" }));
  v.append(el("div", { id: "chargers" }));
}

async function loadVelib() {
  const sel = state.selected; if (!sel) return;
  try {
    const d = await api(`/api/velib?stop=${encodeURIComponent(sel.stop.id)}`);
    if (state.selected !== sel) return;
    const box = $("velib"); if (!box || d.error) return;
    const t = tr();
    box.replaceChildren(el("div", { class: "section-title", textContent: t.velib }));
    if (!d.stations.length) { box.append(el("div", { class: "empty", textContent: t.velibNone })); return; }
    const ul = el("ul", { class: "list" });
    for (const s of d.stations) {
      const meta = s.renting ? `${s.bikes} ${t.bikes} (${s.ebikes} ${t.ebikes}) · ${s.docks} ${t.docks}` : t.closed;
      ul.append(el("li", { onclick: () => map.flyTo([s.lat, s.lon], 17, { duration: 0.5 }) },
        el("span", { class: "name", textContent: s.name }),
        el("span", { class: "meta", textContent: `${s.distance_m} m · ${meta}` })));
    }
    box.append(ul);
  } catch { /* optional section */ }
}

async function loadBoard() {
  clearTimeout(state.timer);
  const sel = state.selected; if (!sel) return;
  try {
    const d = await api(`/api/departures?stop=${encodeURIComponent(sel.stop.id)}&line=${encodeURIComponent(sel.line.id)}&lang=${state.lang}`);
    if (state.selected !== sel) return;
    renderBoard(d);
  } catch (e) {
    const b = $("board"); if (b) b.replaceChildren(el("div", { class: "dir" }, el("span", { class: "empty", textContent: e.message })));
  }
  refreshStatus();
  state.timer = setTimeout(() => { if (state.selected === sel) loadBoard(); }, 30000);
}
function renderBoard(d) {
  const t = tr(), b = $("board"), f = $("fresh");
  if (!b) return;
  b.replaceChildren(); f.replaceChildren();
  const msg = d.error === "feed_down" ? t.feedDown : d.stale ? t.stale : !d.departures?.length ? t.none : null;
  if (msg) { b.append(el("div", { class: "dir" }, el("span", { class: "empty", textContent: msg }))); return; }
  const groups = new Map();
  for (const x of d.departures) { if (!groups.has(x.destination)) groups.set(x.destination, []); groups.get(x.destination).push(x); }
  for (const [dest, xs] of groups) {
    const times = el("div", { class: "times" });
    xs.slice(0, 3).forEach((x, i) => {
      const label = x.minutes <= 0 ? t.now : String(x.minutes);
      const node = el("span", { class: `t ${i ? "later" : "next"}${x.realtime ? "" : " sched"}`, textContent: label,
        title: (x.realtime ? t.live : t.sched) + " · " + new Date(x.at).toLocaleTimeString(state.lang, { hour: "2-digit", minute: "2-digit" }) });
      if (x.minutes > 0) node.append(el("small", { textContent: t.min }));
      times.append(node);
    });
    b.append(el("div", { class: "dir" },
      el("div", {}, el("div", { class: "to", textContent: t.to }), el("div", { class: "dest", textContent: dest })), times));
  }
  const allLive = d.departures.every((x) => x.realtime);
  f.append(allLive ? el("span", { class: "live", attrs: { "aria-hidden": "true" } }) : null,
    document.createTextNode((allLive ? t.live : t.sched) + " · " + t.updated(d.age_seconds)));
}

async function loadTraffic() {
  const sel = state.selected; if (!sel) return;
  try {
    const d = await api(`/api/traffic?line=${encodeURIComponent(sel.line.id)}`);
    if (state.selected !== sel) return;
    const box = $("banner"); if (!box) return;
    box.replaceChildren();
    if (!d.messages?.length) return;
    const t = tr(), full = d.messages.join(" ");
    const short = full.length > 170 ? full.slice(0, 167).trimEnd() + "…" : full;
    const text = el("span", { textContent: short });
    const banner = el("div", { class: "banner", attrs: { role: "status" } }, el("b", { textContent: t.disruption }), text);
    if (short !== full) {
      let open = false;
      const tog = el("button", { type: "button", textContent: " " + t.more });
      tog.onclick = () => { open = !open; text.textContent = open ? full : short; tog.textContent = " " + (open ? t.less : t.more); };
      banner.append(tog);
    }
    box.append(banner);
  } catch { /* banner is optional */ }
}

// ---------- search / ask ----------
function updateSuggest() {
  const q = norm($("q").value), ul = $("suggest");
  ul.replaceChildren(); state.active = -1;
  if (q.length < 2) { $("q").setAttribute("aria-expanded", "false"); return; }
  const scored = [];
  for (const s of state.stops) {
    const n = s._n;
    const i = n.indexOf(q);
    if (i === -1 || !s.lines.some((l) => modeOn(l.mode))) continue;
    scored.push({ s, score: (i === 0 ? 0 : n[i - 1] === " " ? 1 : 2) * 100 + n.length });
  }
  scored.sort((a, b) => a.score - b.score);
  state.suggest = scored.slice(0, 6).map((x) => x.s);
  state.suggest.forEach((s, i) => ul.append(el("li", { attrs: { role: "option", id: `sg${i}` }, onmousedown: (e) => { e.preventDefault(); pick(s); } },
    el("span", { class: "name", textContent: s.name }), badges(s, 5))));
  const raw = $("q").value.trim();
  ul.append(el("li", { class: "ask-row", attrs: { role: "option" }, onmousedown: (e) => { e.preventDefault(); ask(raw); } },
    el("span", { class: "name", textContent: tr().ask(raw) })));
  $("q").setAttribute("aria-expanded", "true");
}
function pick(s) { $("q").value = ""; $("suggest").replaceChildren(); $("answer").textContent = ""; $("answerMeta").replaceChildren(); openStation(s); $("q").blur(); }
function moveActive(delta) {
  const items = [...$("suggest").children]; if (!items.length) return;
  state.active = (state.active + delta + items.length) % items.length;
  items.forEach((li, i) => li.setAttribute("aria-selected", String(i === state.active)));
}
$("q").addEventListener("input", updateSuggest);
$("q").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { e.preventDefault(); moveActive(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); moveActive(-1); }
  else if (e.key === "Escape") { $("suggest").replaceChildren(); }
});
$("q").addEventListener("blur", () => setTimeout(() => $("suggest").replaceChildren(), 120));
$("searchForm").onsubmit = (e) => {
  e.preventDefault();
  const items = [...$("suggest").children];
  if (state.active >= 0 && state.active < state.suggest.length) return pick(state.suggest[state.active]);
  if (state.active === items.length - 1 && items.length) return ask($("q").value);
  ask($("q").value);
};

async function ask(q) {
  q = (q || "").trim(); if (!q) return;
  $("suggest").replaceChildren(); $("q").blur();
  $("answer").textContent = "…"; $("answerMeta").replaceChildren(); $("card").classList.remove("collapsed");
  try {
    const r = await api("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q, session: state.session, lang: state.lang }) });
    if (r.lang && r.lang !== state.lang) setLang(r.lang);
    $("answer").textContent = r.answer;
    renderMeta(r);
    speak(r.answer);
    if (r.intent === "ev") {
      if (!state.ev) setEv(true);
      if (r.focus) { map.flyTo(r.focus, 16, { duration: 0.6 }); showChargerAnswer(r); }
    }
    if (r.stop) { const s = state.byId.get(r.stop.id); if (s) openStation(s, r.line && r.line.id); }
  } catch (e) { $("answer").textContent = e.message; }
  refreshStatus();
}

// The spoken answer is one paragraph (good for voice); on screen, show the first sentence and
// a list of addresses from the same live data.
async function showChargerAnswer(r) {
  const first = r.answer.split(/(?<=\.)\s/)[0];
  try {
    const d = await api(`/api/chargers/near?lat=${r.focus[0]}&lon=${r.focus[1]}`);
    if (d.error || !d.addresses.length) return;
    const t = tr(), ul = el("ul", { class: "list answer-list" });
    for (const a of d.addresses) {
      ul.append(el("li", { onclick: () => map.flyTo([a.lat, a.lon], 18, { duration: 0.5 }) },
        el("span", { class: "name", textContent: a.name }),
        el("span", { class: "meta" + (a.warnings.length ? " warn" : ""),
          textContent: `${a.distance_m} m · ${chargerSummary(a)}` + (a.warnings.length ? ` · ⚠ ${t.evWarn}` : "") })));
    }
    $("answer").replaceChildren(el("div", { textContent: first }), ul);
  } catch { /* keep the plain text answer */ }
}

function renderMeta(r) {
  const t = tr(), m = $("answerMeta"); m.replaceChildren();
  if (!r || !r.path) return;
  const label = { rules: t.pathRules, ai: t.pathAi, ai_fallback: t.pathAiFb, rules_fallback: t.pathRulesFb }[r.path] || r.path;
  const ms = r.latency_ms >= 1000 ? (r.latency_ms / 1000).toFixed(1) + " s" : r.latency_ms + " ms";
  m.append(el("span", { class: "pathtag" + (r.path.startsWith("ai") ? " ai" : ""), textContent: label }),
    el("span", { textContent: ms + (r.tools && r.tools.length ? ` · ${r.tools.length} ${t.tools}` : "") }),
    el("a", { href: "/metrics", textContent: "↗" }));
}

// Read-aloud with the browser's own voices (free, nothing sent to us)
function voiceFor(lang) {
  const voices = ("speechSynthesis" in window) ? speechSynthesis.getVoices() : [];
  return voices.find((v) => v.lang && v.lang.toLowerCase().startsWith(lang)) || null;
}
function speak(text, force = false) {
  if ((!force && !store.get("allo.speak", false)) || !("speechSynthesis" in window) || !text) return false;
  const voice = voiceFor(state.lang);
  if (!voice && speechSynthesis.getVoices().length) return false; // voices loaded, none in this language
  const u = new SpeechSynthesisUtterance(text);
  u.lang = state.lang === "fr" ? "fr-FR" : "en-GB";
  if (voice) u.voice = voice;
  speechSynthesis.cancel(); speechSynthesis.speak(u);
  return true;
}
function renderSpeak() {
  const on = store.get("allo.speak", false);
  $("speak").setAttribute("aria-pressed", String(on));
  $("speak").title = state.lang === "fr" ? (on ? "Lecture à voix haute : activée" : "Lecture à voix haute : désactivée")
    : (on ? "Read aloud: on" : "Read aloud: off");
}
$("speak").onclick = () => {
  const on = !store.get("allo.speak", false);
  store.set("allo.speak", on); renderSpeak();
  if (!("speechSynthesis" in window)) { $("answerMeta").replaceChildren(el("span", { textContent: tr().speakNo })); return; }
  if (!on) { speechSynthesis.cancel(); return; }
  const current = $("answer").textContent.trim();
  const ok = speak(current || tr().speakOn, true);
  if (!ok) $("answerMeta").replaceChildren(el("span", { class: "warn", textContent: tr().speakNo }));
};

// Browser speech recognition (Chrome/Edge): audio goes to the browser vendor, not to us.
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
$("mic").onclick = () => {
  if (!SR) { $("answer").textContent = tr().micNo; return; }
  const rec = new SR(); rec.lang = state.lang === "fr" ? "fr-FR" : "en-GB"; rec.interimResults = false;
  $("mic").classList.add("rec"); $("answer").textContent = tr().listening;
  rec.onresult = (ev) => { const text = ev.results[0][0].transcript; $("q").value = text; ask(text); };
  rec.onerror = () => { $("answer").textContent = tr().micNo; };
  rec.onend = () => $("mic").classList.remove("rec");
  rec.start();
};

// ---------- near me ----------
$("locate").onclick = () => {
  if (!navigator.geolocation) { $("answer").textContent = tr().geoNo; return; }
  navigator.geolocation.getCurrentPosition((pos) => {
    const me = { lat: pos.coords.latitude, lon: pos.coords.longitude };
    state.near = state.stops.map((s) => ({ stop: s, d: haversine(me, s) }))
      .filter((x) => x.d <= 2000 && x.stop.lines.some((l) => modeOn(l.mode)))
      .sort((a, b) => a.d - b.d).slice(0, 5);
    map.flyTo([me.lat, me.lon], 15, { duration: 0.6 });
    if (state.selected) closeStation(); else renderHome();
    $("card").classList.remove("collapsed");
  }, () => { $("answer").textContent = tr().geoNo; }, { enableHighAccuracy: false, timeout: 8000, maximumAge: 60000 });
};

// ---------- language, sheet, status ----------
function setLang(lang) {
  state.lang = lang; store.set("allo.lang", lang);
  const t = tr();
  document.documentElement.lang = lang;
  $("q").placeholder = t.search; $("callLabel").textContent = t.call;
  $("langFr").setAttribute("aria-pressed", String(lang === "fr"));
  $("langEn").setAttribute("aria-pressed", String(lang === "en"));
  $("locate").title = t.nearMe; $("locate").setAttribute("aria-label", t.nearMe);
  $("privacyLink").textContent = lang === "fr" ? "Confidentialité" : "Privacy";
  renderSpeak();
  renderFilters();
  if (state.selected) { renderStation(); loadBoard(); loadTraffic(); loadVelib(); loadChargers(); } else renderHome();
}
$("langFr").onclick = () => setLang("fr");
$("langEn").onclick = () => setLang("en");
$("handle").onclick = () => $("card").classList.toggle("collapsed");

// Theme: auto (follows the system) -> light -> dark
const THEMES = { auto: "◐", light: "☀", dark: "☾" };
const THEME_LABEL = { auto: "Auto", light: "Light", dark: "Dark" };
function applyTheme(mode) {
  if (mode === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", mode);
  $("theme").textContent = THEMES[mode];
  $("theme").title = "Theme: " + THEME_LABEL[mode];
  store.set("allo.theme", mode);
}
$("theme").onclick = () => {
  const order = ["auto", "light", "dark"];
  applyTheme(order[(order.indexOf(store.get("allo.theme", "auto")) + 1) % order.length]);
};
applyTheme(store.get("allo.theme", "auto"));

async function refreshStatus() {
  try {
    const s = await api("/api/status"), p = s.prim, t = tr(), dot = $("feedDot");
    const err = p.last_error_at && (!p.last_ok_at || p.last_error_at > p.last_ok_at);
    if (!p.configured || err) { dot.className = "dot bad"; $("feedText").textContent = t.feedErr(p.last_error || "API key missing"); }
    else if (!p.last_ok_at) { dot.className = "dot ok"; $("feedText").textContent = t.feedUnknown; }
    else { dot.className = "dot ok"; $("feedText").textContent = t.feedOk(p.calls_today, p.daily_budget); }
    if (s.phone) { $("call").hidden = false; $("call").href = "tel:" + s.phone.replace(/[^+\d]/g, ""); $("call").title = s.phone; }
  } catch { /* best effort */ }
}

(async () => {
  setLang(state.lang);
  if (window.matchMedia("(max-width: 760px)").matches) $("card").classList.add("collapsed");
  try {
    state.stops = await api("/api/stops");
    for (const s of state.stops) { s._n = norm(s.name); for (const id of s.ids || [s.id]) state.byId.set(id, s); }
    drawMarkers(); renderHome();
    if (state.ev) setEv(true);
  } catch (e) { $("answer").textContent = e.message; }
  refreshStatus();
})();
