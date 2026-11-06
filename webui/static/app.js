"use strict";

// 서버(kdump-webui.py)의 API_LEVEL과 같아야 합니다. 다르면 업데이트 뒤 서버를 다시 시작하지 않은 것입니다.
const API_LEVEL = 6;

// ---------------------------------------------------------------- 상태와 공통

const state = {
  version: "",
  settings: {},
  servers: [],
  page: "server",       // server | history | versions
  versions: null,       // { local, latest } 노트북 버전과 GitHub 최신
  serverVersions: {},   // 서버 이름 -> 설치된 analyze-kdump 버전
  selected: null,       // 서버 이름
  tab: "vmcores",       // vmcores | results
  view: null,           // { server, name } 결과 파일 보기
  historyFilter: { server: "", text: "", kind: "all" },
  health: {},           // 서버 이름 -> 연결 테스트 결과
  jobs: new Map(),      // 작업 id -> 작업
  apiMismatch: false,   // 화면과 서버의 API 판이 다름(서버 재시작 필요)
  supervised: false,    // 서버가 감시 프로세스 아래에서 실행 중(화면에서 다시 시작 가능)
  startedAt: null,      // 서버 프로세스 시작 시각(다시 시작 확인용)
  vmcores: {},          // 서버 이름 -> 목록 캐시
  vmcoreRecords: {},    // 서버 이름 -> { vmcore 경로: 기록 요약 }
  prepare: {},          // 서버 이름 -> 서버 준비 점검 결과
  vmcoreSelection: {},  // 서버 이름 -> 선택한 vmcore 경로(Set)
};

const $ = (sel, root = document) => root.querySelector(sel);
const PROVIDER_LABEL = {
  openai: "OpenAI", gemini: "Gemini", claude: "Claude API",
  "claude-code": "Claude Code (구독)", codex: "Codex (구독)",
};
const METHOD_LABEL = { auto: "자동 선택", installed: "원격 설치본", upload: "무설치 실행" };

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch (_) { /* 비어 있는 응답 */ }
  if (!res.ok) {
    if (res.status === 404 && path.startsWith("/api/") && state.apiMismatch) {
      throw new Error("웹 UI 서버가 이전 버전으로 실행 중이라 이 기능을 쓸 수 없습니다. 웹 UI를 다시 시작해 주세요.");
    }
    throw new Error(data.error || `요청 실패 (${res.status})`);
  }
  return data;
}

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function h(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function fmtSize(bytes) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0, n = bytes;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(1) : n) + units[i];
}

function fmtTime(sec) {
  const d = new Date(sec * 1000);
  const p = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function fmtElapsed(sec) {
  return sec >= 60 ? `${Math.floor(sec / 60)}분 ${sec % 60}초` : `${sec}초`;
}

let toastTimer;
function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}

// ---------------------------------------------------------------- 마크다운 (LLM 분석 표시용 최소 구현)

function mdInline(text) {
  let s = esc(text);
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return s;
}

function markdown(src) {
  const lines = src.replace(/\r/g, "").split("\n");
  const out = [];
  let i = 0;
  const isTableSep = l => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
  const cells = l => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(c => c.trim());

  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`);
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      out.push(`<h${level}>${mdInline(heading[2])}</h${level}>`);
      i++;
      continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { out.push("<hr>"); i++; continue; }
    if (line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
      out.push("<table><thead><tr>" + head.map(c => `<th>${mdInline(c)}</th>`).join("") + "</tr></thead><tbody>" +
        rows.map(r => "<tr>" + r.map(c => `<td>${mdInline(c)}</td>`).join("") + "</tr>").join("") + "</tbody></table>");
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""));
        i++;
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
          items[items.length - 1] += " " + lines[i].trim();
          i++;
        }
      }
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>` + items.map(t => `<li>${mdInline(t)}</li>`).join("") + `</${tag}>`);
      continue;
    }
    if (/^>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote>${mdInline(buf.join(" "))}</blockquote>`);
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const buf = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|>\s?|\s*([-*]|\d+\.)\s+)/.test(lines[i]) &&
      !(lines[i].includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1]))) buf.push(lines[i++]);
    out.push(`<p>${buf.map(mdInline).join("<br>")}</p>`);
  }
  return out.join("\n");
}

// ---------------------------------------------------------------- 사이드바

function renderSidebar() {
  const list = $("#server-list");
  list.innerHTML = "";
  if (!state.servers.length) {
    list.append(h('<li class="muted" style="padding:8px 10px;font-size:13px">등록된 서버가 없습니다.</li>'));
  }
  $("#nav-history").classList.toggle("active", state.page === "history");
  $("#nav-versions").classList.toggle("active", state.page === "versions");
  for (const s of state.servers) {
    const health = state.health[s.name];
    const dot = health ? (health.ok ? "ok" : "err") : "";
    const item = h(`<li class="server-item ${state.page === "server" && state.selected === s.name ? "active" : ""}">
      <span class="dot ${dot}"></span>
      <div style="min-width:0"><div class="name">${esc(s.name)}</div><div class="sub">${esc(s.target)}</div></div>
    </li>`);
    item.addEventListener("click", () => selectServer(s.name));
    list.append(item);
  }
  const chip = $("#llm-chip");
  const model = state.settings.model ? ` · ${state.settings.model}` : "";
  chip.textContent = (PROVIDER_LABEL[state.settings.provider] || "LLM") + model;
}

function selectServer(name) {
  state.page = "server";
  state.selected = name;
  state.view = null;
  renderSidebar();
  renderMain();
}

function openHistory() {
  state.page = "history";
  state.view = null;
  renderSidebar();
  renderMain();
}

// 결과 파일을 엽니다. 분석 기록 화면에서 열면 돌아갈 때도 기록 화면으로 갑니다.
function openFile(server, name) {
  if (state.page === "server") state.selected = server;
  state.view = { server, name };
  renderSidebar();
  renderMain();
  window.scrollTo(0, 0);
}

// ---------------------------------------------------------------- 주소(#)와 뒤로 가기
// 화면을 바꿀 때마다 주소 끝에 #/... 위치를 남겨서, 브라우저의 뒤로·앞으로 가기와 새로고침이
// 웹 UI 안의 이전 화면으로 동작하게 합니다.
//   #/history  #/history/file/<서버>/<파일>  #/versions
//   #/server/<서버>/vmcores  #/server/<서버>/results  #/server/<서버>/file/<파일>

let restoringRoute = false;

function routeOf() {
  const e = encodeURIComponent;
  if (state.page === "versions") return "#/versions";
  if (state.page === "history") {
    return state.view ? `#/history/file/${e(state.view.server)}/${e(state.view.name)}` : "#/history";
  }
  if (!state.selected) return "#/";
  if (state.view) return `#/server/${e(state.selected)}/file/${e(state.view.name)}`;
  return `#/server/${e(state.selected)}/${state.tab}`;
}

function applyRoute(hash) {
  const parts = (hash || "").replace(/^#\/?/, "").split("/").map(p => {
    try { return decodeURIComponent(p); } catch (_) { return ""; }
  });
  state.view = null;
  if (parts[0] === "versions") {
    state.page = "versions";
  } else if (parts[0] === "history") {
    state.page = "history";
    if (parts[1] === "file" && parts[2] && parts[3]) state.view = { server: parts[2], name: parts[3] };
  } else if (parts[0] === "server" && state.servers.some(s => s.name === parts[1])) {
    state.page = "server";
    state.selected = parts[1];
    if (parts[2] === "file" && parts[3]) state.view = { server: parts[1], name: parts[3] };
    else if (["results", "vmcores", "prepare"].includes(parts[2])) state.tab = parts[2];
  } else {
    state.page = "server";
  }
}

// 화면이 바뀌었으면 방문 기록을 하나 남깁니다. 뒤로 가기로 되돌아온 경우에는 남기지 않습니다.
function syncRoute() {
  const route = routeOf();
  if (route === location.hash || (route === "#/" && !location.hash)) return;
  if (restoringRoute) history.replaceState(null, "", route);
  else history.pushState(null, "", route);
}

window.addEventListener("popstate", () => {
  restoringRoute = true;
  try {
    applyRoute(location.hash);
    renderSidebar();
    renderMain();
  } finally {
    restoringRoute = false;
  }
});

// ---------------------------------------------------------------- 메인 화면

function renderMain() {
  syncRoute();
  const main = $("#main");
  main.innerHTML = "";
  if (state.page === "versions") return renderVersions(main);
  if (state.page === "history") {
    if (state.view) return renderViewer(main, state.view.server);
    return renderHistory(main);
  }
  if (!state.servers.length) {
    main.append(h(`<div class="card empty">
      <h2>kdump-analyzer 웹 UI</h2>
      <p>분석할 서버를 등록하면 vmcore 목록을 보고, 리포트 생성과 LLM 원인 분석을 브라우저에서 진행할 수 있습니다.</p>
      <ol class="steps">
        <li>왼쪽의 <b>+ 추가</b>로 서버를 등록합니다 (SSH 키로 비밀번호 없이 접속).</li>
        <li><b>연결 테스트</b>로 analyze-kdump·crash·vmcore를 확인합니다.</li>
        <li>상단의 <b>설정</b>에서 LLM(API 키 또는 Claude Code·Codex 구독)을 지정합니다.</li>
        <li>vmcore를 골라 <b>리포트 + LLM 분석</b>을 실행합니다.</li>
      </ol>
      <p style="margin-top:20px"><button class="btn primary" id="empty-add">서버 추가</button></p>
    </div>`));
    $("#empty-add").addEventListener("click", () => openServerDialog());
    return;
  }
  if (!state.selected) {
    main.append(h('<div class="card empty"><h2>서버를 선택하세요</h2><p>왼쪽 목록에서 분석할 서버를 고릅니다.</p></div>'));
    return;
  }
  const server = state.servers.find(s => s.name === state.selected);
  if (!server) { state.selected = null; return renderMain(); }

  const health = state.health[server.name];
  const healthText = health
    ? (health.ok
      ? `연결 OK · ${esc(health.host || "")} · ${esc(health.tool || "analyze-kdump 없음")} · ${esc(health.crash || "crash 없음")} · vmcore ${esc(health.vmcores || 0)}개`
      : `연결 실패: ${esc((health.raw || "").split("\n").pop())}`)
    : "연결 테스트를 아직 하지 않았습니다.";

  const card = h(`<div class="card">
    <div class="card-head">
      <div>
        <h2>${esc(server.name)}</h2>
        <div class="meta">
          <span>${esc(server.target)}:${esc(server.port)}</span>
          <span>분석 방식: ${esc(METHOD_LABEL[server.method] || server.method)}</span>
          <span>${server.sudo ? "sudo 사용" : "sudo 사용 안 함"}</span>
        </div>
        <div class="meta" id="health-line">${healthText}</div>
      </div>
      <div class="actions">
        <button class="btn small" id="srv-test">연결 테스트</button>
        <button class="btn small" id="srv-edit">수정</button>
        <button class="btn small danger" id="srv-del">삭제</button>
      </div>
    </div>
  </div>`);
  main.append(card);
  $("#srv-test").addEventListener("click", () => testServer(server.name));
  $("#srv-edit").addEventListener("click", () => openServerDialog(server));
  $("#srv-del").addEventListener("click", () => deleteServer(server.name));

  if (state.view) return renderViewer(main, server.name);

  const panel = h(`<div class="card">
    <div class="tabs">
      <button class="tab ${state.tab === "vmcores" ? "active" : ""}" data-tab="vmcores">vmcore</button>
      <button class="tab ${state.tab === "results" ? "active" : ""}" data-tab="results">분석 결과</button>
      <button class="tab ${state.tab === "prepare" ? "active" : ""}" data-tab="prepare">서버 준비</button>
    </div>
    <div id="tab-body"></div>
  </div>`);
  main.append(panel);
  panel.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => { state.tab = b.dataset.tab; renderMain(); }));
  if (state.tab === "vmcores") renderVmcores(server);
  else if (state.tab === "prepare") renderPrepare(server);
  else renderResults(server);
}

async function renderVmcores(server, refresh = false) {
  const body = $("#tab-body");
  if (!state.vmcores[server.name] || refresh) {
    body.innerHTML = '<p class="muted"><span class="spinner"></span> 원격 서버에서 vmcore 목록을 읽는 중...</p>';
    try {
      const [list, hist] = await Promise.all([
        api("GET", `/api/servers/${encodeURIComponent(server.name)}/vmcores`),
        api("GET", `/api/history?server=${encodeURIComponent(server.name)}`),
      ]);
      state.vmcores[server.name] = list.vmcores;
      state.vmcoreRecords[server.name] = recordsByVmcore(hist.records);
    } catch (e) {
      body.innerHTML = `<p class="form-error">${esc(e.message)}</p>`;
      return;
    }
  }
  if (state.page !== "server" || state.selected !== server.name || state.tab !== "vmcores" || state.view) return;
  const items = state.vmcores[server.name];
  const records = state.vmcoreRecords[server.name] || {};
  const selected = state.vmcoreSelection[server.name] || (state.vmcoreSelection[server.name] = new Set());
  for (const path of [...selected]) if (!items.some(v => v.path === path)) selected.delete(path);

  const wrap = h(`<div>
    <div class="viewer-head"><span class="muted">${esc(server.crash_dir)} · ${items.length}개</span>
      <button class="btn small" id="vm-refresh">새로고침</button></div>
    <div class="batch-bar" id="batch-bar"></div>
  </div>`);
  if (!items.length) {
    wrap.append(h('<p class="muted">vmcore가 없습니다. (찾는 파일: &lt;디렉터리&gt;/vmcore, Ubuntu·Debian은 &lt;시각&gt;/dump.&lt;시각&gt;)</p>'));
  } else {
    const table = h(`<table class="list"><thead><tr>
      <th style="width:28px"><input type="checkbox" id="vm-all" title="모두 선택"></th>
      <th>시각</th><th>크기</th><th>경로</th><th>기록</th><th></th></tr></thead><tbody></tbody></table>`);
    for (const v of items) {
      const rec = records[v.path];
      const badge = !rec ? '<span class="muted">—</span>'
        : rec.analyses
          ? `<button class="tag analysis linkish-tag" data-open="analysis" title="최근 분석 열기">분석 ${rec.analyses}건</button>`
          : '<button class="tag linkish-tag" data-open="report" title="최근 리포트 열기">리포트만</button>';
      const row = h(`<tr class="${selected.has(v.path) ? "selected" : ""}">
        <td><input type="checkbox" class="vm-check" ${selected.has(v.path) ? "checked" : ""}></td>
        <td style="white-space:nowrap">${fmtTime(v.mtime)}</td>
        <td>${fmtSize(v.size)}</td>
        <td class="path vm-path" title="${esc(v.path)}">${esc(v.path.startsWith(server.crash_dir.replace(/\/+$/, "") + "/") ? v.path.slice(server.crash_dir.replace(/\/+$/, "").length + 1) : v.path)}</td>
        <td style="white-space:nowrap">${badge}</td>
        <td style="white-space:nowrap;text-align:right">
          <button class="btn small" data-kind="report" title="crash 리포트만 만듭니다">리포트</button>
          <button class="btn small primary" data-kind="llm" title="crash 리포트를 만든 뒤 LLM으로 분석합니다">+ LLM</button>
        </td></tr>`);
      row.querySelector(".vm-check").addEventListener("change", e => {
        if (e.target.checked) selected.add(v.path); else selected.delete(v.path);
        row.classList.toggle("selected", e.target.checked);
        drawBatchBar(server, items);
      });
      row.querySelectorAll("[data-kind]").forEach(b => b.addEventListener("click", () =>
        startJob({ kind: b.dataset.kind, server: server.name, vmcore: v.path })));
      const open = row.querySelector("[data-open]");
      if (open) open.addEventListener("click", () =>
        openFile(server.name, open.dataset.open === "analysis" ? rec.latestAnalysis : rec.latestReport));
      table.tBodies[0].append(row);
    }
    wrap.append(table);
  }
  const body2 = $("#tab-body");
  body2.innerHTML = "";
  body2.append(wrap);
  $("#vm-refresh").addEventListener("click", () => renderVmcores(server, true));
  const all = $("#vm-all");
  if (all) all.addEventListener("change", e => {
    items.forEach(v => e.target.checked ? selected.add(v.path) : selected.delete(v.path));
    renderVmcores(server);
  });
  drawBatchBar(server, items);
}

// vmcore 경로별 기록 요약: 리포트·분석 개수와 가장 최근 파일
function recordsByVmcore(records) {
  const map = {};
  for (const r of records) {
    const path = r.report && r.report.vmcore;
    if (!path) continue;
    const m = map[path] || (map[path] = { reports: 0, analyses: 0, latestReport: null, latestAnalysis: null, reportTime: 0, analysisTime: 0 });
    m.reports++;
    if (r.report.mtime > m.reportTime) { m.reportTime = r.report.mtime; m.latestReport = r.report.name; }
    for (const a of r.analyses) {
      m.analyses++;
      if (a.mtime > m.analysisTime) { m.analysisTime = a.mtime; m.latestAnalysis = a.name; }
    }
  }
  return map;
}

function drawBatchBar(server, items) {
  const bar = $("#batch-bar");
  if (!bar) return;
  const selected = state.vmcoreSelection[server.name] || new Set();
  const records = state.vmcoreRecords[server.name] || {};
  const all = $("#vm-all");
  if (all) {
    all.checked = items.length > 0 && selected.size === items.length;
    all.indeterminate = selected.size > 0 && selected.size < items.length;
  }
  bar.innerHTML = "";
  if (!selected.size) {
    bar.append(h('<span class="muted">여러 개를 한 번에 분석하려면 체크박스로 고르세요. 같은 서버의 작업은 하나씩 차례로 실행됩니다.</span>'));
    return;
  }
  const withReport = [...selected].filter(p => records[p]).length;
  const el = h(`<div class="batch-inner">
    <b>${selected.size}개 선택</b>
    <button class="btn small" data-batch="report">리포트</button>
    <button class="btn small primary" data-batch="llm">리포트 + LLM 분석</button>
    <button class="btn small" data-batch="llm-only" ${withReport ? "" : "disabled"}
      title="crash를 다시 실행하지 않고, vmcore마다 가장 최근 리포트로 LLM 분석만 합니다.">LLM 분석만 (기존 리포트 ${withReport}개)</button>
    <button class="btn small ghost" data-batch="clear">선택 해제</button>
  </div>`);
  el.querySelectorAll("[data-batch]").forEach(b => b.addEventListener("click", () => {
    const kind = b.dataset.batch;
    if (kind === "clear") { selected.clear(); renderVmcores(server); return; }
    startBatch(server, kind, [...selected]);
  }));
  bar.append(el);
}

async function startBatch(server, kind, vmcores) {
  const label = { report: "리포트", llm: "리포트 + LLM 분석", "llm-only": "LLM 분석" }[kind];
  try {
    const r = await api("POST", "/api/jobs/batch", { server: server.name, kind, vmcores });
    for (const job of r.jobs) state.jobs.set(job.id, job);
    renderJobs();
    pollJobs();
    const skipped = r.skipped.length ? ` (기존 리포트가 없어 ${r.skipped.length}개 건너뜀)` : "";
    toast(`${label} ${r.jobs.length}건을 대기열에 넣었습니다${skipped}.`);
    (state.vmcoreSelection[server.name] || new Set()).clear();
    if (state.page === "server" && state.selected === server.name && state.tab === "vmcores" && !state.view) renderVmcores(server);
  } catch (e) {
    toast(e.message);
  }
}

async function renderResults(server) {
  const body = $("#tab-body");
  body.innerHTML = '<p class="muted"><span class="spinner"></span> 불러오는 중...</p>';
  let records;
  try {
    records = (await api("GET", `/api/history?server=${encodeURIComponent(server.name)}`)).records;
  } catch (e) {
    body.innerHTML = `<p class="form-error">${esc(e.message)}</p>`;
    return;
  }
  if (state.page !== "server" || state.selected !== server.name || state.tab !== "results" || state.view) return;
  body.innerHTML = "";
  if (!records.length) {
    body.append(h('<p class="muted">아직 분석 결과가 없습니다. vmcore 탭에서 분석을 실행하세요.</p>'));
    return;
  }
  body.append(recordList(records, false));
}


// ---------------------------------------------------------------- 서버 준비 (kdump 환경 점검·설치)

const PREPARE_STATUS = { ok: ["ok", "정상"], warn: ["warn", "확인 필요"], missing: ["err", "없음"], info: ["muted", "선택"] };
const PREPARE_WARN = {
  crashkernel: "부팅 설정(커널 명령줄)을 바꿉니다. 서버를 재부팅해야 적용됩니다. 재부팅은 직접 하셔야 합니다.",
  debuginfo: "디버그 커널 패키지를 받습니다(수백 MB~1GB). 서버에서 패키지 저장소에 접근할 수 있어야 합니다.",
  kdump: "kdump 패키지를 설치하고 부팅 때 켜지도록 설정합니다.",
  crash: "crash 패키지를 설치합니다.",
  swap: "2GB swap 파일(/swapfile-kdump)을 만들고 /etc/fstab에 등록합니다.",
  tool: "노트북의 analyze-kdump를 서버에 설치합니다.",
};

async function renderPrepare(server, refresh = false) {
  const body = $("#tab-body");
  if (!state.prepare[server.name] || refresh) {
    body.innerHTML = '<p class="muted"><span class="spinner"></span> 서버를 점검하는 중... (바꾸는 것은 없습니다)</p>';
    try {
      state.prepare[server.name] = await api("GET", `/api/servers/${encodeURIComponent(server.name)}/prepare`);
    } catch (e) {
      body.innerHTML = `<p class="form-error">${esc(e.message)}</p>`;
      return;
    }
  }
  if (state.page !== "server" || state.selected !== server.name || state.tab !== "prepare" || state.view) return;
  const r = state.prepare[server.name];
  const running = [...state.jobs.values()].some(j => j.kind === "prepare" && j.server === server.name && isActive(j));
  const wrap = h(`<div>
    <div class="viewer-head">
      <span class="muted">${esc(r.os)} · ${esc(r.family)} · 커널 ${esc(r.kernel || "?")}${r.root ? "" : ' · <span class="warn-text">root 권한 없음(서버 설정의 sudo를 켜야 설치 가능)</span>'}</span>
      <button class="btn small" id="pr-refresh">다시 점검</button>
    </div>
    <table class="list prepare"><thead><tr><th style="width:28px"></th><th>항목</th><th>상태</th><th>내용</th></tr></thead><tbody></tbody></table>
    <div class="batch-bar" id="pr-bar"></div>
  </div>`);
  const tbody = wrap.querySelector("tbody");
  for (const it of r.items) {
    const [cls, text] = PREPARE_STATUS[it.status] || ["", it.status];
    const fixable = it.action && it.status !== "ok";
    const row = h(`<tr>
      <td>${fixable ? `<input type="checkbox" class="pr-check" data-action="${esc(it.action)}" ${it.status === "missing" || it.status === "warn" ? "checked" : ""}>` : ""}</td>
      <td style="white-space:nowrap;font-weight:600">${esc(it.label)}</td>
      <td><span class="pill ${cls}">${esc(text)}</span></td>
      <td>${esc(it.detail)}${it.note ? `<div class="muted" style="font-size:12px">${esc(it.note)}</div>` : ""}</td></tr>`);
    tbody.append(row);
  }
  const body2 = $("#tab-body");
  body2.innerHTML = "";
  body2.append(wrap);
  $("#pr-refresh").addEventListener("click", () => renderPrepare(server, true));

  const bar = $("#pr-bar");
  const draw = () => {
    const picked = [...wrap.querySelectorAll(".pr-check:checked")].map(c => c.dataset.action);
    bar.innerHTML = "";
    if (!wrap.querySelector(".pr-check")) {
      bar.append(h('<span class="muted">설치할 항목이 없습니다. kdump로 vmcore를 저장하고 이 서버에서 분석할 준비가 되어 있습니다.</span>'));
      return;
    }
    const el = h(`<div class="batch-inner"><b>${picked.length}개 선택</b>
      <button class="btn small primary" id="pr-run" ${picked.length && !running && r.root ? "" : "disabled"}>선택 항목 설치</button>
      <span class="muted">${running ? "준비 작업이 진행 중입니다." : "점검은 서버를 바꾸지 않습니다. 설치는 확인을 거친 뒤 실행합니다."}</span></div>`);
    el.querySelector("#pr-run").addEventListener("click", () => runPrepare(server, picked));
    bar.append(el);
  };
  wrap.querySelectorAll(".pr-check").forEach(c => c.addEventListener("change", draw));
  draw();
}

async function runPrepare(server, actions) {
  const lines = actions.map(a => `• ${PREPARE_WARN[a] || a}`).join("\n");
  const reboot = actions.includes("crashkernel") || actions.includes("kdump")
    ? "\n\n설치 뒤 서버를 재부팅해야 kdump가 동작합니다. 운영 서버라면 점검 시간에 진행하세요." : "";
  if (!confirm(`${server.name}에서 다음을 실행할까요?\n\n${lines}${reboot}`)) return;
  const job = await startJob({ kind: "prepare", server: server.name, actions });
  if (job) renderPrepare(server);
}

// ---------------------------------------------------------------- 분석 기록

// 기록 하나 = 리포트 한 건 + 그 리포트로 만든 LLM 분석들(최신 순)
function recordList(records, showServer) {
  const list = h('<div class="records"></div>');
  for (const r of records) {
    const latest = r.analyses[0];
    const rep = r.report;
    const known = state.servers.some(s => s.name === r.server);
    const verdict = latest
      ? `<div class="verdict">${esc(latest.verdict || "(판정 문장을 찾지 못했습니다)")}</div>`
      : '<div class="verdict none">LLM 분석 없음 · 리포트만 생성됨</div>';
    const facts = [];
    if (rep && rep.panic) facts.push(`<span class="panic">${esc(rep.panic)}</span>`);
    if (rep && rep.vmcore) facts.push(`<span class="path">${esc(rep.vmcore)}</span>`);
    if (!rep) facts.push('<span>원본 리포트가 없습니다</span>');
    const llm = latest ? `${esc(PROVIDER_LABEL[latest.provider] || latest.provider || "LLM")}${latest.model ? " · " + esc(latest.model) : ""}` : "";
    const item = h(`<div class="record">
      <div class="record-body">
        <div class="record-top">
          ${showServer ? `<span class="tag server${known ? "" : " gone"}" title="${known ? "" : "삭제된 서버"}">${esc(r.server)}</span>` : ""}
          <span>${fmtTime(r.time)}</span>
          ${rep && rep.kernel ? `<span class="muted">${esc(rep.kernel)}</span>` : ""}
        </div>
        ${verdict}
        <div class="record-facts">${facts.join("")}</div>
        ${llm ? `<div class="record-llm">${llm}${r.analyses.length > 1 ? ` · 분석 ${r.analyses.length}건` : ""}</div>` : ""}
        ${r.analyses.length > 1 ? `<div class="record-more">${r.analyses.slice(1).map((a, i) =>
          `<button class="linkish" data-older="${i + 1}">${fmtTime(a.mtime)} ${esc(PROVIDER_LABEL[a.provider] || a.provider || "")}</button>`).join("")}</div>` : ""}
      </div>
      <div class="record-actions">
        ${latest ? '<button class="btn small primary" data-act="analysis">분석 보기</button>' : ""}
        ${rep ? '<button class="btn small" data-act="report">리포트</button>' : ""}
        ${rep && known ? `<button class="btn small" data-act="llm">${latest ? "다시 분석" : "LLM 분석"}</button>` : ""}
      </div>
    </div>`);
    item.querySelectorAll("[data-act]").forEach(b => b.addEventListener("click", e => {
      e.stopPropagation();
      const act = b.dataset.act;
      if (act === "analysis") openFile(r.server, latest.name);
      if (act === "report") openFile(r.server, rep.name);
      if (act === "llm") startJob({ kind: "reanalyze", server: r.server, report: rep.name });
    }));
    item.querySelectorAll("[data-older]").forEach(b => b.addEventListener("click", e => {
      e.stopPropagation();
      openFile(r.server, r.analyses[Number(b.dataset.older)].name);
    }));
    item.addEventListener("click", () => openFile(r.server, latest ? latest.name : rep.name));
    list.append(item);
  }
  return list;
}

async function renderHistory(main) {
  const card = h(`<div class="card">
    <div class="card-head">
      <div><h2>분석 기록</h2><div class="meta">이 노트북에 저장된 리포트와 LLM 분석입니다. 리포트별로 묶어 최신 순으로 보여줍니다.</div></div>
    </div>
    <div class="history-tools">
      <select id="h-server"><option value="">모든 서버</option></select>
      <select id="h-kind">
        <option value="all">전체</option><option value="analysis">LLM 분석 있음</option><option value="report">리포트만</option>
      </select>
      <input id="h-text" placeholder="판정, panic, vmcore, 커널 버전으로 검색">
    </div>
    <div id="h-summary" class="muted history-summary"></div>
    <div id="h-list"><p class="muted"><span class="spinner"></span> 불러오는 중...</p></div>
  </div>`);
  main.append(card);
  let records;
  try {
    records = (await api("GET", "/api/history")).records;
  } catch (e) {
    $("#h-list").innerHTML = `<p class="form-error">${esc(e.message)}</p>`;
    return;
  }
  if (state.page !== "history" || state.view || !card.isConnected) return;

  const f = state.historyFilter;
  const names = [...new Set([...state.servers.map(s => s.name), ...records.map(r => r.server)])];
  const sel = $("#h-server");
  for (const n of names) sel.append(h(`<option value="${esc(n)}">${esc(n)}</option>`));
  sel.value = names.includes(f.server) ? f.server : "";
  $("#h-kind").value = f.kind;
  $("#h-text").value = f.text;

  function draw() {
    const t = f.text.trim().toLowerCase();
    const shown = records.filter(r => {
      if (f.server && r.server !== f.server) return false;
      if (f.kind === "analysis" && !r.analyses.length) return false;
      if (f.kind === "report" && r.analyses.length) return false;
      if (!t) return true;
      const hay = [r.server, ...(r.analyses.map(a => `${a.verdict} ${a.provider} ${a.model}`)),
        r.report ? `${r.report.panic} ${r.report.vmcore} ${r.report.kernel} ${r.report.name}` : ""].join(" ").toLowerCase();
      return hay.includes(t);
    });
    const analyzed = shown.filter(r => r.analyses.length).length;
    $("#h-summary").textContent = records.length
      ? `${shown.length}건 표시 (LLM 분석 ${analyzed}건 · 리포트만 ${shown.length - analyzed}건) / 전체 ${records.length}건`
      : "";
    const holder = $("#h-list");
    holder.innerHTML = "";
    if (!records.length) {
      holder.append(h('<p class="muted">아직 분석 기록이 없습니다. 서버의 vmcore 탭에서 분석을 실행하면 여기에 쌓입니다.</p>'));
    } else if (!shown.length) {
      holder.append(h('<p class="muted">조건에 맞는 기록이 없습니다.</p>'));
    } else {
      holder.append(recordList(shown, true));
    }
  }
  draw();
  sel.addEventListener("change", () => { f.server = sel.value; draw(); });
  $("#h-kind").addEventListener("change", e => { f.kind = e.target.value; draw(); });
  let timer;
  $("#h-text").addEventListener("input", e => { clearTimeout(timer); timer = setTimeout(() => { f.text = e.target.value; draw(); }, 150); });
}


// ---------------------------------------------------------------- 버전·업데이트

function openVersions() {
  state.page = "versions";
  state.view = null;
  renderSidebar();
  renderMain();
}

const short = c => (c || "").slice(0, 7);

// "1.10.0" > "1.9.2" 처럼 숫자 단위로 비교합니다.
function cmpVersion(a, b) {
  const pa = String(a || "").split(/[.-]/).map(n => parseInt(n, 10) || 0);
  const pb = String(b || "").split(/[.-]/).map(n => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) - (pb[i] || 0);
  }
  return 0;
}

function localStatus() {
  const v = state.versions;
  if (!v) return { cls: "", text: "확인 중" };
  const { local, latest } = v;
  if (!latest || !latest.ok) return { cls: "warn", text: "최신 버전 확인 실패" };
  if (local.commit && local.commit === latest.commit) return { cls: "ok", text: "최신 버전 사용 중" };
  if (local.commit) {
    if (latest.ahead === 0) return { cls: "ok", text: "최신보다 앞선 버전 (개발 중)" };
    return { cls: "up", text: latest.ahead ? `업데이트 가능 · 커밋 ${latest.ahead}개` : "업데이트 가능" };
  }
  return cmpVersion(latest.version, local.version) > 0
    ? { cls: "up", text: "업데이트 가능" } : { cls: "ok", text: "최신 버전과 같은 번호" };
}

// "릴리스 v1.16.0" 또는 "main 브랜치"
function latestTarget(latest) {
  if (!latest || !latest.ok) return "";
  return latest.channel === "release" ? `릴리스 ${latest.tag || ""}` : `${latest.branch || latest.ref || ""} 브랜치`;
}

function selfUpdateLabel() {
  const latest = state.versions && state.versions.latest;
  return latest && latest.ok && latest.channel === "release" ? `업데이트 (${latest.tag})` : "업데이트 (git pull)";
}

function updateAvailable() {
  return localStatus().cls === "up";
}

function serverStatus(info) {
  if (!info) return { cls: "", text: "" };
  if (info.loading) return { cls: "", text: "확인 중" };
  if (!info.ok) return { cls: "err", text: "접속 실패" };
  if (!info.installed) return { cls: "muted", text: "미설치 · 무설치 실행으로 분석 가능" };
  const v = state.versions || {};
  const latest = v.latest && v.latest.ok ? v.latest : null;
  const local = v.local || {};
  if (info.commit && latest && latest.commit.startsWith(info.commit)) return { cls: "ok", text: "최신 버전" };
  if (info.commit && local.commit && local.commit.startsWith(info.commit)) return { cls: "ok", text: "노트북과 같은 버전" };
  const newest = [latest && latest.version, local.version].filter(Boolean).sort(cmpVersion).pop();
  if (newest && cmpVersion(newest, info.version) > 0) return { cls: "up", text: `업데이트 가능 → v${newest}` };
  if (info.commit && latest) return { cls: "up", text: "다른 커밋 · 다시 설치 가능" };
  return { cls: "ok", text: "확인됨" };
}

function renderVersionBadge() {
  const badge = $("#version");
  const up = updateAvailable();
  badge.textContent = "v" + state.version + (up ? ` → v${state.versions.latest.version}` : "");
  badge.classList.toggle("up", up);
  $("#nav-update-dot").hidden = !up;
}

async function loadVersions(check = false) {
  try {
    state.versions = await api("GET", "/api/versions" + (check ? "?check=1" : ""));
  } catch (e) {
    state.versions = { local: { version: state.version }, latest: { ok: false, error: e.message } };
  }
  renderVersionBadge();
}

async function loadServerVersion(name) {
  state.serverVersions[name] = { loading: true };
  if (state.page === "versions" && !state.view) drawServerVersions();
  try {
    state.serverVersions[name] = await api("GET", `/api/servers/${encodeURIComponent(name)}/version`);
  } catch (e) {
    state.serverVersions[name] = { ok: false, error: e.message };
  }
  if (state.page === "versions" && !state.view) drawServerVersions();
}

function renderVersions(main) {
  const v = state.versions;
  const local = (v && v.local) || { version: state.version };
  const latest = v && v.latest;
  const st = localStatus();
  const checked = latest && latest.checked ? fmtTime(latest.checked) : "";
  const repo = state.settings.update_repo || "621dev/kdump-analyzer";
  const branch = state.settings.update_branch || "main";
  const channel = state.settings.update_channel || "release";
  const target = latestTarget(latest);

  const card = h(`<div class="card">
    <div class="card-head">
      <div>
        <h2>이 노트북의 kdump-analyzer</h2>
        <div class="meta">웹 UI와, 서버에 '무설치 실행'·'노트북 버전 설치'로 보내는 스크립트의 버전입니다.</div>
      </div>
      <div class="actions" id="ver-actions"><button class="btn small" id="ver-check">최신 버전 확인</button></div>
    </div>
    <div class="version-grid">
      <div class="version-box">
        <div class="label">현재</div>
        <div class="value">v${esc(local.version)}</div>
        <div class="sub">${local.git ? `${esc(short(local.commit))} · 브랜치 ${esc(local.branch)}${local.dirty ? ' · <span class="warn-text">커밋하지 않은 변경 있음</span>' : ""}` : "git 저장소가 아님 (커밋 정보 없음)"}</div>
      </div>
      <div class="version-box">
        <div class="label">최신 (GitHub ${channel === "release" ? "릴리스" : "브랜치"})</div>
        <div class="value">${latest && latest.ok ? "v" + esc(latest.version) : "—"}</div>
        <div class="sub">${latest && latest.ok ? `${latest.release_url ? `<a href="${esc(latest.release_url)}" target="_blank" rel="noopener noreferrer">${esc(target)}</a>` : esc(target)} · ${esc(short(latest.commit))} · ${esc(repo)}${checked ? " · " + checked + " 확인" : ""}` : esc((latest && latest.error) || "확인 중")}</div>
      </div>
      <div class="version-box">
        <div class="label">상태</div>
        <div class="value"><span class="pill ${st.cls}">${esc(st.text)}</span></div>
        <div class="sub" id="ver-action"></div>
      </div>
    </div>
    <div id="ver-changes"></div>
    <div id="ver-result"></div>
    <details class="ver-source"><summary>업데이트 설정 (${channel === "release" ? "최신 릴리스" : esc(branch) + " 브랜치 최신 커밋"})</summary>
      <div class="inline-actions" style="margin-top:8px">
        <label style="width:220px">업데이트 기준<select id="ver-channel">
          <option value="release"${channel === "release" ? " selected" : ""}>최신 릴리스 (권장)</option>
          <option value="branch"${channel === "branch" ? " selected" : ""}>브랜치 최신 커밋</option>
        </select></label>
        <label style="flex:1">저장소 (owner/repo)<input id="ver-repo" value="${esc(repo)}"></label>
        <label style="width:180px">브랜치<input id="ver-branch" value="${esc(branch)}"></label>
        <button class="btn small" id="ver-save" style="align-self:flex-end">저장</button>
      </div>
      <p class="muted" style="margin:6px 0 0">최신 릴리스는 검증을 마친 버전만 받습니다. 브랜치 최신 커밋은 릴리스 전 변경까지 바로 받습니다.
        노트북 저장소는 어느 쪽이든 브랜치(${esc(branch)})에서 fast-forward로만 갱신합니다.</p>
    </details>
  </div>`);
  main.append(card);

  if (state.supervised) {
    const btn = restartButton();
    btn.classList.remove("primary");
    btn.title = "웹 UI 서버를 디스크에 있는 코드로 다시 실행합니다";
    $("#ver-actions").append(btn);
  }
  const stop = h('<button class="btn small danger" title="웹 UI 서버를 끕니다. 다시 쓰려면 바탕화면 아이콘이나 콘솔에서 다시 실행하세요.">웹 UI 종료</button>');
  stop.addEventListener("click", () => shutdownWebui());
  $("#ver-actions").append(stop);
  const action = $("#ver-action");
  if (st.cls === "up" && local.git) {
    const btn = h(`<button class="btn small primary">${esc(selfUpdateLabel())}</button>`);
    btn.addEventListener("click", () => selfUpdate(btn));
    action.append(btn);
  } else if (st.cls === "up") {
    action.append(h(`<span>git으로 받은 저장소가 아니어서 자동 업데이트를 할 수 없습니다. <a href="https://github.com/${esc(repo)}" target="_blank" rel="noopener noreferrer">GitHub</a>에서 새로 받아 주세요.</span>`));
  }
  if (latest && latest.changes && latest.changes.length && st.cls === "up") {
    $("#ver-changes").append(h(`<div class="changes"><div class="label">새 커밋 (최근 순)</div><ul>${latest.changes.map(c =>
      `<li><code>${esc(c.sha)}</code> ${esc(c.title)}</li>`).join("")}</ul></div>`));
  }
  $("#ver-check").addEventListener("click", async e => {
    e.target.disabled = true;
    e.target.innerHTML = '<span class="spinner"></span> 확인 중';
    await loadVersions(true);
    renderMain();
  });
  $("#ver-save").addEventListener("click", async () => {
    try {
      state.settings = await api("POST", "/api/settings", {
        update_channel: $("#ver-channel").value,
        update_repo: $("#ver-repo").value.trim(), update_branch: $("#ver-branch").value.trim() });
      toast("업데이트 설정을 저장했습니다.");
      await loadVersions(true);
      renderMain();
    } catch (e) { toast(e.message); }
  });

  const servers = h(`<div class="card">
    <div class="card-head">
      <div><h2>서버의 analyze-kdump</h2>
        <div class="meta">'원격 설치본 실행'에 쓰는 서버 설치본입니다. 설정·서버 목록·로그·vmlinux는 업그레이드해도 유지됩니다.</div></div>
      <div class="actions"><button class="btn small" id="srv-ver-all">모두 확인</button></div>
    </div>
    <div id="srv-versions"></div>
  </div>`);
  main.append(servers);
  $("#srv-ver-all").addEventListener("click", () => state.servers.forEach(s => loadServerVersion(s.name)));
  drawServerVersions();
  // 처음 들어왔을 때는 아직 확인하지 않은 서버를 한 번씩 확인합니다.
  for (const s of state.servers) if (!state.serverVersions[s.name]) loadServerVersion(s.name);
}

function drawServerVersions() {
  const holder = $("#srv-versions");
  if (!holder) return;
  holder.innerHTML = "";
  if (!state.servers.length) {
    holder.append(h('<p class="muted">등록된 서버가 없습니다.</p>'));
    return;
  }
  const local = (state.versions && state.versions.local) || { version: state.version };
  const latest = state.versions && state.versions.latest;
  const table = h(`<table class="list"><thead><tr><th>서버</th><th>설치 버전</th><th>설치 정보</th><th>상태</th><th></th></tr></thead><tbody></tbody></table>`);
  for (const s of state.servers) {
    const info = state.serverVersions[s.name];
    const st = serverStatus(info);
    const running = [...state.jobs.values()].some(j => j.kind === "upgrade" && j.server === s.name && isActive(j));
    const installed = info && info.ok && info.installed;
    const verb = installed ? "업그레이드" : "설치";
    const row = h(`<tr>
      <td><div style="font-weight:600">${esc(s.name)}</div><div class="muted" style="font-size:12px">${esc(s.target)}</div></td>
      <td style="white-space:nowrap">${info && info.ok && info.installed ? `v${esc(info.version)}${info.commit ? `<div class="muted path">${esc(info.commit)}</div>` : ""}` : (info && info.loading ? '<span class="spinner"></span>' : "—")}</td>
      <td class="muted" style="font-size:12.5px">${info && info.ok && info.installed
        ? `${esc(info.prefix || "")}${info.installed_at ? "<br>" + esc(info.installed_at) : ""}${info.source ? "<br>" + esc(info.source) : ""}`
        : esc((info && info.error) || "")}</td>
      <td><span class="pill ${st.cls}">${esc(st.text)}</span></td>
      <td><div class="row-actions">
        <button class="btn small" data-act="check">확인</button>
        <button class="btn small ${st.cls === "up" ? "primary" : ""}" data-act="local" ${running || !(info && info.ok) ? "disabled" : ""}
          title="노트북의 v${esc(local.version)}를 SSH로 보내 설치합니다. 서버에 인터넷이 없어도 됩니다.">노트북 버전 ${verb}</button>
        <button class="btn small" data-act="github" ${running || !(info && info.ok) ? "disabled" : ""}
          title="서버가 GitHub에서 직접 받아 설치합니다(${esc(latestTarget(latest) || "최신")}). 서버에 인터넷이 필요합니다.">GitHub ${latest && latest.ok && latest.channel === "release" ? esc(latest.tag) : "최신"} ${verb}</button>
      </div></td></tr>`);
    row.querySelector('[data-act="check"]').addEventListener("click", () => loadServerVersion(s.name));
    row.querySelectorAll('[data-act="local"],[data-act="github"]').forEach(b => b.addEventListener("click", () => {
      const source = b.dataset.act;
      const what = source === "local"
        ? `노트북의 v${local.version}${local.commit ? " (" + short(local.commit) + ")" : ""}`
        : `GitHub ${latest && latest.ok ? latestTarget(latest) + " v" + latest.version + " (" + short(latest.commit) + ")" : "최신"}`;
      const now = installed ? `현재 v${info.version}${info.commit ? " (" + info.commit + ")" : ""}` : "현재 미설치";
      if (!confirm(`${s.name}에 ${what}을(를) ${verb}할까요?\n\n${now}\n설치 위치: ${(info && info.prefix) || s.tool}\n\n설정·서버 목록·로그·vmlinux는 유지됩니다.`)) return;
      startJob({ kind: "upgrade", server: s.name, source }).then(() => drawServerVersions());
    }));
    table.tBodies[0].append(row);
  }
  holder.append(table);
}

async function selfUpdate(btn) {
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 업데이트 중';
  try {
    const r = await api("POST", "/api/self-update");
    state.versions = { local: r.local, latest: r.latest };
    state.version = r.local.version;
    renderVersionBadge();
    renderMain();
    const msg = r.restart
      ? (state.supervised ? "웹 UI 서버 코드가 바뀌었습니다. 아래 버튼으로 다시 시작하면 적용됩니다."
        : "웹 UI 서버 코드가 바뀌었습니다. 콘솔에서 Ctrl+C로 끈 뒤 다시 실행해 주세요.")
      : "화면 파일만 바뀌었습니다. 새로고침(Ctrl+F5)하면 적용됩니다.";
    const notice = h(`<div class="notice ok"><b>업데이트를 마쳤습니다: ${esc(short(r.before))} → ${esc(short(r.local.commit))} (v${esc(r.local.version)})</b>
      <div>${r.changed.length ? esc(msg) : "바뀐 파일이 없습니다."}</div>
      ${r.changed.length ? `<details><summary>바뀐 파일 ${r.changed.length}개</summary><pre>${esc(r.changed.join("\n"))}</pre></details>` : ""}</div>`);
    if (r.restart && state.supervised) {
      const row = h('<div style="margin-top:8px"></div>');
      row.append(restartButton("지금 다시 시작"));
      notice.append(row);
    }
    $("#ver-result").append(notice);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = selfUpdateLabel();
    $("#ver-result").innerHTML = "";
    $("#ver-result").append(h(`<div class="notice err"><b>업데이트하지 못했습니다</b><pre>${esc(e.message)}</pre></div>`));
  }
}


// ---------------------------------------------------------------- 웹 UI 다시 시작
// 서버에 다시 시작을 요청한 뒤, 새 서버가 뜰 때까지 기다렸다가 페이지를 새로 엽니다.
// 토큰은 그대로이므로 다시 로그인하지 않아도 됩니다.

function restartButton(label = "웹 UI 다시 시작") {
  const btn = h(`<button class="btn small primary">${esc(label)}</button>`);
  btn.addEventListener("click", () => restartWebui());
  return btn;
}

async function restartWebui() {
  const active = [...state.jobs.values()].filter(isActive).length;
  if (active) {
    toast(`진행 중이거나 대기 중인 작업이 ${active}개 있습니다. 끝난 뒤 다시 시작해 주세요.`);
    return;
  }
  if (!confirm("웹 UI 서버를 다시 시작할까요?\n\n디스크에 있는 최신 코드로 다시 실행하고, 이 페이지는 자동으로 새로 열립니다.")) return;
  const overlay = h(`<div class="overlay"><div class="overlay-box">
    <div><span class="spinner"></span> <b>웹 UI를 다시 시작하는 중...</b></div>
    <div class="muted" id="restart-status">서버에 요청하는 중</div></div></div>`);
  document.body.append(overlay);
  const status = t => { overlay.querySelector("#restart-status").textContent = t; };
  try {
    await api("POST", "/api/restart", {});
  } catch (e) {
    overlay.remove();
    toast(e.message);
    return;
  }
  const before = state.startedAt;
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 1000));
    try {
      const res = await fetch("/api/state");
      if (res.ok) {
        const data = await res.json();
        if (data.started_at && data.started_at !== before) {
          status(`v${data.version}로 다시 시작했습니다. 페이지를 새로 엽니다.`);
          location.reload();
          return;
        }
      }
      status("새 서버를 기다리는 중");
    } catch (_) {
      status("새 서버를 기다리는 중");
    }
  }
  overlay.querySelector(".overlay-box").innerHTML = `<b>다시 시작하지 못했습니다.</b>
    <div>웹 UI를 실행한 콘솔에 오류가 있는지 확인하고, 필요하면 Ctrl+C로 끈 뒤 직접 다시 실행해 주세요.</div>
    <div style="margin-top:10px"><button class="btn small" id="overlay-close">닫기</button></div>`;
  overlay.querySelector("#overlay-close").addEventListener("click", () => overlay.remove());
}

// 웹 UI 서버를 끕니다. 콘솔 없이 아이콘으로 실행했을 때는 이 버튼이 종료 방법입니다.
async function shutdownWebui() {
  const active = [...state.jobs.values()].filter(isActive).length;
  if (active) {
    toast(`진행 중이거나 대기 중인 작업이 ${active}개 있습니다. 끝난 뒤 종료해 주세요.`);
    return;
  }
  if (!confirm("웹 UI를 종료할까요?" + String.fromCharCode(10, 10) + "저장된 서버 목록, 설정, 분석 결과는 그대로 남습니다.")) return;
  try {
    await api("POST", "/api/shutdown", {});
  } catch (e) {
    toast(e.message);
    return;
  }
  document.body.append(h(`<div class="overlay"><div class="overlay-box">
    <b>웹 UI를 종료했습니다.</b>
    <div class="muted">이 탭은 닫아도 됩니다. 다시 쓰려면 바탕화면의 아이콘을 실행하세요.</div></div></div>`));
}

// ---------------------------------------------------------------- 결과 보기

async function renderViewer(main, serverName) {
  const name = state.view.name;
  const card = h(`<div class="card"><p class="muted"><span class="spinner"></span> 불러오는 중...</p></div>`);
  main.append(card);
  let content;
  try {
    content = (await api("GET", `/api/file?server=${encodeURIComponent(serverName)}&name=${encodeURIComponent(name)}`)).content;
  } catch (e) {
    card.innerHTML = `<p class="form-error">${esc(e.message)}</p>`;
    return;
  }
  const isAnalysis = name.includes("-analysis-");
  const fromHistory = state.page === "history";
  card.innerHTML = "";
  const head = h(`<div class="viewer-head">
    <div><button class="btn small ghost" id="v-back">← ${fromHistory ? "분석 기록" : "목록"}</button>
      ${fromHistory ? `<span class="tag server">${esc(serverName)}</span>` : ""} <span class="path">${esc(name)}</span></div>
    <div class="actions"></div></div>`);
  card.append(head);
  $("#v-back").addEventListener("click", () => {
    state.view = null;
    if (!fromHistory) state.tab = "results";
    renderMain();
  });
  const actions = head.querySelector(".actions");

  if (isAnalysis) {
    const split = content.indexOf("\n\n");
    const meta = split > 0 ? content.slice(0, split) : "";
    const body = split > 0 ? content.slice(split + 2) : content;
    // 원본 리포트는 분석 파일 머리말의 source_report 경로에서 찾습니다(파일 이름의 실행 ID에 PID가 들어 있음).
    const source = (meta.match(/^source_report:\s*(.+)$/m) || [])[1] || "";
    const reportName = source.split(/[\\/]/).pop();
    if (reportName) {
      const btn = h('<button class="btn small">원본 리포트 보기</button>');
      btn.addEventListener("click", () => openFile(serverName, reportName));
      actions.append(btn);
    }
    const shortMeta = meta.split("\n").filter(l => !l.startsWith("source_report:") && !l.startsWith("kdump llm")).join("\n");
    card.append(h(`<div class="analysis-meta">${esc(shortMeta).replace(/\n/g, " · ")}</div>`));
    card.append(h(`<div class="markdown">${markdown(body)}</div>`));
    return;
  }

  if (state.servers.some(s => s.name === serverName)) {
    const btn = h('<button class="btn small primary">LLM으로 분석</button>');
    btn.addEventListener("click", () => startJob({ kind: "reanalyze", server: serverName, report: name }));
    actions.append(btn);
  }

  const parts = content.split(/^===== (.+?) =====$/m);
  const preamble = parts[0].trim();
  const sections = [];
  for (let i = 1; i < parts.length; i += 2) sections.push({ title: parts[i], body: (parts[i + 1] || "").replace(/^\n|\n+$/g, "") });

  card.append(h(`<pre class="path" style="margin:0 0 12px;white-space:pre-wrap">${esc(preamble)}</pre>`));
  const tools = h(`<div class="report-tools"><input placeholder="리포트에서 검색 (예: panic, Oops, hung_task)" id="r-search">
    <button class="btn small" id="r-open">모두 펼치기</button><button class="btn small" id="r-close">모두 접기</button></div>`);
  card.append(tools);
  const holder = h("<div></div>");
  card.append(holder);

  function draw(term) {
    holder.innerHTML = "";
    const t = term.trim().toLowerCase();
    for (const s of sections) {
      const lines = s.body.split("\n").length;
      const hit = t && s.body.toLowerCase().includes(t);
      if (t && !hit && !s.title.toLowerCase().includes(t)) continue;
      let text = esc(s.body);
      if (t) {
        const re = new RegExp(esc(term.trim()).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
        text = text.replace(re, m => `<mark>${m}</mark>`);
      }
      const open = hit || /crash> (sys|bt)$/.test(s.title) ? "open" : "";
      holder.append(h(`<details class="section" ${open}><summary><span>${esc(s.title)}</span><span class="count">${lines}줄</span></summary><pre>${text}</pre></details>`));
    }
    if (!holder.children.length) holder.append(h('<p class="muted">검색 결과가 없습니다.</p>'));
  }
  draw("");
  let timer;
  $("#r-search").addEventListener("input", e => { clearTimeout(timer); timer = setTimeout(() => draw(e.target.value), 200); });
  $("#r-open").addEventListener("click", () => holder.querySelectorAll("details").forEach(d => { d.open = true; }));
  $("#r-close").addEventListener("click", () => holder.querySelectorAll("details").forEach(d => { d.open = false; }));
}

// ---------------------------------------------------------------- 서버 관리

async function testServer(name) {
  const line = $("#health-line");
  if (line) line.innerHTML = '<span class="spinner"></span> 연결 테스트 중...';
  try {
    state.health[name] = await api("POST", `/api/servers/${encodeURIComponent(name)}/test`);
    toast(state.health[name].ok ? `${name}: 연결 OK` : `${name}: 연결 실패`);
  } catch (e) {
    state.health[name] = { ok: false, raw: e.message };
  }
  renderSidebar();
  if (state.selected === name) renderMain();
}

function openServerDialog(server) {
  const dialog = $("#server-dialog");
  const form = $("#server-form");
  form.reset();
  $("#server-error").textContent = "";
  $("#server-dialog-title").textContent = server ? "서버 수정" : "서버 추가";
  const values = server || { port: 22, tool: "/opt/kdump-tools/bin/analyze-kdump", crash_dir: "/var/crash", method: "auto", sudo: true };
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.name === "original") el.value = server ? server.name : "";
    else if (el.type === "checkbox") el.checked = !!values[el.name];
    else if (values[el.name] !== undefined) el.value = values[el.name];
  }
  dialog.showModal();
}

$("#server-form").addEventListener("submit", async e => {
  if (e.submitter && e.submitter.value === "cancel") return;
  e.preventDefault();
  const form = e.target;
  const data = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    data[el.name] = el.type === "checkbox" ? el.checked : el.value.trim();
  }
  try {
    const saved = await api("POST", "/api/servers", data);
    await loadState();
    $("#server-dialog").close();
    delete state.vmcores[saved.name];
    selectServer(saved.name);
    toast("저장했습니다. 연결 테스트를 해 보세요.");
  } catch (err) {
    $("#server-error").textContent = err.message;
  }
});

async function deleteServer(name) {
  if (!confirm(`${name} 서버를 목록에서 삭제할까요?\n(가져온 리포트와 분석 파일은 지우지 않습니다)`)) return;
  await api("DELETE", `/api/servers/${encodeURIComponent(name)}`);
  state.selected = null;
  await loadState();
  renderMain();
}

// ---------------------------------------------------------------- 분석 작업

async function startJob(body) {
  try {
    const job = await api("POST", "/api/jobs", body);
    state.jobs.set(job.id, job);
    renderJobs();
    pollJobs();
    return job;
  } catch (e) {
    toast(e.message);
  }
}

let polling = false;
async function pollJobs() {
  if (polling) return;
  polling = true;
  while ([...state.jobs.values()].some(isActive)) {
    await new Promise(r => setTimeout(r, 1000));
    for (const job of [...state.jobs.values()].filter(isActive)) {
      try {
        const next = await api("GET", `/api/jobs/${job.id}`);
        const finished = !isActive(next);
        state.jobs.set(job.id, Object.assign(next, { showLog: job.showLog }));
        if (finished) onJobFinished(next);
      } catch (_) { /* 다음 주기에 다시 시도 */ }
    }
    renderJobs();
  }
  polling = false;
}

async function cancelJobs(list) {
  for (const job of list) {
    try {
      Object.assign(job, await api("POST", `/api/jobs/${job.id}/cancel`));
    } catch (e) { toast(e.message); }
  }
  renderJobs();
}

function onJobFinished(job) {
  if (job.status === "cancelled") { scheduleJobClose(job.id, 2500); return; }
  if (job.kind === "prepare") {
    toast(job.status === "done" ? `${job.server}: 서버 준비를 마쳤습니다.` : `${job.server}: 서버 준비 중 일부가 실패했습니다.`);
    if (job.status === "done") scheduleJobClose(job.id);
    delete state.prepare[job.server];
    delete state.health[job.server];
    if (state.page === "server" && state.selected === job.server && state.tab === "prepare" && !state.view) renderPrepare(state.servers.find(s => s.name === job.server), true);
    return;
  }
  if (job.kind === "upgrade") {
    toast(job.status === "done" ? `${job.server}: v${job.version || "?"} 설치를 마쳤습니다.` : `${job.server}: 설치에 실패했습니다.`);
    delete state.health[job.server];
    if (job.status === "done") scheduleJobClose(job.id);
    loadServerVersion(job.server);
    return;
  }
  const left = [...state.jobs.values()].filter(isActive).length;
  toast((job.status === "done" ? `${job.server}: 분석을 마쳤습니다.` : `${job.server}: 실패했습니다.`) + (left ? ` 남은 작업 ${left}개` : ""));
  if (job.status === "done") scheduleJobClose(job.id);
  delete state.vmcores[job.server]; // 기록 배지를 새로 읽도록
  // 기록 목록을 보고 있으면 새 결과가 보이도록 다시 그립니다.
  if (!state.view && (state.page === "history" || (state.selected === job.server && state.tab === "results"))) renderMain();
}

// 성공한 작업 카드는 잠시 뒤 자동으로 닫습니다. 실패한 카드는 오류를 읽을 수 있게 직접 닫을 때까지 둡니다.
// 마우스를 올려 두었거나 로그를 펼쳐 둔 카드는 닫지 않고 기다립니다.
const JOB_AUTO_CLOSE_MS = 8000;
function scheduleJobClose(id, delay = JOB_AUTO_CLOSE_MS) {
  setTimeout(() => {
    const job = state.jobs.get(id);
    if (!job) return;
    const el = document.querySelector(`.job[data-id="${id}"]`);
    if (job.showLog || (el && el.matches(":hover"))) return scheduleJobClose(id, 3000);
    if (!el) { state.jobs.delete(id); return; }
    el.classList.add("leaving");
    setTimeout(() => { state.jobs.delete(id); renderJobs(); }, 300);
  }, delay);
}

const isActive = job => job.status === "running" || job.status === "queued";

function renderJobs() {
  const box = $("#jobs");
  box.innerHTML = "";
  // 실행 중 → 대기 중 → 끝난 작업 순으로 최대 5개를 보여주고, 나머지는 한 줄로 요약합니다.
  const all = [...state.jobs.values()];
  const rank = j => j.status === "running" ? 0 : j.status === "queued" ? 1 : 2;
  const sorted = all.map((j, i) => [j, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || (rank(a[0]) === 2 ? b[1] - a[1] : a[1] - b[1])).map(x => x[0]);
  const shown = sorted.slice(0, 5);
  const hidden = sorted.slice(5);
  if (hidden.length) {
    const queued = hidden.filter(j => j.status === "queued").length;
    const el = h(`<div class="job summary"><span>그 밖에 ${hidden.length}개${queued ? ` (대기 ${queued}개)` : ""}</span>
      ${queued ? '<button class="linkish" data-act="cancel-all">대기 중인 작업 모두 취소</button>' : ""}</div>`);
    const btn = el.querySelector('[data-act="cancel-all"]');
    if (btn) btn.addEventListener("click", () => cancelJobs(all.filter(j => j.status === "queued")));
    box.append(el);
  }
  for (const job of shown.reverse()) {
    const label = job.kind === "prepare" ? `서버 준비 (${(job.actions || []).length}개 항목)`
      : job.kind === "upgrade"
      ? `analyze-kdump 설치 (${job.source === "github" ? "GitHub" : "노트북 버전"})`
      : { report: "리포트 생성", llm: "리포트 + LLM 분석", reanalyze: "LLM 분석" }[job.kind];
    let pct = null;
    if (job.status === "running" && job.progress && job.progress.total) {
      pct = Math.round(job.progress.current / job.progress.total * 100);
    }
    const detail = job.status === "running" && job.progress
      ? `${job.progress.current}/${job.progress.total} ${job.progress.label || ""}`
      : job.phase;
    const el = h(`<div class="job ${job.status}" data-id="${esc(job.id)}">
      <div class="job-head"><span>${esc(job.server)} · ${esc(label)}</span>
        <span>${job.status === "running" ? '<span class="spinner"></span>' : job.status === "queued" ? '<span class="muted">대기</span>' : (job.status === "done" ? "✓" : job.status === "cancelled" ? "—" : "✕")}</span></div>
      <div class="job-sub">${esc(job.vmcore || job.report || (job.version ? "설치된 버전: v" + job.version : ""))}</div>
      <div class="bar ${pct === null && job.status === "running" ? "indeterminate" : ""}"><span style="width:${pct ?? 0}%"></span></div>
      <div class="job-foot"><span>${esc(detail)}</span><span>${fmtElapsed(job.elapsed)}</span></div>
      ${job.error ? `<div class="job-error">${esc(job.error)}</div>` : ""}
      <div class="job-foot">
        <button class="linkish" data-act="log">${job.showLog ? "로그 숨기기" : "로그 보기"}</button>
        <span>
          ${job.analysis ? '<button class="linkish" data-act="analysis">분석 보기</button>' : ""}
          ${job.report && !isActive(job) ? ' <button class="linkish" data-act="report">리포트 보기</button>' : ""}
          ${job.status === "queued" ? ' <button class="linkish" data-act="cancel">취소</button>' : ""}
          ${!isActive(job) ? ' <button class="linkish" data-act="close">닫기</button>' : ""}
        </span>
      </div>
      ${job.showLog ? `<div class="job-log">${esc(job.logs.join("\n"))}</div>` : ""}
    </div>`);
    el.querySelectorAll("[data-act]").forEach(b => b.addEventListener("click", () => {
      const act = b.dataset.act;
      if (act === "log") { job.showLog = !job.showLog; renderJobs(); }
      if (act === "close") { state.jobs.delete(job.id); renderJobs(); }
      if (act === "cancel") cancelJobs([job]);
      if (act === "analysis" || act === "report") {
        state.page = "server";
        openFile(job.server, act === "analysis" ? job.analysis : job.report);
      }
    }));
    box.append(el);
    const log = el.querySelector(".job-log");
    if (log) log.scrollTop = log.scrollHeight;
  }
}

// ---------------------------------------------------------------- 설정

function syncProviderFields() {
  const provider = $("#settings-form").elements.provider.value;
  const cli = provider === "claude-code" || provider === "codex";
  document.querySelectorAll(".api-only").forEach(el => { el.style.display = cli ? "none" : ""; });
  document.querySelectorAll(".cli-only").forEach(el => { el.style.display = cli ? "" : "none"; });
  document.querySelectorAll(".claude-only").forEach(el => { el.style.display = provider === "claude-code" ? "" : "none"; });
  $("#cli-status").textContent = "";
}

function fillSettings() {
  const form = $("#settings-form");
  const s = state.settings;
  for (const el of form.elements) {
    if (!el.name || !(el.name in s)) continue;
    if (el.type === "checkbox") el.checked = !!s[el.name];
    else el.value = s[el.name] ?? "";
  }
  $("#api-key-state").textContent = s.api_key_saved ? "(저장된 키 있음)" : "(저장된 키 없음)";
  $("#cli-token-state").textContent = s.cli_token_saved ? "(저장된 토큰 있음)" : "";
  $("#api-key-input").value = "";
  $("#cli-token-input").value = "";
  $("#settings-error").textContent = "";
  $("#llm-test-result").textContent = "";
  syncProviderFields();
}

function settingsPayload() {
  const form = $("#settings-form");
  const data = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    data[el.name] = el.type === "checkbox" ? el.checked : el.value.trim();
  }
  return data;
}

async function saveSettings(quiet) {
  state.settings = await api("POST", "/api/settings", settingsPayload());
  renderSidebar();
  if (!quiet) toast("설정을 저장했습니다.");
}

function openSettings() {
  fillSettings();
  $("#settings-dialog").showModal();
}

$("#open-settings").addEventListener("click", openSettings);
$("#llm-chip").addEventListener("click", openSettings);
$("#settings-form").elements.provider.addEventListener("change", () => {
  $("#settings-form").elements.model.value = "";
  $("#model-options").innerHTML = "";
  syncProviderFields();
});

$("#settings-form").addEventListener("submit", async e => {
  if (e.submitter && e.submitter.value === "cancel") return;
  e.preventDefault();
  try {
    await saveSettings();
    $("#settings-dialog").close();
  } catch (err) {
    $("#settings-error").textContent = err.message;
  }
});

$("#load-models").addEventListener("click", async () => {
  const btn = $("#load-models");
  btn.disabled = true;
  try {
    await saveSettings(true);
    const models = (await api("GET", "/api/models")).models;
    $("#model-options").innerHTML = models.map(m => `<option value="${esc(m)}">`).join("");
    toast(models.length ? `모델 ${models.length}개를 불러왔습니다. 입력란을 눌러 고르세요.` : "이 provider는 모델 목록을 제공하지 않습니다.");
    $("#settings-form").elements.model.focus();
  } catch (err) {
    $("#settings-error").textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

$("#save-api-key").addEventListener("click", async () => {
  const value = $("#api-key-input").value.trim();
  if (!value) return;
  try {
    await saveSettings(true);
    state.settings = await api("POST", "/api/secrets/api-key", { value });
    fillSettings();
    toast("API 키를 이 컴퓨터에 저장했습니다.");
  } catch (err) {
    $("#settings-error").textContent = err.message;
  }
});

$("#save-cli-token").addEventListener("click", async () => {
  const value = $("#cli-token-input").value.trim();
  if (!value) return;
  try {
    await saveSettings(true);
    state.settings = await api("POST", "/api/secrets/cli-token", { value });
    fillSettings();
    toast("토큰을 이 컴퓨터에 저장했습니다.");
  } catch (err) {
    $("#settings-error").textContent = err.message;
  }
});

$("#cli-refresh").addEventListener("click", async () => {
  const box = $("#cli-status");
  box.innerHTML = '<span class="spinner"></span> 확인 중...';
  try {
    await saveSettings(true);
    const s = await api("GET", "/api/cli/status");
    box.textContent = `실행 파일: ${s.path}\n버전: ${s.version || "-"}\n상태: ${s.logged_in ? "로그인됨" : "로그인 필요"}\n${s.status}`;
  } catch (err) {
    box.textContent = err.message;
  }
});

$("#llm-test").addEventListener("click", async () => {
  const out = $("#llm-test-result");
  out.innerHTML = '<span class="spinner"></span> 짧은 요청 1회 보내는 중...';
  try {
    await saveSettings(true);
    const r = await api("POST", "/api/cli/test");
    out.textContent = `성공 (${r.elapsed}초): ${r.reply}`;
  } catch (err) {
    out.textContent = "실패: " + err.message;
  }
});

$("#add-server").addEventListener("click", () => openServerDialog());
$("#nav-history").addEventListener("click", openHistory);
$("#nav-versions").addEventListener("click", openVersions);
$("#version").addEventListener("click", openVersions);

// ---------------------------------------------------------------- 시작

async function loadState() {
  const data = await api("GET", "/api/state");
  state.version = data.version;
  state.settings = data.settings;
  state.servers = data.servers;
  state.apiMismatch = data.api !== API_LEVEL;
  state.supervised = !!data.supervised;
  state.startedAt = data.started_at;
  const banner = $("#restart-banner");
  if (state.apiMismatch) {
    const running = data.running_version ? `v${data.running_version}` : "이전 버전";
    if (state.supervised) {
      banner.innerHTML = `<b>웹 UI를 다시 시작해 주세요.</b> 화면은 새 버전으로 바뀌었지만 서버는 ${esc(running)}으로 실행 중이라 일부 기능이 동작하지 않습니다. `;
      banner.append(restartButton("지금 다시 시작"));
    } else {
      banner.innerHTML = `<b>웹 UI를 다시 시작해 주세요.</b> 화면은 새 버전으로 바뀌었지만 서버는 ${esc(running)}으로 실행 중이라 일부 기능이 동작하지 않습니다. 웹 UI를 실행한 콘솔에서 <code>Ctrl+C</code>로 끈 뒤 <code>python webui/kdump-webui.py</code>로 다시 실행하고, 새로 나온 주소로 접속하세요.`;
    }
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
  // 페이지를 새로 열었을 때는 아직 진행 중인 작업만 다시 보여줍니다.
  for (const job of data.jobs) if (isActive(job) && !state.jobs.has(job.id)) state.jobs.set(job.id, job);
  renderVersionBadge();
  if (!state.selected && state.servers.length === 1) state.selected = state.servers[0].name;
  renderSidebar();
}

loadState().then(() => {
  // 새로고침했거나 주소로 바로 들어온 경우 그 화면을 다시 엽니다.
  // 첫 화면은 방문 기록을 새로 쌓지 않고 현재 기록을 바꿉니다(뒤로 가기 한 번이 헛돌지 않도록).
  restoringRoute = true;
  if (location.hash && location.hash !== "#/") {
    applyRoute(location.hash);
    renderSidebar();
  }
  renderMain();
  restoringRoute = false;
  renderJobs(); pollJobs(); loadVersions().then(() => { if (state.page === "versions") renderMain(); }); }).catch(e => {
  $("#main").innerHTML = `<div class="card"><p class="form-error">${esc(e.message)}</p></div>`;
});
