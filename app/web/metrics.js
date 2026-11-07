"use strict";
const $ = (id) => document.getElementById(id);
function el(tag, props = {}, ...kids) { const n = document.createElement(tag); Object.assign(n, props); for (const k of kids) n.append(k); return n; }
function tile(k, v, d, cls) { return el("div", { className: "tile" }, el("div", { className: "k", textContent: k }), el("div", { className: "v " + (cls || ""), textContent: v }), el("div", { className: "d", textContent: d || "" })); }
function row(cells, head) { const tr = el("tr"); for (const c of cells) tr.append(el(head ? "th" : "td", { textContent: c == null ? "–" : String(c) })); return tr; }
const LABEL = { rules: "Rules", ai: "AI (verified as written)", ai_fallback: "AI blocked → template", rules_fallback: "AI unavailable → rules" };

async function load() {
  let m;
  try { m = await (await fetch("/api/metrics", { cache: "no-store" })).json(); } catch { return; }
  const s = m.service, ai = m.ai;
  $("since").textContent = `Since ${new Date(s.since).toLocaleString()} · aggregates only, no question text, no IPs · refreshes every 10 s`;
  const rules = s.latency_ms.rules || {}, aiLat = s.latency_ms.ai || {};
  const t = $("tiles"); t.replaceChildren(
    tile("Questions", s.questions, "since start"),
    tile("Answered by rules", s.questions ? Math.round((1 - s.ai_share) * 100) + "%" : "–", rules.p50 != null ? `p50 ${rules.p50} ms · p95 ${rules.p95} ms` : ""),
    tile("Needed the AI", s.questions ? Math.round(s.ai_share * 100) + "%" : "–", aiLat.p50 != null ? `p50 ${aiLat.p50} ms · p95 ${aiLat.p95} ms` : (ai.enabled ? "" : "AI disabled")),
    tile("Unverified answers shown", "0", `${s.grounding.retries} corrected · ${s.grounding.blocked_to_fallback} blocked`, "ok"),
    tile("AI cost today", ai.enabled ? `$${ai.spent_usd_today.toFixed(4)}` : "–", ai.enabled ? `cap $${ai.daily_budget_usd} · ${ai.calls_today} calls · ${ai.model}` : "no key configured"),
  );
  const p = $("paths"); p.replaceChildren(row(["Path", "Questions", "p50 ms", "p95 ms"], true));
  for (const [k, n] of Object.entries(s.by_path)) { const l = s.latency_ms[k] || {}; p.append(row([LABEL[k] || k, n, l.p50, l.p95])); }
  const src = $("sources"); src.replaceChildren(row(["Source", "Requests today", "Daily budget", "Last error"], true),
    row(["IDFM next departures + traffic", m.prim.calls_today, m.prim.daily_budget, m.prim.last_error]),
    row(["IDFM journey planner", m.routes.calls_today, m.routes.daily_budget, m.routes.last_error]),
    row(["Vélib' (Paris open data)", m.velib.calls_today, m.velib.daily_budget, m.velib.last_error]));
}
load(); setInterval(load, 10000);
