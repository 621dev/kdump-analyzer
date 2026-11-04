"use strict";

// ---------------------------------------------------------------- 상태와 공통

const state = {
  version: "",
  settings: {},
  servers: [],
  selected: null,       // 서버 이름
  tab: "vmcores",       // vmcores | results
  view: null,           // { name } 결과 파일 보기
  health: {},           // 서버 이름 -> 연결 테스트 결과
  jobs: new Map(),      // 작업 id -> 작업
  vmcores: {},          // 서버 이름 -> 목록 캐시
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
  if (!res.ok) throw new Error(data.error || `요청 실패 (${res.status})`);
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
  for (const s of state.servers) {
    const health = state.health[s.name];
    const dot = health ? (health.ok ? "ok" : "err") : "";
    const item = h(`<li class="server-item ${state.selected === s.name ? "active" : ""}">
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
  state.selected = name;
  state.view = null;
  renderSidebar();
  renderMain();
}

// ---------------------------------------------------------------- 메인 화면

function renderMain() {
  const main = $("#main");
  main.innerHTML = "";
  if (!state.servers.length) {
    main.append(h(`<div class="card empty">
      <h2>kdump-tools 웹 UI</h2>
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

  if (state.view) return renderViewer(main, server);

  const panel = h(`<div class="card">
    <div class="tabs">
      <button class="tab ${state.tab === "vmcores" ? "active" : ""}" data-tab="vmcores">vmcore</button>
      <button class="tab ${state.tab === "results" ? "active" : ""}" data-tab="results">분석 결과</button>
    </div>
    <div id="tab-body"></div>
  </div>`);
  main.append(panel);
  panel.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => { state.tab = b.dataset.tab; renderMain(); }));
  if (state.tab === "vmcores") renderVmcores(server); else renderResults(server);
}

async function renderVmcores(server, refresh = false) {
  const body = $("#tab-body");
  if (!state.vmcores[server.name] || refresh) {
    body.innerHTML = '<p class="muted"><span class="spinner"></span> 원격 서버에서 vmcore 목록을 읽는 중...</p>';
    try {
      state.vmcores[server.name] = (await api("GET", `/api/servers/${encodeURIComponent(server.name)}/vmcores`)).vmcores;
    } catch (e) {
      body.innerHTML = `<p class="form-error">${esc(e.message)}</p>`;
      return;
    }
  }
  if (state.selected !== server.name || state.tab !== "vmcores" || state.view) return;
  const items = state.vmcores[server.name];
  const wrap = h(`<div>
    <div class="viewer-head"><span class="muted">${esc(server.crash_dir)} · ${items.length}개</span>
      <button class="btn small" id="vm-refresh">새로고침</button></div>
  </div>`);
  if (!items.length) {
    wrap.append(h('<p class="muted">vmcore가 없습니다.</p>'));
  } else {
    const table = h(`<table class="list"><thead><tr><th>시각</th><th>크기</th><th>경로</th><th></th></tr></thead><tbody></tbody></table>`);
    for (const v of items) {
      const row = h(`<tr>
        <td style="white-space:nowrap">${fmtTime(v.mtime)}</td>
        <td>${fmtSize(v.size)}</td>
        <td class="path">${esc(v.path)}</td>
        <td style="white-space:nowrap;text-align:right">
          <button class="btn small" data-kind="report">리포트</button>
          <button class="btn small primary" data-kind="llm">리포트 + LLM 분석</button>
        </td></tr>`);
      row.querySelectorAll("button").forEach(b => b.addEventListener("click", () =>
        startJob({ kind: b.dataset.kind, server: server.name, vmcore: v.path })));
      table.tBodies[0].append(row);
    }
    wrap.append(table);
  }
  const body2 = $("#tab-body");
  body2.innerHTML = "";
  body2.append(wrap);
  $("#vm-refresh").addEventListener("click", () => renderVmcores(server, true));
}

async function renderResults(server) {
  const body = $("#tab-body");
  body.innerHTML = '<p class="muted"><span class="spinner"></span> 불러오는 중...</p>';
  let results;
  try {
    results = (await api("GET", `/api/results?server=${encodeURIComponent(server.name)}`)).results;
  } catch (e) {
    body.innerHTML = `<p class="form-error">${esc(e.message)}</p>`;
    return;
  }
  if (state.selected !== server.name || state.tab !== "results" || state.view) return;
  body.innerHTML = "";
  if (!results.length) {
    body.append(h('<p class="muted">아직 분석 결과가 없습니다. vmcore 탭에서 분석을 실행하세요.</p>'));
    return;
  }
  const table = h(`<table class="list"><thead><tr><th>종류</th><th>파일</th><th>시각</th><th>크기</th></tr></thead><tbody></tbody></table>`);
  for (const r of results) {
    const row = h(`<tr class="clickable">
      <td><span class="tag ${r.kind}">${r.kind === "analysis" ? "LLM 분석" : "리포트"}</span></td>
      <td class="path">${esc(r.name)}</td>
      <td style="white-space:nowrap">${fmtTime(r.mtime)}</td>
      <td>${fmtSize(r.size)}</td></tr>`);
    row.addEventListener("click", () => { state.view = { name: r.name }; renderMain(); });
    table.tBodies[0].append(row);
  }
  body.append(table);
}

// ---------------------------------------------------------------- 결과 보기

async function renderViewer(main, server) {
  const name = state.view.name;
  const card = h(`<div class="card"><p class="muted"><span class="spinner"></span> 불러오는 중...</p></div>`);
  main.append(card);
  let content;
  try {
    content = (await api("GET", `/api/file?server=${encodeURIComponent(server.name)}&name=${encodeURIComponent(name)}`)).content;
  } catch (e) {
    card.innerHTML = `<p class="form-error">${esc(e.message)}</p>`;
    return;
  }
  const isAnalysis = name.includes("-analysis-");
  card.innerHTML = "";
  const head = h(`<div class="viewer-head">
    <div><button class="btn small ghost" id="v-back">← 목록</button> <span class="path">${esc(name)}</span></div>
    <div class="actions"></div></div>`);
  card.append(head);
  $("#v-back").addEventListener("click", () => { state.view = null; state.tab = "results"; renderMain(); });
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
      btn.addEventListener("click", () => { state.view = { name: reportName }; renderMain(); });
      actions.append(btn);
    }
    const shortMeta = meta.split("\n").filter(l => !l.startsWith("source_report:") && !l.startsWith("kdump llm")).join("\n");
    card.append(h(`<div class="analysis-meta">${esc(shortMeta).replace(/\n/g, " · ")}</div>`));
    card.append(h(`<div class="markdown">${markdown(body)}</div>`));
    return;
  }

  const btn = h('<button class="btn small primary">LLM으로 분석</button>');
  btn.addEventListener("click", () => startJob({ kind: "reanalyze", server: server.name, report: name }));
  actions.append(btn);

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
  } catch (e) {
    toast(e.message);
  }
}

let polling = false;
async function pollJobs() {
  if (polling) return;
  polling = true;
  while ([...state.jobs.values()].some(j => j.status === "running")) {
    await new Promise(r => setTimeout(r, 1000));
    for (const job of [...state.jobs.values()].filter(j => j.status === "running")) {
      try {
        const next = await api("GET", `/api/jobs/${job.id}`);
        const finished = next.status !== "running";
        state.jobs.set(job.id, Object.assign(next, { showLog: job.showLog }));
        if (finished) onJobFinished(next);
      } catch (_) { /* 다음 주기에 다시 시도 */ }
    }
    renderJobs();
  }
  polling = false;
}

function onJobFinished(job) {
  toast(job.status === "done" ? `${job.server}: 분석을 마쳤습니다.` : `${job.server}: 실패했습니다.`);
  if (state.selected === job.server && state.tab === "results" && !state.view) renderMain();
}

function renderJobs() {
  const box = $("#jobs");
  box.innerHTML = "";
  for (const job of [...state.jobs.values()].slice(-4)) {
    const label = { report: "리포트 생성", llm: "리포트 + LLM 분석", reanalyze: "LLM 분석" }[job.kind];
    let pct = null;
    if (job.status === "running" && job.progress && job.progress.total) {
      pct = Math.round(job.progress.current / job.progress.total * 100);
    }
    const detail = job.status === "running" && job.progress
      ? `${job.progress.current}/${job.progress.total} ${job.progress.label || ""}`
      : job.phase;
    const el = h(`<div class="job ${job.status}">
      <div class="job-head"><span>${esc(job.server)} · ${esc(label)}</span>
        <span>${job.status === "running" ? '<span class="spinner"></span>' : (job.status === "done" ? "✓" : "✕")}</span></div>
      <div class="job-sub">${esc(job.vmcore || job.report || "")}</div>
      <div class="bar ${pct === null && job.status === "running" ? "indeterminate" : ""}"><span style="width:${pct ?? 0}%"></span></div>
      <div class="job-foot"><span>${esc(detail)}</span><span>${fmtElapsed(job.elapsed)}</span></div>
      ${job.error ? `<div class="job-error">${esc(job.error)}</div>` : ""}
      <div class="job-foot">
        <button class="linkish" data-act="log">${job.showLog ? "로그 숨기기" : "로그 보기"}</button>
        <span>
          ${job.analysis ? '<button class="linkish" data-act="analysis">분석 보기</button>' : ""}
          ${job.report && job.status !== "running" ? ' <button class="linkish" data-act="report">리포트 보기</button>' : ""}
          ${job.status !== "running" ? ' <button class="linkish" data-act="close">닫기</button>' : ""}
        </span>
      </div>
      ${job.showLog ? `<div class="job-log">${esc(job.logs.join("\n"))}</div>` : ""}
    </div>`);
    el.querySelectorAll("[data-act]").forEach(b => b.addEventListener("click", () => {
      const act = b.dataset.act;
      if (act === "log") { job.showLog = !job.showLog; renderJobs(); }
      if (act === "close") { state.jobs.delete(job.id); renderJobs(); }
      if (act === "analysis" || act === "report") {
        state.selected = job.server;
        state.view = { name: act === "analysis" ? job.analysis : job.report };
        renderSidebar();
        renderMain();
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

// ---------------------------------------------------------------- 시작

async function loadState() {
  const data = await api("GET", "/api/state");
  state.version = data.version;
  state.settings = data.settings;
  state.servers = data.servers;
  // 페이지를 새로 열었을 때는 아직 진행 중인 작업만 다시 보여줍니다.
  for (const job of data.jobs) if (job.status === "running" && !state.jobs.has(job.id)) state.jobs.set(job.id, job);
  $("#version").textContent = "v" + data.version;
  if (!state.selected && state.servers.length === 1) state.selected = state.servers[0].name;
  renderSidebar();
}

loadState().then(() => { renderMain(); renderJobs(); pollJobs(); }).catch(e => {
  $("#main").innerHTML = `<div class="card"><p class="form-error">${esc(e.message)}</p></div>`;
});
