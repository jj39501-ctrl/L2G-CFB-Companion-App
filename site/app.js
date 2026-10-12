// L2G Dynasty companion: a read-only view of data/*.json produced by `python -m extract`.
"use strict";

const FILES = ["members", "schedule", "top25", "standings", "season_stats", "heisman_watch", "players_of_week"];
const D = {};                 // screen -> file contents ({captured_at, data})
let memberTeams = new Map();  // team -> gamertag

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v) => (v === null || v === undefined || v === "" ? "–" : typeof v === "number" ? v.toLocaleString() : esc(v));

async function load() {
  await Promise.all(FILES.map(async (f) => {
    try {
      const r = await fetch(`data/${f}.json`, { cache: "no-cache" });
      if (r.ok) D[f] = await r.json();
    } catch { /* screen not published yet */ }
  }));
  memberTeams = new Map((D.members?.data?.[0]?.rows || []).filter((m) => m.team).map((m) => [m.team, m.gamertag]));
  const dates = FILES.map((f) => D[f]?.captured_at).filter(Boolean).sort();
  if (dates.length) $("#updated").textContent = "Updated " + new Date(dates.at(-1)).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  const week = D.schedule?.data?.[0]?.week;
  if (week) $("#season-label").textContent = week;
}

// ---------- shared bits ----------
function teamCell(team, rank) {
  const gt = memberTeams.get(team);
  return `${rank ? `<span class="rank">${rank}</span>` : ""}<span class="team">${esc(team)}</span>${gt ? `<span class="tag">${esc(gt)}</span>` : ""}`;
}
const isMember = (team) => memberTeams.has(team);
const head = (title, sub) => `<div class="page-head"><div><h1>${title}</h1>${sub ? `<p>${sub}</p>` : ""}</div></div>`;
const none = (what) => `${head(what)}<p class="empty">No ${what.toLowerCase()} data published yet.</p>`;

function chips(items, current, attr) {
  return `<div class="chips" role="tablist">${items.map((it, i) =>
    `<button class="chip${i === current ? " on" : ""}" data-${attr}="${i}" role="tab" aria-selected="${i === current}">${esc(it)}</button>`).join("")}</div>`;
}

// Sortable table: cols = [{key, label, left, sticky, render}], rows = objects
function table(cols, rows, { sortKey, desc = true, rowClass } = {}) {
  if (sortKey) {
    rows = [...rows].sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      const nx = typeof x === "number", ny = typeof y === "number";
      const c = nx && ny ? x - y : nx ? 1 : ny ? -1 : String(x ?? "").localeCompare(String(y ?? ""));
      return desc ? -c : c;
    });
  }
  // JSON drops trailing zeros (5.0 -> 5): show each column with its own decimal places.
  const places = {};
  for (const c of cols) {
    places[c.key] = Math.max(0, ...rows.map((r) => (typeof r[c.key] === "number" ? (String(r[c.key]).split(".")[1] || "").length : 0)));
  }
  const cell = (r, c, i) => c.render ? c.render(r, i)
    : typeof r[c.key] === "number" && places[c.key] ? r[c.key].toFixed(places[c.key]) : fmt(r[c.key]);
  const th = cols.map((c) => `<th class="${c.left ? "l" : ""} ${c.sticky ? "sticky-col" : ""} ${c.sort === false ? "" : "sortable"} ${c.key === sortKey ? "sorted" + (desc ? "" : " asc") : ""}" data-key="${esc(c.key)}">${esc(c.label ?? c.key)}</th>`).join("");
  const tr = rows.map((r, i) => `<tr class="${rowClass ? rowClass(r) : ""}">${cols.map((c) =>
    `<td class="${c.left ? "l" : ""} ${c.sticky ? "sticky-col" : ""} ${c.cls || ""}">${cell(r, c, i)}</td>`).join("")}</tr>`).join("");
  return `<div class="table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
}

function bindSort(el, state, rerender) {
  el.querySelectorAll("th.sortable").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.key;
    state.desc = state.sortKey === k ? !state.desc : true;
    state.sortKey = k;
    rerender();
  }));
}

function gameCard(g) {
  const f = g.final;
  const member = isMember(g.away) || isMember(g.home);
  let awayScore = "", homeScore = "", awayLost = false, homeLost = false;
  if (f) {
    // Final shows abbreviations ("ORE 88, FCSE 3"): the winner is listed first.
    const aw = awayWon(g);
    awayScore = aw ? f.winner_score : f.loser_score;
    homeScore = aw ? f.loser_score : f.winner_score;
    awayLost = !aw; homeLost = aw;
  }
  return `<div class="game${member ? " member" : ""}">
    <div class="game-row${awayLost ? " loser" : ""}"><span>${teamCell(g.away, g.away_rank)}</span><span class="score">${awayScore}</span></div>
    <div class="game-row${homeLost ? " loser" : ""}"><span><span class="muted">${g.neutral ? "vs" : "@"}</span> ${teamCell(g.home, g.home_rank)}</span><span class="score">${homeScore}</span></div>
    <div class="game-meta"><span>${esc(g.date || "")}</span>${f ? `<span class="final">Final</span>` : `<span>${esc(g.time || "")}</span>`}</div>
  </div>`;
}
// Does a scoreboard abbreviation ("SCAR", "TOL", "FCSMW") stand for this team? Same first
// letter, and its letters appear in order in the name.
function abbrevMatches(abbr, team) {
  const a = abbr.replace(/[^A-Z]/g, ""), t = team.toUpperCase().replace(/[^A-Z]/g, "");
  if (!a || a[0] !== t[0]) return false;
  let i = 0;
  for (const ch of t) if (ch === a[i]) i++;
  return i === a.length;
}
// Which side of a finished game won: true = away team.
function awayWon(g) {
  const a = abbrevMatches(g.final.winner, g.away), h = abbrevMatches(g.final.winner, g.home);
  return a !== h ? a : abbrevMatches(g.final.loser, g.home);
}

// ---------- views ----------
const views = {
  "": home,
  scores,
  top25,
  standings,
  stats,
  awards,
  members,
};

function home(el) {
  const sched = D.schedule?.data?.[0];
  const poll = D.top25?.data?.[0];
  const mem = D.members?.data?.[0]?.rows || [];
  const passing = D.season_stats?.data?.find((c) => c.category === "PASSING");
  const rushing = D.season_stats?.data?.find((c) => c.category === "RUSHING");
  const memberGames = (sched?.games || []).filter((g) => isMember(g.away) || isMember(g.home));
  const leaders = (cat, key, label) => cat ? `<div class="panel"><div class="panel-head"><h2>${label}</h2><a href="#/stats">All stats →</a></div>
    <ol class="leader-list">${[...cat.rows].sort((a, b) => (b[key] ?? 0) - (a[key] ?? 0)).slice(0, 5).map((r) =>
      `<li><span><span class="pos">${esc(r.POS)}</span>${esc(r.NAME)}</span><span class="val">${fmt(r[key])}</span></li>`).join("")}</ol></div>` : "";
  el.innerHTML = `
    ${head("L2G Dynasty", sched ? `${esc(sched.week)} · ${mem.length} coaches` : "")}
    <div class="grid grid-2">
      ${memberGames.length ? `<div class="panel"><div class="panel-head"><h2>League games this week</h2><a href="#/scores">All scores →</a></div>
        <div class="card-list">${memberGames.map(gameCard).join("")}</div></div>` : ""}
      ${poll ? `<div class="panel"><div class="panel-head"><h2>Top 10</h2><a href="#/top25">Full poll →</a></div>
        ${table([{ key: "rank", label: "#", cls: "num" }, { key: "team", label: "Team", left: true, render: (r) => teamCell(r.team) }, { key: "record", label: "W-L" }],
          poll.rows.slice(0, 10), { rowClass: (r) => (isMember(r.team) ? "member" : "") })}</div>` : ""}
      ${leaders(passing, "YARDS", "Passing leaders")}
      ${leaders(rushing, "YARDS", "Rushing leaders")}
    </div>`;
}

function scores(el) {
  const s = D.schedule?.data?.[0];
  if (!s) return (el.innerHTML = none("Scores"));
  const state = { filter: "all" };
  const draw = () => {
    let games = s.games;
    if (state.filter === "league") games = games.filter((g) => isMember(g.away) || isMember(g.home));
    if (state.filter === "ranked") games = games.filter((g) => g.away_rank || g.home_rank);
    el.innerHTML = `${head("Scores & Schedule", `${esc(s.week)} · ${esc(s.scope)} · ${games.length} games`)}
      ${chips(["All games", "League games", "Ranked"], ["all", "league", "ranked"].indexOf(state.filter), "f")}
      <div class="games">${games.map(gameCard).join("") || `<p class="empty">No games.</p>`}</div>`;
    el.querySelectorAll("[data-f]").forEach((b) => b.addEventListener("click", () => { state.filter = ["all", "league", "ranked"][b.dataset.f]; draw(); }));
  };
  draw();
}

function top25(el) {
  const p = D.top25?.data?.[0];
  if (!p) return (el.innerHTML = none("Top 25"));
  const move = (r) => {
    if (r.last_week === "NR") return `<span class="up">NEW</span>`;
    const d = r.last_week - r.rank;
    return d > 0 ? `<span class="up">▲${d}</span>` : d < 0 ? `<span class="down">▼${-d}</span>` : `<span class="muted">–</span>`;
  };
  const resultCell = (t) => {
    if (!t) return "–";
    const m = /^([WL]) (.*)$/.exec(t);
    return m ? `<span class="${m[1] === "W" ? "w" : "l-res"}">${m[1]}</span> ${esc(m[2])}` : esc(t);
  };
  el.innerHTML = `${head("Top 25", `${esc(p.poll || "Media")} poll`)}
    ${table([
      { key: "rank", label: "#", cls: "num", sort: false },
      { key: "move", label: "", sort: false, render: move },
      { key: "team", label: "Team", left: true, sort: false, render: (r) => teamCell(r.team) + (r.first_place_votes ? ` <span class="muted">(${r.first_place_votes})</span>` : "") },
      { key: "record", label: "W-L", sort: false },
      { key: "points", label: "Pts", sort: false },
      { key: "last_game", label: "Last week", left: true, sort: false, render: (r) => resultCell(r.last_game) },
      { key: "next_game", label: "This week", left: true, sort: false },
    ], p.rows, { rowClass: (r) => (isMember(r.team) ? "member" : "") })}`;
}

function standings(el) {
  const parts = D.standings?.data || [];
  if (!parts.length) return (el.innerHTML = none("Standings"));
  // Start on the conference with the most league members.
  const score = (c) => c.rows.filter((r) => isMember(r.team)).length;
  const state = { i: parts.indexOf([...parts].sort((a, b) => score(b) - score(a))[0]) };
  const draw = () => {
    const c = parts[state.i];
    const cols = [
      { key: "pos", label: "#", cls: "num", sort: false, render: (r, i) => i + 1 },
      { key: "team", label: "Team", left: true, sticky: true, sort: false, render: (r) => teamCell(r.team, r.rank) },
      ...["conf", "w-l", "pct", "pf", "pa", "diff", "mov", "home"].filter((k) => k in (c.rows[0] || {}))
        .map((k) => ({ key: k, label: k.toUpperCase(), sort: false,
          render: k === "pct" ? (r) => (typeof r.pct === "number" ? r.pct.toFixed(3) : fmt(r.pct)) : null })),
    ];
    el.innerHTML = `${head("Standings", "Conference standings")}
      ${chips(parts.map((p) => p.conference), state.i, "c")}
      ${table(cols, c.rows, { rowClass: (r) => (isMember(r.team) ? "member" : "") })}`;
    el.querySelectorAll("[data-c]").forEach((b) => b.addEventListener("click", () => { state.i = +b.dataset.c; draw(); }));
  };
  draw();
}

function stats(el) {
  const cats = D.season_stats?.data || [];
  if (!cats.length) return (el.innerHTML = none("Stats"));
  const state = { i: 0, sortKey: null, desc: true, q: "" };
  const defaultSort = (c) => (c.columns.includes("YARDS") ? "YARDS" : c.columns.find((k) => !["NAME", "POS", "GP"].includes(k)));
  const draw = () => {
    const c = cats[state.i];
    state.sortKey = state.sortKey && c.columns.includes(state.sortKey) ? state.sortKey : defaultSort(c);
    const q = state.q.toLowerCase();
    const rows = c.rows.filter((r) => !q || r.NAME.toLowerCase().includes(q) || r.POS.toLowerCase() === q);
    const cols = c.columns.map((k) => ({
      key: k, label: k, left: k === "NAME", sticky: k === "NAME",
      render: k === "NAME" ? (r) => `<span class="team">${esc(r.NAME)}</span>` : k === "POS" ? (r) => `<span class="pos">${esc(r.POS)}</span>` : null,
    }));
    el.innerHTML = `${head("Season Stats", `${esc(c.scope.charAt(0) + c.scope.slice(1).toLowerCase())} leaders · ${c.rows.length} players`)}
      ${chips(cats.map((x) => x.category.toLowerCase().replace(/\b\w/g, (m) => m.toUpperCase())), state.i, "cat")}
      <div class="controls" style="margin-bottom:12px"><input type="search" placeholder="Search player or position" value="${esc(state.q)}" aria-label="Search players"></div>
      ${table(cols, rows, { sortKey: state.sortKey, desc: state.desc })}`;
    el.querySelectorAll("[data-cat]").forEach((b) => b.addEventListener("click", () => { state.i = +b.dataset.cat; state.sortKey = null; state.desc = true; draw(); }));
    const input = $("input[type=search]", el);
    input.addEventListener("input", () => { state.q = input.value; const pos = input.selectionStart; draw(); const n = $("input[type=search]", el); n.focus(); n.setSelectionRange(pos, pos); });
    bindSort(el, state, draw);
  };
  draw();
}

function awards(el) {
  const heis = D.heisman_watch?.data?.[0]?.rows || [];
  const potw = D.players_of_week?.data || [];
  if (!heis.length && !potw.length) return (el.innerHTML = none("Awards"));
  const state = { i: 0 };
  const card = (kind, p) => p ? `<div class="player-card"><span class="kind">${kind}</span>
      <span class="name">${esc(p.name)}</span>
      <span class="line">${[p.pos, p.number != null ? "#" + p.number : null].filter(Boolean).map(esc).join(" · ")}${p.game ? " · " + esc(p.game) : ""}</span>
      <span class="stats">${esc(p.stats)}</span></div>` : "";
  const draw = () => {
    const w = potw[state.i];
    el.innerHTML = `${head("Awards")}
      <div class="grid grid-2">
        ${heis.length ? `<div class="panel"><h2>Heisman Watch</h2>
          ${table([{ key: "place", label: "#", cls: "num", sort: false }, { key: "name", label: "Player", left: true, sort: false, render: (r) => `<span class="team">${esc(r.name)}</span>` },
            { key: "pos", label: "Pos", sort: false }, { key: "team", label: "Team", left: true, sort: false, render: (r) => teamCell(r.team, r.team_rank) }, { key: "year", label: "Year", sort: false }],
            heis, { rowClass: (r) => (isMember(r.team) ? "member" : "") })}</div>` : ""}
        ${w ? `<div class="panel"><h2>Players of the Week <span class="muted" style="font-size:14px">${esc(w.week)}</span></h2>
          <select aria-label="Conference">${potw.map((p, i) => `<option value="${i}" ${i === state.i ? "selected" : ""}>${esc(p.scope)}</option>`).join("")}</select>
          <div class="card-list" style="margin-top:12px">${card("Offensive", w.offensive)}${card("Defensive", w.defensive)}</div></div>` : ""}
      </div>`;
    const sel = $("select", el);
    if (sel) sel.addEventListener("change", () => { state.i = +sel.value; draw(); });
  };
  draw();
}

function members(el) {
  const rows = D.members?.data?.[0]?.rows || [];
  if (!rows.length) return (el.innerHTML = none("Members"));
  const poll = new Map((D.top25?.data?.[0]?.rows || []).map((r) => [r.team, r]));
  const conf = new Map();
  (D.standings?.data || []).forEach((c) => c.rows.forEach((r) => conf.set(r.team, { conf: c.conference, record: r["w-l"] })));
  const sorted = [...rows].sort((a, b) => (a.team_rank || 99) - (b.team_rank || 99));
  el.innerHTML = `${head("Members", `${rows.length} coaches in the dynasty`)}
    <div class="grid grid-3">${sorted.map((m) => {
      const [done, total] = (m.progress || "").split("/").map(Number);
      const c = conf.get(m.team) || {};
      return `<div class="member-card">
        <span class="badge">${m.team_rank ? "#" + m.team_rank : "–"}</span>
        <div class="who">
          <div class="gt">${esc(m.gamertag)}</div>
          <div class="sub">${esc(m.team || "Unknown team")}${c.conf ? " · " + esc(c.conf) : ""}${(poll.get(m.team)?.record || c.record) ? " · " + esc(poll.get(m.team)?.record || c.record) : ""}</div>
          <div class="sub">${memberGame(m)}</div>
          ${total ? `<div class="bar" title="${esc(m.progress)}"><i style="width:${Math.min(100, (100 * done) / total)}%"></i></div>` : ""}
        </div></div>`;
    }).join("")}</div>`;
}

// A member's game this week, from the schedule (cleaner than the card's own text).
function memberGame(m) {
  const g = (D.schedule?.data?.[0]?.games || []).find((x) => x.away === m.team || x.home === m.team);
  if (!g) return m.game ? "This week: " + esc(m.game) : "Bye week";
  const home = g.home === m.team;
  const opp = home ? g.away : g.home;
  const oppRank = home ? g.away_rank : g.home_rank;
  const where = `${home ? (g.neutral ? "vs" : "vs") : "at"} ${oppRank ? oppRank + " " : ""}${esc(opp)}`;
  if (!g.final) {
    // The card can show a result the schedule frame didn't ("W 41-14 at Baylor").
    const played = /^([WL])\b/.exec(m.game || "");
    if (played) return `<span class="${played[1] === "W" ? "w" : "l-res"}">${played[1]}</span> ${where}`;
    return `Next: ${where}${g.time ? " · " + esc(g.time) : ""}`;
  }
  const won = awayWon(g) !== home;
  const score = won ? `${g.final.winner_score}-${g.final.loser_score}` : `${g.final.loser_score}-${g.final.winner_score}`;
  return `<span class="${won ? "w" : "l-res"}">${won ? "W" : "L"}</span> ${score} ${where}`;
}

// ---------- routing ----------
function route() {
  const name = location.hash.replace(/^#\/?/, "").split("/")[0];
  const view = views[name] || home;
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#/" + name));
  $("#nav").classList.remove("open");
  $(".menu-btn").setAttribute("aria-expanded", "false");
  view($("#view"));
  window.scrollTo(0, 0);
}

$(".menu-btn").addEventListener("click", (e) => {
  const open = $("#nav").classList.toggle("open");
  e.currentTarget.setAttribute("aria-expanded", String(open));
});
window.addEventListener("hashchange", route);
load().then(route);
