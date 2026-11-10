#!/usr/bin/env python3
"""kdump-analyzer 웹 UI

PC(Windows·macOS·Linux)나 서버에서 실행하는 로컬 웹 앱입니다. 브라우저로 조작하고,
분석할 서버에는 SSH로 접속해 analyze-kdump로 crash 리포트를 만든 뒤, 리포트를 가져와
LLM 분석은 이 컴퓨터에서 합니다(API 키·구독 로그인은 이 컴퓨터에만 있으면 됨).

    python webui/kdump-webui.py [--port 8730] [--data-dir ~/.kdump-tools-web] [--no-browser]

127.0.0.1에만 열리고, 시작할 때 출력되는 토큰 주소로만 접속할 수 있습니다.
Python 3.8 이상, 표준 라이브러리만 사용합니다.
"""

import argparse
import http.server
import json
import os
import re
import secrets
import shlex
import shutil
import socketserver
import base64
import contextlib
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _hide_child_consoles():
    """콘솔이 없는 프로세스(pythonw)가 ssh·git 같은 콘솔 프로그램을 띄우면 창이 열렸다 닫힙니다.
    콘솔이 없을 때만 모든 하위 프로세스에 CREATE_NO_WINDOW를 줍니다(콘솔에서 실행할 때는 그대로)."""
    if os.name != "nt":
        return
    import ctypes
    if ctypes.windll.kernel32.GetConsoleWindow():
        return
    original = subprocess.Popen.__init__

    def patched(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x08000000  # CREATE_NO_WINDOW
        original(self, *args, **kwargs)
    subprocess.Popen.__init__ = patched


_hide_child_consoles()
import kdump_llm  # noqa: E402

APP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(APP_DIR)
# 화면(app.js)과 서버가 주고받는 API의 판. API를 바꿀 때 app.js의 API_LEVEL과 함께 올립니다.
# 업데이트 뒤 서버를 다시 시작하지 않으면 화면이 이 값의 차이로 알아채고 안내합니다.
API_LEVEL = 11

# 화면의 "다시 시작"은 감시 프로세스가 서버를 새 코드로 다시 띄우는 방식입니다.
RESTART_EXIT = 75                     # 서버가 이 코드로 끝나면 감시 프로세스가 다시 띄웁니다
ENV_WORKER = "KDUMP_WEBUI_WORKER"     # 감시 프로세스가 띄운 서버임을 표시
ENV_TOKEN = "KDUMP_WEBUI_TOKEN"       # 다시 시작해도 같은 토큰(브라우저 쿠키 유지)
AUTO_LOG = "auto-log.json"            # 새 덤프 자동 분석이 끝낸 작업 기록(데이터 폴더)
AUTO_LOG_MAX = 200
ENV_PORT = "KDUMP_WEBUI_PORT"         # 다시 시작해도 같은 포트
STATIC_DIR = os.path.join(APP_DIR, "static")
WIN_SCRIPT = os.path.join(os.path.dirname(APP_DIR), "winbin", "analyze-windump.ps1")
ANALYZE_SCRIPT = os.path.join(REPO_DIR, "bin", "analyze-kdump")

NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
FILE_RE = re.compile(r"^kdump-(report|analysis)-[A-Za-z0-9._-]+\.txt$")
PROGRESS_RE = re.compile(r"crash 리포트 생성 \[[#.]+\] (\d+)/(\d+) (.*?) \((\d+)초\)")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

DEFAULT_SETTINGS = {
    "provider": "openai", "model": "", "base_url": "", "api_key_file": "",
    "cli_path": "", "cli_token_file": "", "cli_args": "",
    "mask": True, "max_report_chars": 60000, "max_tokens": 8192, "timeout": 300,
    "crash_timeout": 30,
    "update_repo": "621dev/kdump-analyzer", "update_branch": "main",
    # release: GitHub의 최신 릴리스(태그)로 업데이트, branch: update_branch의 최신 커밋으로 업데이트
    "update_channel": "release",
    "auto_interval": 10,   # 새 덤프 자동 분석: 서버를 확인하는 주기(분)
}
UPDATE_CHANNELS = ("release", "branch")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
TOOL_VERSION_RE = re.compile(r"analyze-(?:kdump|windump) (\S+?)(?: \(commit ([0-9a-f]+)\))?(?:, 설치 (.+))?$")
# 새 서버의 기본 원격 경로. 서버에 이 경로가 없고 예전 기본 위치(/opt/kdump-tools)에만 설치돼 있으면
# 원격 스크립트가 예전 위치를 씁니다(with_install_fallback).
DEFAULT_TOOL = "/opt/kdump-analyzer/bin/analyze-kdump"
# Windows 서버의 기본값: 분석 스크립트 설치 위치와 덤프가 있는 디렉터리(MEMORY.DMP, Minidump)
WIN_TOOL = r"C:\ProgramData\kdump-analyzer\bin\analyze-windump.ps1"
WIN_DUMP_DIR = r"C:\Windows"
SERVER_OS = ("linux", "windows")
DEFAULT_SERVER = {
    "name": "", "target": "", "port": 22, "key_file": "", "sudo": True,
    "tool": DEFAULT_TOOL, "crash_dir": "/var/crash", "method": "auto", "os": "linux",
    # 새 덤프 자동 분석: off | report(리포트) | llm(리포트 + LLM 분석)
    "auto": "off",
}
AUTO_MODES = ("off", "report", "llm")


def version_text():
    try:
        with open(os.path.join(REPO_DIR, "VERSION"), encoding="utf-8") as f:
            return f.readline().strip()
    except OSError:
        return "unknown"


# ---------------------------------------------------------------- 저장소

class Store:
    """설정·서버 목록·비밀·결과 파일을 데이터 디렉터리에 둡니다."""

    def __init__(self, data_dir):
        self.dir = data_dir
        self.lock = threading.Lock()
        for sub in ("", "secrets", "reports"):
            os.makedirs(os.path.join(data_dir, sub), exist_ok=True)
        try:
            os.chmod(os.path.join(data_dir, "secrets"), 0o700)
        except OSError:
            pass

    def _load(self, name, default):
        path = os.path.join(self.dir, name)
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return default

    def _save(self, name, data):
        path = os.path.join(self.dir, name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def settings(self):
        merged = dict(DEFAULT_SETTINGS)
        merged.update(self._load("settings.json", {}))
        return merged

    def save_settings(self, values):
        with self.lock:
            current = self.settings()
            for key in DEFAULT_SETTINGS:
                if key in values:
                    current[key] = values[key]
            self._save("settings.json", current)
        return current

    def servers(self):
        return self._load("servers.json", [])

    def server(self, name):
        for server in self.servers():
            if server["name"] == name:
                return server
        raise ApiError(404, "서버를 찾을 수 없습니다: %s" % name)

    def save_server(self, values, original=None):
        server = dict(DEFAULT_SERVER)
        server.update({k: values[k] for k in DEFAULT_SERVER if k in values})
        server["port"] = int(server.get("port") or 22)
        server["sudo"] = bool(server.get("sudo"))
        if not NAME_RE.match(server["name"] or ""):
            raise ApiError(400, "서버 이름은 영문, 숫자, . _ - 만 쓸 수 있습니다.")
        if not valid_ssh_target(server["target"]):
            raise ApiError(400, "접속 대상(user@host)을 공백 없이, '-'로 시작하지 않게 입력해 주세요.")
        if server["method"] not in ("auto", "installed", "upload"):
            raise ApiError(400, "분석 방식이 올바르지 않습니다.")
        if server.get("auto") not in AUTO_MODES:
            raise ApiError(400, "자동 분석은 off, report, llm 중 하나여야 합니다.")
        if server.get("os") not in SERVER_OS:
            raise ApiError(400, "운영체제는 linux 또는 windows여야 합니다.")
        if server["os"] == "windows":
            server["sudo"] = False  # Windows는 관리자 계정으로 접속합니다(sudo 없음).
            if not server["tool"].lower().endswith("\\bin\\analyze-windump.ps1"):
                raise ApiError(400, "Windows 서버의 분석 스크립트 경로는 ...\\bin\\analyze-windump.ps1 형태여야 합니다 (기본 %s)." % WIN_TOOL)
        with self.lock:
            servers = [s for s in self.servers() if s["name"] not in (original, server["name"])]
            if original != server["name"] and any(s["name"] == server["name"] for s in self.servers()):
                raise ApiError(400, "이미 있는 서버 이름입니다: %s" % server["name"])
            servers.append(server)
            servers.sort(key=lambda s: s["name"])
            self._save("servers.json", servers)
        return server

    def delete_server(self, name):
        with self.lock:
            self._save("servers.json", [s for s in self.servers() if s["name"] != name])

    def save_secret(self, filename, value):
        """API 키·토큰을 저장합니다. Windows에서는 DPAPI로 암호화합니다(kdump_llm.protect_secret)."""
        path = os.path.join(self.dir, "secrets", filename)
        stored = kdump_llm.protect_secret(value)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(stored + "\n")
        return path

    def protect_existing_secrets(self):
        """예전 판이 평문으로 저장한 비밀을 이 PC의 방식(DPAPI)으로 다시 저장합니다. 바꾼 파일 이름 목록."""
        if kdump_llm.secret_protection() != "dpapi":
            return []
        folder = os.path.join(self.dir, "secrets")
        changed = []
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            path = os.path.join(folder, name)
            if not os.path.isfile(path) or name.endswith(".tmp") or kdump_llm.is_protected(path):
                continue
            try:
                value = kdump_llm.read_secret(path)
                if value:
                    self.save_secret(name, value)
                    changed.append(name)
            except (OSError, ValueError) as error:
                print("비밀 파일을 암호화하지 못했습니다: %s (%s)" % (name, error), file=sys.stderr)
        return changed

    def report_dir(self, server):
        path = os.path.join(self.dir, "reports", server)
        os.makedirs(path, exist_ok=True)
        return path

    def results(self, server):
        path = self.report_dir(server)
        items = []
        for name in os.listdir(path):
            if FILE_RE.match(name):
                full = os.path.join(path, name)
                items.append({"name": name, "kind": "analysis" if "-analysis-" in name else "report",
                              "size": os.path.getsize(full), "mtime": os.path.getmtime(full)})
        items.sort(key=lambda i: i["mtime"], reverse=True)
        return items

    def history(self, server=None):
        """리포트별로 LLM 분석을 묶은 분석 기록. 삭제한 서버의 기록도 포함합니다."""
        base = os.path.join(self.dir, "reports")
        servers = [server] if server else (sorted(os.listdir(base)) if os.path.isdir(base) else [])
        records = []
        for srv in servers:
            folder = os.path.join(base, srv)
            if not NAME_RE.match(srv) or not os.path.isdir(folder):
                continue
            reports, analyses = {}, []
            for name in os.listdir(folder):
                if not FILE_RE.match(name):
                    continue
                full = os.path.join(folder, name)
                info = parse_result_head(full)
                info.update(name=name, mtime=os.path.getmtime(full))
                if "-analysis-" in name:
                    analyses.append(info)
                else:
                    reports[name] = info
            grouped = {}
            for a in analyses:
                source = a.pop("source_report", "")
                key = re.split(r"[\\/]", source)[-1] if source else ""
                grouped.setdefault(key if key in reports else "?" + a["name"], []).append(a)
            for name, rep in reports.items():
                records.append(self._record(srv, rep, grouped.pop(name, [])))
            for items in grouped.values():  # 원본 리포트가 지워진 분석
                records.append(self._record(srv, None, items))
        auto = self.auto_reports()
        for record in records:
            record["auto"] = bool(record["report"]) and (record["server"], record["report"]["name"]) in auto
        records.sort(key=lambda r: r["time"], reverse=True)
        return records

    def export_data(self, server, name, mask=False):
        """보고서로 내보낼 리포트, JSON 요약, LLM 분석(가장 최근)을 모읍니다. name은 리포트나 분석 파일.

        mask면 LLM에 보낼 때와 같은 규칙(kdump_llm.mask_text)으로 호스트명, IPv4, MAC, 이메일을 가립니다.
        호스트명은 리포트의 sys NODENAME에서 찾으므로, 분석과 요약도 리포트와 함께 가립니다.
        """
        path = self.result_path(server, name)
        analysis_name = report_name = None
        if "-analysis-" in name:
            analysis_name = name
            source = parse_result_head(path).get("source_report", "")
            candidate = re.split(r"[\\/]", source)[-1] if source else ""
            if candidate and FILE_RE.match(candidate) and os.path.exists(os.path.join(self.report_dir(server), candidate)):
                report_name = candidate
        else:
            report_name = name
            for rec in self.history(server):
                if rec["report"] and rec["report"]["name"] == name and rec["analyses"]:
                    analysis_name = rec["analyses"][0]["name"]
                    break

        def read(n):
            if not n:
                return ""
            with open(self.result_path(server, n), encoding="utf-8", errors="replace") as f:
                return f.read()

        report, analysis = read(report_name), read(analysis_name)
        summary = load_summary(self.result_path(server, report_name)) if report_name else None
        if mask:
            sep = "\n\x00KDUMP-EXPORT-SPLIT\x00\n"
            joined = kdump_llm.mask_text(sep.join([report, analysis, json.dumps(summary, ensure_ascii=False)]))
            parts = joined.split(sep)
            if len(parts) == 3:
                report, analysis = parts[0], parts[1]
                summary = json.loads(parts[2])
        return {"server": server, "report_name": report_name, "report": report,
                "analysis_name": analysis_name, "analysis": analysis, "summary": summary, "masked": bool(mask),
                "version": version_text(), "exported": time.strftime("%Y-%m-%d %H:%M:%S")}

    @staticmethod
    def _record(server, report, analyses):
        analyses.sort(key=lambda a: a["mtime"], reverse=True)
        times = [a["mtime"] for a in analyses] + ([report["mtime"]] if report else [])
        return {"server": server, "time": max(times), "report": report, "analyses": analyses}

    def result_path(self, server, name):
        if not NAME_RE.match(server or "") or not FILE_RE.match(name or ""):
            raise ApiError(400, "잘못된 파일 이름입니다.")
        path = os.path.join(self.report_dir(server), name)
        if not os.path.exists(path):
            raise ApiError(404, "파일을 찾을 수 없습니다: %s" % name)
        return path

    def add_auto_log(self, entry):
        """새 덤프 자동 분석이 끝낸 작업(성공·실패·취소)을 auto-log.json에 남깁니다. 최근 AUTO_LOG_MAX건만 둡니다."""
        with self.lock:
            log = self._load(AUTO_LOG, [])
            if not isinstance(log, list):
                log = []
            log.append(entry)
            self._save(AUTO_LOG, log[-AUTO_LOG_MAX:])

    def auto_log(self, limit=50):
        """최근 자동 분석 기록(최신 순). 리포트가 남아 있으면 장애 유형을 붙이고, 지워졌으면 표시합니다."""
        log = self._load(AUTO_LOG, [])
        if not isinstance(log, list):
            return []
        items = []
        for entry in reversed(log[-AUTO_LOG_MAX:]):
            if not isinstance(entry, dict) or not NAME_RE.match(str(entry.get("server", ""))):
                continue
            item = dict(entry)
            folder = os.path.join(self.dir, "reports", item["server"])
            for key in ("report", "analysis"):
                name = item.get(key)
                item[key + "_exists"] = bool(name and FILE_RE.match(name) and os.path.isfile(os.path.join(folder, name)))
            if item["report_exists"]:
                head = parse_result_head(os.path.join(folder, item["report"]))
                item["type"], item["type_label"] = head.get("type", ""), head.get("type_label", "")
            items.append(item)
            if len(items) >= limit:
                break
        return items

    def auto_reports(self):
        """자동 분석이 만든 리포트 (서버, 파일 이름)."""
        log = self._load(AUTO_LOG, [])
        return {(e.get("server"), e.get("report")) for e in log if isinstance(e, dict) and e.get("report")} \
            if isinstance(log, list) else set()

    def delete_results(self, server, names, busy=()):
        """웹 UI에 저장된 리포트·분석 파일을 지웁니다. 삭제한 서버의 기록도 지울 수 있습니다.

        - 리포트를 고르면 그 JSON 요약과, 그 리포트로 만든 LLM 분석도 함께 지웁니다.
        - 분석을 고르면 그 분석 파일만 지웁니다.
        - busy(진행 중인 작업이 쓰는 파일 이름)에 걸리면 아무것도 지우지 않습니다.
        서버의 덤프와, 분석 서버에 남은 리포트(설치 실행의 logs)는 건드리지 않습니다.
        """
        if not isinstance(names, list) or not 1 <= len(names) <= 500:
            raise ApiError(400, "지울 파일을 1~500개 골라 주세요.")
        for name in names:
            self.result_path(server, name)   # 이름 검사와 존재 확인
        folder = self.report_dir(server)
        targets = []
        reports = [n for n in names if "-analysis-" not in n]
        for name in names:
            if name not in targets:
                targets.append(name)
        if reports:
            for name in os.listdir(folder):
                if "-analysis-" not in name or not FILE_RE.match(name) or name in targets:
                    continue
                source = parse_result_head(os.path.join(folder, name)).get("source_report", "")
                if source and re.split(r"[\\/]", source)[-1] in reports:
                    targets.append(name)
        blocked = [n for n in targets if n in busy]
        if blocked:
            raise ApiError(409, "진행 중인 작업이 쓰고 있어 지울 수 없습니다: %s. 작업이 끝난 뒤 다시 시도해 주세요."
                           % ", ".join(blocked))
        deleted = []
        with self.lock:
            for name in targets:
                full = os.path.join(folder, name)
                extra = [summary_path(full)] if "-analysis-" not in name else []
                for path in [full] + extra:
                    try:
                        os.remove(path)
                    except FileNotFoundError:
                        continue
                deleted.append(name)
        return deleted


HEAD_KEYS = ("vmcore", "kernel", "generated", "provider", "model", "source_report")

# 분석 기록에 보일 "판정" 한 줄을 찾습니다. LLM마다 보고서 형식이 달라 우선순위대로 찾습니다.
#   1) "판정: ..." / "결론: ..." 줄 (기본 프롬프트가 첫 줄에 쓰도록 요청함)
#   2) 요약 표의 판정·결론·근본 원인 행
#   3) "추정 근본 원인: ..." 같은 항목
#   4) "근본 원인"·"결론"·"판정" 제목 바로 아래의 첫 문장
#   5) 제목이 아닌 첫 문장
VERDICT_LABELS = r"(판정|결론|verdict|conclusion)"
CAUSE_LABELS = r"(추정\s*근본\s*원인|추정\s*원인|근본\s*원인|직접\s*원인|root\s*cause|probable\s*root\s*cause)"
LIST_MARK_RE = re.compile(r"^\s*(?:[-*+>]\s+|\d+[.)]\s+)+")
TABLE_ROW_RE = re.compile(r"^\|\s*\**\s*(?P<label>[^|*]+?)\s*\**\s*\|\s*(?P<value>.+?)\s*\|?\s*$")
LABEL_LINE_RE = re.compile(r"^\**\s*(?P<label>[^:*]{1,30}?)\s*\**\s*[:：]\s*\**\s*(?P<value>.+)$")
MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
BOLD_LINE_RE = re.compile(r"^\s*\*\*[^*]+\*\*\s*$")
TITLE_WORDS = re.compile(r"(분석\s*보고|보고서|report|요약|summary)\s*(—|-|:|$)", re.I)


def _is_heading(line):
    """# 제목이거나, 짧고 문장으로 끝나지 않는 굵은 줄(**장애 분석 보고**)을 제목으로 봅니다."""
    if MD_HEADING_RE.match(line):
        return True
    text = _plain(line)
    return bool(BOLD_LINE_RE.match(line)) and len(text) < 40 and not re.search(r"(다|요|음|함|됨|임)\.?$|\.$", text)


def _plain(text):
    text = re.sub(r"[*`]", "", text).strip()
    return text if len(text) <= 200 else text[:199] + "…"


def _clean(line):
    return LIST_MARK_RE.sub("", line).strip()


def _first_sentence(text):
    text = _plain(text)
    m = re.search(r"(다|요|음|함|됨|임)\.(\s|$)|\.\s", text)
    return text[:m.end()].strip() if m else text


def find_verdict(body):
    lines = [l for l in body.splitlines()]
    cleaned = [_clean(l) for l in lines]

    for line in cleaned:  # 1) 판정·결론 줄
        m = LABEL_LINE_RE.match(line)
        if m and re.fullmatch(VERDICT_LABELS, m.group("label").strip(), re.I):
            return _plain(m.group("value"))
    rows = [m for m in (TABLE_ROW_RE.match(l.strip()) for l in lines)
            if m and not re.fullmatch(r"[-:\s]+", m.group("value"))]
    for pattern in (VERDICT_LABELS, CAUSE_LABELS):  # 2) 요약 표의 판정 행, 없으면 근본 원인 행
        for m in rows:
            if re.fullmatch(r"\s*(\d+[.)]\s*)?" + pattern + r"(\s*\(.*\))?\s*", m.group("label"), re.I):
                return _plain(m.group("value"))
    for line in cleaned:  # 3) 근본 원인 항목
        m = LABEL_LINE_RE.match(line)
        if m and re.fullmatch(CAUSE_LABELS, m.group("label").strip(), re.I):
            return _first_sentence(m.group("value"))
    for i, line in enumerate(cleaned):  # 4) 근본 원인·결론 제목 아래 첫 문장
        if _is_heading(lines[i]) and re.search(VERDICT_LABELS + "|" + CAUSE_LABELS, line, re.I):
            for nxt in cleaned[i + 1:]:
                if nxt and not _is_heading(nxt) and not nxt.startswith(("|", "```", "---")):
                    return _first_sentence(nxt)
    for i, line in enumerate(cleaned):  # 5) 제목이 아닌 첫 문장
        if not line or line.startswith(("|", "```", "---")) or _is_heading(lines[i]):
            continue
        if TITLE_WORDS.search(_plain(line)) and len(_plain(line)) < 60:
            continue
        return _first_sentence(line)
    return ""


TYPE_LINE_RE = re.compile(r"^(?P<label>.*?)\s*\[(?P<key>[a-z_]+)\]$")
SUMMARY_SYS_KEYS = ("UPTIME", "LOAD AVERAGE", "TASKS", "CPUS", "MEMORY")


def summary_path(report_path):
    """리포트 옆에 두는 JSON 요약 파일 경로 (kdump-report-X.txt -> kdump-report-X.json)."""
    return report_path[:-len(".txt")] + ".json"


def load_summary(report_path):
    """analyze-kdump 1.16.0부터 리포트와 함께 만드는 JSON 요약을 화면에 쓸 만큼만 줄여 읽습니다. 없거나 깨졌으면 None."""
    try:
        with open(summary_path(report_path), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    ctype = data.get("crash_type") if isinstance(data.get("crash_type"), dict) else {}
    sysv = data.get("sys") if isinstance(data.get("sys"), dict) else {}

    def names(key):
        value = data.get(key)
        return [str(v) for v in value][:20] if isinstance(value, list) else []

    count = data.get("uninterruptible_tasks")
    return {
        "type": str(ctype.get("type") or ""), "label": str(ctype.get("label") or ""),
        "evidence": str(ctype.get("evidence") or ""), "panic": str(data.get("panic") or ""),
        "uninterruptible": count if isinstance(count, int) else None,
        "tainted": names("tainted_modules"), "modules": names("module_symbols"),
        "suspect": names("suspect_modules"), "os": str(data.get("os") or "linux"),
        "crash_exit": data.get("crash_exit") if isinstance(data.get("crash_exit"), int) else None,
        "sys": {k: str(sysv[k]) for k in SUMMARY_SYS_KEYS if k in sysv},
    }


def parse_result_head(path):
    """리포트·분석 파일 앞부분에서 기록 화면에 보일 정보를 읽습니다."""
    info = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(16384)
    except OSError:
        return info
    lines = head.splitlines()
    for line in lines[:14]:
        key, sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if sep and key in HEAD_KEYS:
            info[key] = value
        elif sep and key == "type" and not info.get("type"):
            # "type:      hung task (D 상태로 오래 멈춘 태스크) [hung_task]" (analyze-kdump 1.16.0부터)
            m = TYPE_LINE_RE.match(value)
            if m:
                info["type"], info["type_label"] = m.group("key"), m.group("label")
        elif sep and key == "evidence" and value:
            info["evidence"] = _plain(value)
    if "-analysis-" in os.path.basename(path):
        info["verdict"] = find_verdict(head.split("\n\n", 1)[-1])
    else:
        m = re.search(r'^\s*PANIC:\s*"?(.*?)"?\s*$', head, re.M)
        if m and m.group(1):
            info["panic"] = _plain(m.group(1))
        summary = load_summary(path)
        if summary:
            info["summary"] = {k: summary[k] for k in ("uninterruptible", "tainted", "crash_exit", "suspect")}
            if summary["type"] and not info.get("type"):
                info["type"], info["type_label"] = summary["type"], summary["label"]
    return info


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------- SSH

_SSH_EXTRA = None


def ssh_tool(name):
    """ssh·scp·ssh-keygen·ssh-add 실행 파일.

    Windows에서는 Windows OpenSSH(System32\\OpenSSH)를 먼저 씁니다. Git Bash 등에서 웹 UI를 실행하면 PATH에서
    Git의 ssh가 먼저 잡히는데, 그 ssh는 Windows의 ssh-agent 서비스를 보지 못해 암호를 건 키로 접속하지 못합니다.
    """
    if os.name == "nt":
        root = os.environ.get("SystemRoot") or r"C:\Windows"
        path = os.path.join(root, "System32", "OpenSSH", name + ".exe")
        if os.path.isfile(path):
            return path
    return name


# ---- 암호(passphrase)를 건 SSH 키 안내
# 웹 UI는 ssh를 BatchMode로 실행해 암호를 묻지 않습니다. 암호를 건 키는 ssh-agent에 등록돼 있어야 쓸 수 있는데,
# 등록하지 않으면 "Permission denied (publickey)"만 보여 원인을 알기 어렵습니다. 접속이 거부되면 키를 확인해 안내합니다.

_KEY_HINTS = {}          # 키 경로 -> (확인한 시각, 안내 문구)
KEY_HINT_TTL = 60


def key_has_passphrase(key):
    """키 파일에 암호가 걸려 있는지. 빈 암호로 공개 키를 꺼내 보고 '암호가 틀림'으로 실패하는지 봅니다."""
    try:
        r = subprocess.run([ssh_tool("ssh-keygen"), "-y", "-P", "", "-f", key], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode != 0 and b"passphrase" in r.stdout.lower()


def agent_fingerprints():
    """ssh-agent에 등록된 키의 지문 집합. ssh-agent에 접속할 수 없으면 None."""
    try:
        r = subprocess.run([ssh_tool("ssh-add"), "-l"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode == 2:
        return None          # ssh-agent가 꺼져 있거나 접속할 수 없음
    return {line.split()[1] for line in r.stdout.decode("utf-8", "replace").splitlines()
            if len(line.split()) >= 2 and line.split()[1].startswith(("SHA256:", "MD5:"))}


def key_fingerprint(key):
    """키의 지문(SHA256:...). 같은 이름의 .pub 파일에서 읽고, 없으면 None."""
    pub = key + ".pub"
    if not os.path.isfile(pub):
        return None
    try:
        r = subprocess.run([ssh_tool("ssh-keygen"), "-l", "-f", pub], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    parts = r.stdout.decode("utf-8", "replace").split()
    return parts[1] if r.returncode == 0 and len(parts) >= 2 else None


def passphrase_hint(server, now=None):
    """접속이 거부됐을 때 붙일 안내. 암호를 건 키가 ssh-agent에 없으면 해결 방법을, 아니면 빈 문자열."""
    key = server.get("key_file") or ""
    if not key or not os.path.isfile(key):
        return ""
    now = time.time() if now is None else now
    cached = _KEY_HINTS.get(key)
    if cached and now - cached[0] < KEY_HINT_TTL:
        return cached[1]
    hint = ""
    if key_has_passphrase(key):
        agent = agent_fingerprints()
        fingerprint = key_fingerprint(key)
        if os.name == "nt":
            start = ("ssh-agent 서비스가 꺼져 있으면 관리자 PowerShell에서 "
                     "Set-Service ssh-agent -StartupType Automatic; Start-Service ssh-agent 를 먼저 실행하세요. ")
            add = "PowerShell에서 ssh-add \"%s\" 를 한 번 실행해 암호를 입력하면, 재부팅 뒤에도 다시 등록할 필요가 없습니다." % key
        else:
            start = "ssh-agent가 없으면 웹 UI를 실행하는 셸에서 eval \"$(ssh-agent)\" 로 먼저 띄우세요. "
            add = "ssh-add \"%s\" 로 등록한 뒤 같은 셸에서 웹 UI를 실행하세요." % key
        if agent is None:
            hint = "SSH 키(%s)에 암호(passphrase)가 걸려 있는데 ssh-agent에 접속할 수 없습니다. %s%s" % (key, start, add)
        elif (fingerprint and fingerprint not in agent) or (not fingerprint and not agent):
            hint = "SSH 키(%s)에 암호(passphrase)가 걸려 있는데 ssh-agent에 등록돼 있지 않습니다. %s" % (key, add)
    _KEY_HINTS[key] = (now, hint)
    return hint


def with_ssh_hint(server, code, out):
    """접속이 거부된 출력(bytes)에 암호 키 안내를 덧붙입니다(ssh는 종료 코드 255, scp는 1)."""
    if code != 0 and b"Permission denied (publickey" in out:
        hint = passphrase_hint(server)
        if hint:
            out = out.rstrip(b"\r\n") + b"\n" + hint.encode("utf-8")
    return out


def ssh_extra_options():
    """로컬 ssh가 지원하는 경우에만 붙이는 옵션입니다.

    OpenSSH 10.1부터는 post-quantum 키 교환을 못 하는 서버(RHEL 9 계열 등)에 접속할 때마다 경고 3줄을
    출력합니다. 출력에 섞이면 가져온 리포트 맨 앞에 붙으므로 WarnWeakCrypto=no로 끕니다.
    옛 ssh는 모르는 옵션이면 접속 자체를 거부하므로 먼저 확인합니다.
    """
    global _SSH_EXTRA
    if _SSH_EXTRA is None:
        try:
            ok = subprocess.run([ssh_tool("ssh"), "-G", "-o", "WarnWeakCrypto=no", "kdump-tools-probe"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        _SSH_EXTRA = ["-o", "WarnWeakCrypto=no"] if ok else []
    return _SSH_EXTRA


def valid_ssh_target(target):
    """ssh 접속 대상: 비어 있거나 공백이 있거나 '-'로 시작하면 안 됩니다.
    '-'로 시작하면 ssh가 옵션(-oProxyCommand=... 등)으로 읽어 웹 UI를 실행한 컴퓨터에서 명령이 실행될 수 있습니다."""
    return bool(target) and not target.startswith("-") and not re.search(r"\s", target)


def ssh_args(server):
    if not valid_ssh_target(server.get("target") or ""):
        raise ApiError(400, "서버 '%s'의 접속 대상이 올바르지 않습니다. 서버 설정을 확인해 주세요." % server.get("name", ""))
    args = [ssh_tool("ssh"), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new"] + ssh_extra_options() + ["-p", str(server.get("port") or 22)]
    if server.get("key_file"):
        args += ["-i", server["key_file"]]
    return args + [server["target"]]


PREPARE_TIMEOUT = 7200       # 서버 준비·설치(패키지 내려받기 포함)의 최대 실행 시간(초)
KILL_GRACE = 30              # 원격 timeout이 보낸 종료 신호를 무시할 때 강제 종료까지 기다리는 시간(초)


# 원격 명령을 새 세션(프로세스 그룹)에서 실행하고, 제한 시간이 지나면 그룹 전체에 TERM, 잠시 뒤 KILL을 보냅니다.
# coreutils timeout은 구현마다 다릅니다(Ubuntu 26.04의 uutils timeout은 KILL을 자식 하나에만 보내 TERM을 무시한
# 손자 프로세스가 남습니다). 그래서 setsid와 kill만으로 직접 처리합니다. 시간 초과면 124로 끝납니다.
# ssh 연결이 끊겨도 감시 프로세스는 따로 남아 제한 시간에 명령을 끝냅니다.
REMOTE_TIMEOUT = r"""
limit=$1 grace=$2
shift 2
# 백그라운드 명령의 표준 입력은 /dev/null로 바뀌므로, 원래 입력(설치 번들 등)을 fd 3으로 넘깁니다.
exec 3<&0
setsid "$@" 0<&3 3<&- &
pid=$!
exec 3<&-
setsid sh -c 'sleep "$1"; kill -s TERM -- "-$3" 2>/dev/null || exit 0; sleep "$2"; kill -s KILL -- "-$3" 2>/dev/null' \
    sh "$limit" "$grace" "$pid" </dev/null >/dev/null 2>&1 3<&- &
watcher=$!
wait "$pid"
rc=$?
kill -s KILL -- "-$watcher" 2>/dev/null
case $rc in 137|143) exit 124 ;; esac
exit "$rc"
"""


# 원격 스크립트 앞에 붙이는 설치 위치 보정입니다. 경로가 새 기본 설치 위치(/opt/kdump-analyzer) 아래인데
# 그 서버에는 예전 기본 위치(/opt/kdump-tools)에만 설치돼 있으면(1.19.0 이전에 설치한 서버) 예전 위치의 같은 경로로 바꿉니다.
INSTALL_FALLBACK_SH = r"""
legacy_path() {
  case "$1" in
    /opt/kdump-analyzer/*)
      if [ ! -e /opt/kdump-analyzer/bin/analyze-kdump ] && [ -x /opt/kdump-tools/bin/analyze-kdump ]; then
        echo "/opt/kdump-tools/${1#/opt/kdump-analyzer/}"
        return
      fi
      ;;
  esac
  echo "$1"
}
"""


def with_install_fallback(script, arg):
    """script의 arg번째 인자(1 또는 2, 원격 도구 경로나 vmlinux 디렉터리)를 legacy_path로 보정합니다."""
    fix = {1: '_p=$(legacy_path "$1"); shift; set -- "$_p" "$@"\n',
           2: '_a=$1; _p=$(legacy_path "$2"); shift 2; set -- "$_a" "$_p" "$@"\n'}[arg]
    return INSTALL_FALLBACK_SH + fix + script


def with_remote_timeout(argv, seconds):
    return ["sh", "-c", REMOTE_TIMEOUT, "sh", str(int(seconds)), str(KILL_GRACE)] + list(argv)


def crash_timeout_seconds(settings):
    try:
        minutes = int(settings.get("crash_timeout") or DEFAULT_SETTINGS["crash_timeout"])
    except (TypeError, ValueError):
        minutes = DEFAULT_SETTINGS["crash_timeout"]
    return max(1, min(minutes, 1440)) * 60


def human_duration(seconds):
    seconds = int(seconds)
    if seconds % 3600 == 0:
        return "%d시간" % (seconds // 3600)
    if seconds % 60 == 0:
        return "%d분" % (seconds // 60)
    return "%d초" % seconds


def remote_command(server, argv):
    command = " ".join(shlex.quote(a) for a in argv)
    return ("sudo -n " + command) if server.get("sudo") and not is_windows(server) else command


def is_windows(server):
    return (server or {}).get("os") == "windows"


def split_stream(buffer):
    """출력 버퍼를 ([(줄, 구분자)], 남은 버퍼)로 나눕니다. 구분자는 "\\n"(완성된 줄) 또는 "\\r"(진행 표시 갱신).

    Windows 서버의 출력은 줄 끝이 \\r\\n이라 이것도 완성된 줄("\\n")로 봅니다. 버퍼 끝의 \\r은 다음 조각이
    \\n으로 시작할 수 있으므로 남겨 둡니다.
    """
    pieces = []
    while True:
        match = re.search(r"\r\n|[\r\n]", buffer)
        if not match:
            break
        if match.group() == "\r" and match.end() == len(buffer):
            break
        sep = "\r" if match.group() == "\r" else "\n"
        pieces.append((buffer[:match.start()], sep))
        buffer = buffer[match.end():]
    return pieces, buffer


def valid_vmcore_path(server, path):
    """덤프 경로가 서버 운영체제의 절대 경로인지 확인합니다 (Linux /..., Windows C:\\...)."""
    if not isinstance(path, str) or not path or "\n" in path or "\r" in path or "\0" in path:
        return False
    if is_windows(server):
        return re.match(r"^[A-Za-z]:\\", path) is not None
    return path.startswith("/")


def ps_quote(value):
    """PowerShell 작은따옴표 문자열 (작은따옴표는 두 번 씁니다)."""
    return "'" + str(value).replace("'", "''") + "'"


# Windows 원격 명령은 powershell -EncodedCommand로 보냅니다. Windows의 sshd는 명령을 cmd.exe로 넘기는데,
# base64에는 따옴표가 필요한 문자가 없어 인용 문제가 생기지 않습니다. cmd.exe 명령 길이 제한(8191자)이 있어
# 짧은 스크립트만 이렇게 보내고, 분석 스크립트 자체는 표준 입력으로 보냅니다.
WIN_PRELUDE = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$ProgressPreference='SilentlyContinue';"
# analyze-windump.ps1의 Find-Cdb와 같은 순서로 cdb.exe를 찾습니다.
WIN_FIND_CDB = r"""function Find-Cdb{foreach($p in @(${env:ProgramFiles(x86)},$env:ProgramFiles)){if($p){$c=Join-Path $p 'Windows Kits\10\Debuggers\x64\cdb.exe';if(Test-Path -LiteralPath $c){return $c}}};$g=Get-Command cdb.exe -ErrorAction SilentlyContinue;if($g){return $g.Source};return $null};"""
# 덤프 디렉터리(기본 C:\Windows)의 *.dmp(MEMORY.DMP)와 Minidump\*.dmp
WIN_DUMPS = r"""function Get-Dumps($d){@(Get-ChildItem -LiteralPath $d -Filter *.dmp -File -ErrorAction SilentlyContinue)+@(Get-ChildItem -LiteralPath (Join-Path $d 'Minidump') -Filter *.dmp -File -ErrorAction SilentlyContinue)|Where-Object{$_ -and $_.Length -gt 0}|Sort-Object FullName -Unique};"""


def win_argv(script):
    data = (WIN_PRELUDE + script).encode("utf-16-le")
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-EncodedCommand", base64.b64encode(data).decode("ascii")]


def fetch_remote_file(server, path, timeout=120):
    """원격 파일 내용을 바이트로 가져옵니다. Windows는 콘솔 인코딩을 거치지 않도록 base64로 받습니다."""
    if not is_windows(server):
        return ssh_run(server, ["cat", path], timeout=timeout, data=True)
    code, data = ssh_run(server, win_argv("[Convert]::ToBase64String([IO.File]::ReadAllBytes(%s))" % ps_quote(path)),
                         timeout=timeout, data=True)
    if code != 0:
        return code, data
    try:
        return 0, base64.b64decode(b"".join(data.split()), validate=True)
    except ValueError:  # binascii.Error 포함
        return 1, data


def ssh_run(server, argv, stdin=None, timeout=60, data=False):
    """원격 명령을 실행하고 (종료 코드, 출력)을 돌려줍니다.

    data=True면 파일 내용처럼 표준 출력만 돌려줍니다. ssh 자체의 경고·오류(표준 오류)가 내용에 섞이지 않게
    하려는 것이고, 실패했을 때만 표준 오류를 덧붙입니다.
    """
    # 보낼 입력이 없으면 표준 입력을 반드시 막습니다. 물려받은 입력이 열려 있으면
    # Windows의 ssh는 입력이 끝나기를 기다리며 원격 명령이 끝난 뒤에도 종료하지 않습니다.
    stdin_args = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    try:
        result = subprocess.run(ssh_args(server) + [remote_command(server, argv)], **stdin_args,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE if data else subprocess.STDOUT, timeout=timeout)
        if data and result.returncode != 0:
            return result.returncode, with_ssh_hint(server, result.returncode, result.stdout + result.stderr)
        return result.returncode, with_ssh_hint(server, result.returncode, result.stdout)
    except subprocess.TimeoutExpired:
        return 124, b"SSH timeout"
    except OSError as error:
        return 127, ("ssh를 실행할 수 없습니다: %s" % error).encode()


def ssh_text(server, argv, timeout=60):
    code, out = ssh_run(server, argv, timeout=timeout)
    return code, out.decode("utf-8", errors="replace")


def probe_method(server):
    if is_windows(server):
        code, out = ssh_text(server, win_argv(WIN_FIND_CDB + "if(Test-Path -LiteralPath %s){'installed'}elseif(Find-Cdb){'upload'}else{'none'}"
                                              % ps_quote(server["tool"])), timeout=30)
        out = out.strip().splitlines()[-1:] or [""]
        return out[0] if code == 0 else ""
    code, out = ssh_text(server, ["sh", "-c", with_install_fallback(
                                  # 원격 경로가 명령 이름(analyze-kdump)이면 등록된 위치로 풉니다.
                                  'case "$1" in */*) t=$1 ;; *) t=$(command -v "$1" 2>/dev/null || printf %s "$1") ;; esac; '
                                  'if [ -x "$t" ]; then echo installed; '
                                  'elif command -v crash >/dev/null 2>&1; then echo upload; '
                                  'else echo none; fi', 1), "sh", server["tool"]], timeout=30)
    out = out.strip().splitlines()[-1:] or [""]
    return out[0] if code == 0 else ""


def test_server(server):
    if is_windows(server):
        return win_test_server(server)
    code, out = ssh_text(server, ["sh", "-c", with_install_fallback("""
echo "host=$(hostname)"; echo "user=$(id -un)"
# 원격 경로가 경로가 아닌 명령 이름(analyze-kdump)이면 등록된 위치로 풉니다.
case "$1" in */*) t=$1 ;; *) t=$(command -v "$1" 2>/dev/null || printf %s "$1") ;; esac
if [ -x "$t" ]; then echo "tool=$("$t" --version 2>/dev/null | grep '^analyze-kdump ' | head -n 1)"; [ -n "$("$t" --version 2>/dev/null | grep '^analyze-kdump ')" ] || echo "tool=installed (version unknown)"; else echo "tool="; fi
# crash --version은 실행 중 /dev/mem을 열어 보다 Secure Boot lockdown 경고를 커널 로그에 남기므로 패키지 정보로 버전을 읽습니다.
if command -v crash >/dev/null 2>&1; then v=$(rpm -q --qf '%{VERSION}-%{RELEASE}' crash 2>/dev/null) || v=$(dpkg-query -W -f='${Version}' crash 2>/dev/null) || v=; echo "crash=crash ${v:-installed}"; else echo "crash="; fi
echo "vmcores=$(for f in "$2"/*/vmcore "$2"/*/vmcore.flat "$2"/*/dump.[0-9]*; do [ -f "$f" ] || continue; case "$f" in */vmcore) ;; *) [ -f "${f%/*}/vmcore" ] && continue ;; esac; echo "$f"; done | wc -l)"
""", 1), "sh", server["tool"], server["crash_dir"]], timeout=40)
    info = {"ok": code == 0, "raw": out.strip()[-600:]}
    for line in out.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    if code == 0:
        info["method"] = "installed" if info.get("tool") else ("upload" if info.get("crash") else "none")
    return info


# SSH로 받은 RHEL 덤프는 <디렉터리>/vmcore.flat입니다. crash가 읽지 못해 같은 디렉터리의 vmcore로 변환했으면
# vmcore가 있는 디렉터리의 vmcore.flat·dump.*는 목록에서 뺍니다.
DUMP_LIST_SH = ('for f in "$1"/*/vmcore "$1"/*/vmcore.flat "$1"/*/dump.[0-9]*; do [ -f "$f" ] || continue; case "$f" in */vmcore) ;; *) [ -f "${f%/*}/vmcore" ] && continue ;; esac; '
                'stat -c "%Y %s %n" "$f"; done | sort -rn')


def list_vmcores(server):
    if is_windows(server):
        code, out = ssh_text(server, win_argv(WIN_DUMPS + "Get-Dumps %s|Sort-Object LastWriteTime -Descending|ForEach-Object{'{0} {1} {2}' -f [int64](($_.LastWriteTimeUtc-[datetime]'1970-01-01').TotalSeconds),$_.Length,$_.FullName}"
                                              % ps_quote(server["crash_dir"])), timeout=40)
        if code != 0:
            raise ApiError(502, "덤프 목록을 읽지 못했습니다: %s" % out.strip()[-300:])
        items = []
        for line in out.splitlines():
            parts = line.strip().split(" ", 2)
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                items.append({"mtime": int(parts[0]), "size": int(parts[1]), "path": parts[2]})
        return items
    # 덤프 파일 이름: RHEL·SUSE는 <디렉터리>/vmcore, Ubuntu·Debian(kdump-tools)은 <YYYYMMDDHHMM>/dump.<YYYYMMDDHHMM>
    code, out = ssh_text(server, ["sh", "-c", DUMP_LIST_SH,
                                  "sh", server["crash_dir"]], timeout=40)
    if code != 0:
        raise ApiError(502, "vmcore 목록을 읽지 못했습니다: %s" % out.strip()[-300:])
    items = []
    for line in out.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[0].isdigit():
            items.append({"mtime": int(parts[0]), "size": int(parts[1]), "path": parts[2]})
    return items


# ---------------------------------------------------------------- 덤프 보관 관리
# 덤프 디렉터리의 남은 공간, 덤프 삭제, 덤프를 웹 UI로 받기.
# 삭제와 받기는 덤프 디렉터리 안의 파일만 다룹니다. 화면에서 고른 경로라도 서버에서 실제 경로(심볼릭 링크 해석)로
# 다시 확인합니다.

# $1 덤프 디렉터리 -> "전체바이트 남은바이트"
DUMP_DISK_SH = 'df -Pk "$1" 2>/dev/null | awk \'NR == 2 { printf "%.0f %.0f\\n", $2 * 1024, $4 * 1024 }\''

# $1 덤프 디렉터리, $2 덤프 파일. 덤프 디렉터리 바로 아래 파일이면 그 파일만, 한 단계 아래(<디렉터리>/vmcore)면
# 그 디렉터리(vmcore-dmesg.txt 등 함께 저장된 파일 포함)를 지웁니다.
REMOTE_DUMP_DELETE = r"""
d=$(readlink -f "$1" 2>/dev/null); f=$(readlink -f "$2" 2>/dev/null)
if [ -z "$d" ] || [ "$d" = / ]; then echo "덤프 디렉터리가 올바르지 않습니다: $1"; exit 4; fi
if [ -z "$f" ] || [ ! -f "$f" ]; then echo "덤프가 없습니다: $2"; exit 3; fi
case "$f" in
  "$d"/*) ;;
  *) echo "덤프 디렉터리($d) 밖의 파일은 지우지 않습니다: $f"; exit 4 ;;
esac
parent=$(dirname "$f")
if [ "$parent" = "$d" ]; then
  rm -f -- "$f" || exit 5
  echo "삭제했습니다: $f"
elif [ "$(dirname "$parent")" = "$d" ]; then
  rm -rf -- "$parent" || exit 5
  echo "삭제했습니다: $parent/ (덤프와 함께 저장된 파일 포함)"
else
  echo "덤프 디렉터리의 한 단계 아래까지만 지웁니다: $f"; exit 4
fi
"""

# $1 덤프 디렉터리, $2 덤프 파일 -> 파일 내용(표준 출력). 웹 UI로 받을 때 씁니다(sudo로 읽기 위해 scp 대신).
REMOTE_DUMP_CAT = r"""
d=$(readlink -f "$1" 2>/dev/null); f=$(readlink -f "$2" 2>/dev/null)
if [ -z "$d" ] || [ "$d" = / ] || [ -z "$f" ] || [ ! -f "$f" ]; then echo "덤프가 없습니다: $2" >&2; exit 3; fi
case "$f" in "$d"/*) ;; *) echo "덤프 디렉터리 밖의 파일은 보내지 않습니다: $f" >&2; exit 4 ;; esac
exec cat -- "$f"
"""

WIN_DUMP_CHECK = r"""function Test-InDumpDir($dir,$file){$d=(Resolve-Path -LiteralPath $dir -ErrorAction Stop).Path.TrimEnd('\');$f=(Resolve-Path -LiteralPath $file -ErrorAction Stop).Path
if($d.Length -le 3){throw "덤프 디렉터리가 드라이브 바로 아래라 지우지 않습니다: $d"}
if(-not $f.StartsWith($d+'\',[StringComparison]::OrdinalIgnoreCase)){throw "덤프 디렉터리($d) 밖의 파일은 다루지 않습니다: $f"}
if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "덤프가 없습니다: $f"};return $f};"""


def dump_in_dir(server, path):
    """화면에서 받은 덤프 경로가 서버 덤프 디렉터리 안인지 먼저 확인합니다(서버에서 다시 확인함)."""
    if not valid_vmcore_path(server, path):
        return False
    base = server["crash_dir"].rstrip("\\/")
    sep = "\\" if is_windows(server) else "/"
    if is_windows(server):
        return path.lower().startswith(base.lower() + sep) and ".." not in path.split(sep)
    return path.startswith(base + sep) and ".." not in path.split(sep)


def dump_disk(server):
    """덤프 디렉터리가 있는 디스크의 전체·남은 크기(바이트). 읽지 못하면 None."""
    if is_windows(server):
        code, out = ssh_text(server, win_argv("$v=(Get-Item -LiteralPath %s -ErrorAction Stop).PSDrive;'{0} {1}' -f ($v.Used+$v.Free),$v.Free"
                                              % ps_quote(server["crash_dir"])), timeout=40)
    else:
        code, out = ssh_text(server, ["sh", "-c", DUMP_DISK_SH, "sh", server["crash_dir"]], timeout=40)
    match = re.search(r"(\d+) (\d+)\s*$", out.strip()) if code == 0 else None
    if not match:
        return None
    return {"total": int(match.group(1)), "free": int(match.group(2))}


def delete_dump(server, path):
    """덤프를 지웁니다. (성공 여부, 서버가 남긴 메시지)"""
    if not dump_in_dir(server, path):
        raise ApiError(400, "덤프 디렉터리(%s) 안의 덤프만 지울 수 있습니다." % server["crash_dir"])
    if is_windows(server):
        argv = win_argv(WIN_DUMP_CHECK + "try{$f=Test-InDumpDir %s %s;Remove-Item -LiteralPath $f -Force -ErrorAction Stop;\"삭제했습니다: $f\"}catch{$_.Exception.Message;exit 4}"
                        % (ps_quote(server["crash_dir"]), ps_quote(path)))
    else:
        argv = ["sh", "-c", REMOTE_DUMP_DELETE, "sh", server["crash_dir"], path]
    code, out = ssh_text(server, argv, timeout=120)
    return code == 0, out.strip()[-500:]


def local_dump_name(server, path):
    """웹 UI 데이터 폴더에 저장할 파일 이름: <서버>/<상위 디렉터리>-<파일> (예: db01/10.0.0.11-2026-11-09-vmcore)."""
    parts = [p for p in re.split(r"[\\/]", path) if p]
    name = "-".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def scp_download_args(server, remote_path, local_path):
    """Windows 서버의 파일을 scp로 받는 명령. Windows OpenSSH는 /C:/... 형태의 경로를 받습니다."""
    ssh = ssh_args(server)
    options = ["-P" if o == "-p" else o for o in ssh[1:-1]]
    user, _, host = ssh[-1].rpartition("@")
    if ":" in host:
        host = "[%s]" % host
    remote = "/" + remote_path.replace("\\", "/")
    return [ssh_tool("scp"), "-q"] + options + ["%s%s:%s" % (user + "@" if user else "", host, remote), local_path]


# ---------------------------------------------------------------- 버전과 업그레이드

def git(*args, timeout=30):
    try:
        result = subprocess.run(["git", "-c", "safe.directory=*", "-C", REPO_DIR] + list(args),
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeout)
        return result.returncode, result.stdout.decode("utf-8", errors="replace").strip()
    except subprocess.TimeoutExpired:
        return 124, "git 시간 초과"
    except OSError:
        return 127, "git이 설치되어 있지 않습니다."


def local_info():
    """웹 UI로 실행 중인 kdump-analyzer(웹 UI와 무설치 실행에 쓰는 스크립트)의 버전."""
    info = {"version": version_text(), "commit": "", "branch": "", "git": False, "dirty": False}
    code, out = git("rev-parse", "HEAD")
    if code == 0 and re.fullmatch(r"[0-9a-f]{40}", out):
        info.update(git=True, commit=out)
        info["branch"] = git("rev-parse", "--abbrev-ref", "HEAD")[1]
        info["dirty"] = bool(git("status", "--porcelain", "--untracked-files=no")[1])
    return info


def _http_get(url, accept=None, timeout=8):
    headers = {"User-Agent": "kdump-analyzer-webui"}
    if accept:
        headers["Accept"] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as res:
        return res.read()


def update_source(settings):
    """설정에서 업데이트 저장소, 채널(release|branch), 브랜치를 읽습니다."""
    repo = settings.get("update_repo") or DEFAULT_SETTINGS["update_repo"]
    branch = settings.get("update_branch") or DEFAULT_SETTINGS["update_branch"]
    channel = settings.get("update_channel") or DEFAULT_SETTINGS["update_channel"]
    if channel not in UPDATE_CHANNELS:
        channel = DEFAULT_SETTINGS["update_channel"]
    return repo, channel, branch


def latest_release_tag(repo):
    """GitHub의 최신 릴리스(초안·프리릴리스 제외) 태그와 정보를 읽습니다."""
    try:
        data = json.loads(_http_get("https://api.github.com/repos/%s/releases/latest" % repo,
                                    "application/vnd.github+json"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ValueError("이 저장소에는 아직 릴리스가 없습니다. 업데이트 채널을 '브랜치'로 바꿔 주세요.")
        raise
    tag = data.get("tag_name") or ""
    if not BRANCH_RE.match(tag):
        raise ValueError("릴리스 태그를 읽지 못했습니다.")
    return tag, data.get("name") or tag, data.get("html_url") or ""


def fetch_latest(repo, channel, branch, base=""):
    """GitHub에서 최신 릴리스 태그(또는 브랜치)의 커밋과 VERSION을 읽습니다.
    base가 있으면 그 뒤의 커밋 제목도 가져옵니다."""
    if not REPO_RE.match(repo or "") or not BRANCH_RE.match(branch or ""):
        return {"ok": False, "error": "업데이트 저장소나 브랜치 형식이 올바르지 않습니다."}
    result = {"ok": False, "repo": repo, "channel": channel, "branch": branch, "checked": time.time()}
    try:
        if channel == "release":
            tag, name, url = latest_release_tag(repo)
            result.update(ref=tag, ref_kind="tags", tag=tag, release_name=name, release_url=url)
        else:
            result.update(ref=branch, ref_kind="heads")
        sha = _http_get("https://api.github.com/repos/%s/commits/%s" % (repo, urllib.parse.quote(result["ref"], safe="")),
                        "application/vnd.github.sha").decode().strip()
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("커밋 값을 읽지 못했습니다.")
        version = _http_get("https://raw.githubusercontent.com/%s/%s/VERSION" % (repo, sha)).decode()
        result.update(ok=True, commit=sha, version=version.splitlines()[0].strip() if version else "unknown")
    except Exception as error:  # noqa: BLE001 - 네트워크 오류는 화면에 그대로 보여줍니다.
        result["error"] = "GitHub에 접속하지 못했습니다: %s" % error
        return result
    if base and re.fullmatch(r"[0-9a-f]{7,40}", base) and not sha.startswith(base):
        try:
            data = json.loads(_http_get("https://api.github.com/repos/%s/compare/%s...%s" % (repo, base, sha)))
            result["ahead"] = data.get("ahead_by")
            result["changes"] = [{"sha": c.get("sha", "")[:7],
                                  "title": (c.get("commit", {}).get("message") or "").splitlines()[0]}
                                 for c in reversed(data.get("commits", [])[-30:])]
        except Exception:  # noqa: BLE001 - 변경 내역은 없어도 됩니다.
            pass
    return result


def self_update(settings):
    """웹 UI의 저장소를 갱신합니다. 릴리스 채널은 최신 릴리스 태그로, 브랜치 채널은 git pull로 fast-forward합니다."""
    repo, channel, branch = update_source(settings)
    info = local_info()
    if not info["git"]:
        raise ApiError(400, "웹 UI가 git 저장소에서 실행되고 있지 않아 자동으로 업데이트할 수 없습니다. "
                            "GitHub에서 새로 받아 주세요.")
    if info["dirty"]:
        raise ApiError(409, "저장소에 커밋하지 않은 변경이 있어 업데이트하지 않았습니다. "
                            "변경을 정리한 뒤 다시 시도해 주세요.")
    if info["branch"] != branch:
        raise ApiError(409, "현재 브랜치(%s)가 업데이트 브랜치(%s)와 달라 업데이트하지 않았습니다." % (info["branch"], branch))
    before = info["commit"]
    if channel == "release":
        try:
            tag = latest_release_tag(repo)[0]
        except Exception as error:  # noqa: BLE001
            raise ApiError(502, "최신 릴리스를 확인하지 못했습니다: %s" % error)
        code, out = git("fetch", "--quiet", "https://github.com/%s.git" % repo,
                        "+refs/tags/%s:refs/tags/%s" % (tag, tag), timeout=180)
        if code != 0:
            raise ApiError(502, "릴리스 태그 %s를 받지 못했습니다:\n%s" % (tag, out[-800:]))
        if git("merge-base", "--is-ancestor", "refs/tags/%s" % tag, "HEAD")[0] == 0:
            raise ApiError(409, "이미 릴리스 %s와 같거나 더 새로운 버전입니다." % tag)
        code, out = git("merge", "--ff-only", "refs/tags/%s" % tag, timeout=180)
        what = "릴리스 %s로 fast-forward" % tag
    else:
        code, out = git("pull", "--ff-only", timeout=180)
        what = "git pull"
    after = local_info()
    if code != 0:
        raise ApiError(502, "%s이(가) 실패했습니다:\n%s" % (what, out[-800:]))
    changed = git("diff", "--name-only", before, after["commit"])[1].splitlines() if after["commit"] != before else []
    return {"ok": True, "output": out[-2000:], "before": before, "local": after, "changed": changed,
            "restart": any(f.startswith("webui/") and f.endswith(".py") for f in changed)}


def server_version(server):
    """원격 서버에 설치된 analyze-kdump의 버전과 설치 정보."""
    if is_windows(server):
        return win_server_version(server)
    code, out = ssh_text(server, ["sh", "-c", with_install_fallback("""
t=$(command -v "$1" 2>/dev/null || true)
if [ -n "$t" ] && [ -x "$t" ]; then
  "$t" --version 2>/dev/null | grep -m 1 '^analyze-kdump ' | sed 's/^/version=/'
  d=$(dirname "$(dirname "$(readlink -f "$t")")")
  echo "prefix=$d"
  grep -E '^(SOURCE|INSTALLED_AT|BIN_DIR)=' "$d/.install-info" 2>/dev/null
else
  echo "version="
fi
""", 1), "sh", server["tool"]], timeout=40)
    info = {"ok": code == 0, "server": server["name"]}
    if code != 0:
        info["error"] = (out.strip().splitlines() or ["SSH 접속 실패"])[-1][-300:]
        return info
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in ("version", "prefix", "SOURCE", "INSTALLED_AT", "BIN_DIR"):
            info[key.lower()] = value.strip()
    info["installed"] = bool(info.get("version"))
    match = TOOL_VERSION_RE.match(info.get("version", ""))
    if match:
        info["version"], info["commit"] = match.group(1), match.group(2) or ""
        if not info.get("installed_at"):
            info["installed_at"] = match.group(3) or ""
    return info


# ---------------------------------------------------------------- 서버 준비 (kdump 환경 점검·설치)

# 점검만 합니다(바꾸는 것 없음). $1 crash 디렉터리, $2 vmlinux 보관 디렉터리
REMOTE_CHECK = with_install_fallback(r"""
. /etc/os-release 2>/dev/null
echo "os_id=${ID:-}"; echo "os_like=${ID_LIKE:-}"; echo "os_name=${PRETTY_NAME:-}"; echo "codename=${VERSION_CODENAME:-}"
k=$(uname -r); echo "kernel=$k"; echo "uid=$(id -u)"
if command -v dnf >/dev/null 2>&1; then pm=dnf; elif command -v yum >/dev/null 2>&1; then pm=yum
elif command -v apt-get >/dev/null 2>&1; then pm=apt; elif command -v zypper >/dev/null 2>&1; then pm=zypper; else pm=; fi
echo "pkg=$pm"
if command -v kdumpctl >/dev/null 2>&1; then
  echo "kdump_tool=kdumpctl"; svc=kdump
  if kdumpctl status >/dev/null 2>&1; then echo "kdump_ready=1"; else echo "kdump_ready=0"; fi
  next=$(grubby --info=DEFAULT 2>/dev/null | grep -o 'crashkernel=[^ "]*' | head -n 1)
elif command -v kdump-config >/dev/null 2>&1; then
  echo "kdump_tool=kdump-config"; svc=kdump-tools
  # "Not ready to kdump"도 "ready to kdump"를 포함하므로 상태 줄 전체를 맞춥니다.
  if kdump-config status 2>/dev/null | grep -Eqi "current state[[:space:]]*:[[:space:]]*ready to kdump"; then echo "kdump_ready=1"; else echo "kdump_ready=0"; fi
  echo "use_kdump=$(sed -n 's/^USE_KDUMP=//p' /etc/default/kdump-tools 2>/dev/null | tr -d '\"' | tail -n 1)"
  next=$(cat /etc/default/grub /etc/default/grub.d/*.cfg 2>/dev/null | grep -v '^[[:space:]]*#' | grep -o 'crashkernel=[^ "]*' | tail -n 1)
else
  echo "kdump_tool="; svc=; next=
fi
if [ -n "$svc" ]; then echo "kdump_active=$(systemctl is-active $svc 2>/dev/null)"; echo "kdump_enabled=$(systemctl is-enabled $svc 2>/dev/null)"; fi
echo "crashkernel_now=$(grep -o 'crashkernel=[^ ]*' /proc/cmdline | head -n 1)"
echo "crashkernel_next=$next"
echo "crashkernel_bytes=$(cat /sys/kernel/kexec_crash_size 2>/dev/null)"
# crash --version은 실행 중 /dev/mem을 열어 보다 Secure Boot lockdown 경고를 커널 로그에 남기므로 패키지 정보로 버전을 읽습니다.
if command -v crash >/dev/null 2>&1; then v=$(rpm -q --qf '%{VERSION}-%{RELEASE}' crash 2>/dev/null) || v=$(dpkg-query -W -f='${Version}' crash 2>/dev/null) || v=; echo "crash=crash ${v:-installed}"; else echo "crash="; fi
v=
for p in "/usr/lib/debug/lib/modules/$k/vmlinux" "/usr/lib/debug/boot/vmlinux-$k" "$2/$k/vmlinux"; do
  if [ -f "$p" ]; then v=$p; break; fi
done
echo "vmlinux=$v"
echo "mem_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
echo "swap_kb=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)"
d="$1"; while [ -n "$d" ] && [ ! -d "$d" ]; do d=$(dirname "$d"); done
echo "disk_kb=$(df -Pk "${d:-/}" 2>/dev/null | awk 'NR == 2 {print $4}')"
""", 2)

# 설치 동작 하나를 실행합니다. $1 동작, $2 vmlinux 보관 디렉터리
REMOTE_PREPARE = with_install_fallback(r"""
action="$1"
. /etc/os-release 2>/dev/null
k=$(uname -r)
[ "$(id -u)" -eq 0 ] || { echo "root 권한이 필요합니다. 서버 설정에서 sudo를 켜 주세요(비밀번호 없는 sudo 필요)."; exit 4; }
if command -v dnf >/dev/null 2>&1; then pm=dnf; elif command -v yum >/dev/null 2>&1; then pm=yum
elif command -v apt-get >/dev/null 2>&1; then pm=apt; else echo "지원하지 않는 배포판입니다(dnf·yum·apt-get 없음)."; exit 10; fi
export DEBIAN_FRONTEND=noninteractive
apt_get() { apt-get -q -y -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confold "$@"; }
updated=0
apt_update() { [ "$updated" = 1 ] || { apt_get update && updated=1; }; }
case "$action" in
crash)
  if [ "$pm" = apt ]; then apt_update && apt_get install crash; else $pm -y install crash; fi
  ;;
kdump)
  if [ "$pm" = apt ]; then
    echo "kdump-tools kdump-tools/use_kdump boolean true" | debconf-set-selections
    apt_update && apt_get install kdump-tools kexec-tools makedumpfile || exit 1
    [ -f /etc/default/kdump-tools ] && sed -i 's/^USE_KDUMP=.*/USE_KDUMP=1/' /etc/default/kdump-tools
    systemctl enable kdump-tools
    svc=kdump-tools
  else
    $pm -y install kexec-tools || exit 1
    systemctl enable kdump
    svc=kdump
  fi
  if [ "$(cat /sys/kernel/kexec_crash_size 2>/dev/null || echo 0)" -gt 0 ]; then
    # crashkernel이 이미 예약되어 있으면 서비스를 다시 시작해 재부팅 없이 바로 준비 상태로 만듭니다.
    if ! systemctl restart "$svc"; then
      echo "kdump 서비스를 시작하지 못했습니다. 원인: journalctl -u $svc -b --no-pager | tail -30"
      journalctl -u "$svc" -b --no-pager 2>/dev/null | tail -15
      exit 1
    fi
    echo "kdump 서비스를 다시 시작했습니다."
    if command -v kdump-config >/dev/null 2>&1; then kdump-config status; else kdumpctl status; fi
  else
    echo "kdump는 crashkernel 메모리가 예약된 뒤(재부팅 후)부터 동작합니다."
  fi
  ;;
crashkernel)
  if command -v grubby >/dev/null 2>&1; then
    v=$(kdumpctl get-default-crashkernel 2>/dev/null)
    [ -n "$v" ] || v=auto
    echo "crashkernel=$v (모든 커널)"
    grubby --update-kernel=ALL --args="crashkernel=$v" || exit 1
  elif [ "$pm" = apt ]; then
    # 패키지 기본값은 2G부터라 메모리 2GB 서버에서는 예약되지 않으므로 1G부터 잡습니다.
    v="1G-4G:320M,4G-32G:512M,32G-64G:1024M,64G-128G:2048M,128G-:4096M"
    f=/etc/default/grub.d/kdump-tools.cfg
    mkdir -p /etc/default/grub.d
    if [ -f "$f" ] && grep -q 'crashkernel=' "$f"; then
      sed -i "s/crashkernel=[^ \"']*/crashkernel=$v/" "$f"
    else
      echo "GRUB_CMDLINE_LINUX_DEFAULT=\"\$GRUB_CMDLINE_LINUX_DEFAULT crashkernel=$v\"" > "$f"
    fi
    echo "$f:"; cat "$f"
    update-grub || exit 1
  else
    echo "crashkernel을 자동으로 설정할 수 없는 배포판입니다."; exit 10
  fi
  echo "재부팅해야 적용됩니다."
  ;;
debuginfo)
  # 디버그 패키지는 수백 MB~2GB라 받는 동안 화면이 멈춘 것처럼 보이므로, 받은 크기를 10초마다 알립니다.
  ( while sleep 10; do
      mb=$(du -sm /var/cache/apt/archives/partial /var/cache/dnf /var/cache/yum 2>/dev/null | awk '{s += $1} END {print s + 0}')
      echo "내려받는 중: ${mb} MB"
    done ) &
  watcher=$!
  trap 'kill $watcher 2>/dev/null' EXIT
  if [ "$pm" = apt ]; then
    case "${ID:-}" in
    ubuntu)
      # 키링 설치는 실패해도 계속합니다(이미 있거나 저장소에 없을 수 있음).
      if apt_update; then apt_get install ubuntu-dbgsym-keyring || true; fi
      printf 'deb http://ddebs.ubuntu.com %s main restricted universe multiverse\ndeb http://ddebs.ubuntu.com %s-updates main restricted universe multiverse\n' \
        "$VERSION_CODENAME" "$VERSION_CODENAME" > /etc/apt/sources.list.d/ddebs.list
      apt_get update || exit 1
      apt_get install "linux-image-unsigned-$k-dbgsym" || apt_get install "linux-image-$k-dbgsym" || exit 1
      ;;
    debian)
      printf 'deb http://deb.debian.org/debian-debug/ %s-debug main\n' "$VERSION_CODENAME" > /etc/apt/sources.list.d/debian-debug.list
      apt_get update || exit 1
      apt_get install "linux-image-$k-dbg" || exit 1
      ;;
    *) echo "이 배포판의 디버그 커널 패키지를 알 수 없습니다: ${ID:-}"; exit 10 ;;
    esac
    # 내려받은 디버그 패키지(최대 2GB)가 apt 캐시에 남아 덤프 저장 공간을 차지하므로 지웁니다.
    rm -f /var/cache/apt/archives/*-dbgsym_*.ddeb /var/cache/apt/archives/*-dbg_*.deb
  else
    # 커널 종류에 맞는 디버그 패키지: Oracle UEK는 kernel-uek, 실시간 커널은 kernel-rt
    case "$k" in
      *uek*) kpkg=kernel-uek ;;
      *.rt*|*+rt*) kpkg=kernel-rt ;;
      *) kpkg=kernel ;;
    esac
    major=$(printf '%s' "${VERSION_ID:-}" | cut -d. -f1)
    case "${ID:-}" in
    ol)
      # Oracle Linux: debuginfo는 oss.oracle.com의 별도 저장소에 있어 기본 설정으로는 찾지 못합니다.
      if ! grep -qs "oss.oracle.com/ol$major/debuginfo" /etc/yum.repos.d/*.repo; then
        printf '[ol%s_debuginfo]\nname=Oracle Linux %s debuginfo\nbaseurl=https://oss.oracle.com/ol%s/debuginfo/\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-oracle\ngpgcheck=1\nenabled=1\n' \
          "$major" "$major" "$major" > /etc/yum.repos.d/oracle-debuginfo.repo
        echo "Oracle Linux debuginfo 저장소를 추가했습니다: /etc/yum.repos.d/oracle-debuginfo.repo"
      fi
      ;;
    rhel)
      # RHEL: 구독의 debug 저장소를 켭니다. 켜지 못하면 안내만 하고 계속합니다(이미 켜져 있을 수 있음).
      if command -v subscription-manager >/dev/null 2>&1; then
        arch=$(uname -m)
        if ! subscription-manager repos --enable "rhel-$major-for-$arch-baseos-debug-rpms" >/dev/null 2>&1 &&
           ! subscription-manager repos --enable "rhel-$major-server-debug-rpms" >/dev/null 2>&1; then
          echo "RHEL debug 저장소를 켜지 못했습니다. 구독 상태를 확인하거나 subscription-manager repos --enable rhel-$major-for-$arch-baseos-debug-rpms 를 실행해 주세요."
        fi
      fi
      ;;
    esac
    if [ "$pm" = yum ]; then
      # RHEL·CentOS 7: debuginfo-install은 yum의 하위 명령이 아니라 yum-utils의 별도 명령입니다.
      yum -y install yum-utils >/dev/null 2>&1 || true
      debuginfo-install -y "$kpkg-$k" || exit 1
    else
      dnf -y install dnf-plugins-core >/dev/null 2>&1 || true
      dnf -y debuginfo-install "$kpkg-$k" || exit 1
    fi
  fi
  for p in "/usr/lib/debug/lib/modules/$k/vmlinux" "/usr/lib/debug/boot/vmlinux-$k"; do
    [ -f "$p" ] && { echo "vmlinux: $p"; exit 0; }
  done
  echo "패키지는 설치했지만 vmlinux를 찾지 못했습니다."; exit 1
  ;;
swap)
  f=/swapfile-kdump
  if swapon --show=NAME --noheadings 2>/dev/null | grep -qx "$f"; then echo "이미 사용 중입니다: $f"; exit 0; fi
  rm -f "$f"
  if ! { fallocate -l 2G "$f" 2>/dev/null && chmod 600 "$f" && mkswap "$f" >/dev/null && swapon "$f" 2>/dev/null; }; then
    # 일부 파일시스템은 fallocate로 만든 파일을 swap으로 쓰지 못해 dd로 다시 만듭니다.
    swapoff "$f" 2>/dev/null; rm -f "$f"
    dd if=/dev/zero of="$f" bs=1M count=2048 status=none && chmod 600 "$f" && mkswap "$f" >/dev/null && swapon "$f" || exit 1
  fi
  grep -q "^$f " /etc/fstab || echo "$f none swap defaults 0 0" >> /etc/fstab
  echo "swap 2GB 추가: $f"
  ;;
*) echo "알 수 없는 동작: $action"; exit 2 ;;
esac
""", 2)

PREPARE_ACTIONS = ("kdump", "crashkernel", "crash", "debuginfo", "swap",
                   "dumpconf", "pagefile", "cdb", "tool")
LINUX_PREPARE_ACTIONS = ("kdump", "crashkernel", "crash", "debuginfo", "swap", "tool")
WIN_PREPARE_ACTIONS = ("dumpconf", "pagefile", "cdb", "tool")
PREPARE_LABELS = {"kdump": "kdump 서비스 설치·활성화", "crashkernel": "crashkernel 메모리 예약 설정",
                  "crash": "crash 설치", "debuginfo": "디버그 커널(vmlinux) 설치",
                  "swap": "swap 2GB 추가", "tool": "analyze-kdump 설치 (웹 UI 버전)",
                  "dumpconf": "덤프 설정 (커널 메모리 덤프)", "pagefile": "페이지 파일 (시스템 관리 크기)",
                  "cdb": "디버거 설치 (Debugging Tools for Windows)"}


def valid_prepare_actions(server, actions):
    """서버 준비 요청의 항목이 그 서버 운영체제의 항목인지 확인합니다."""
    allowed = WIN_PREPARE_ACTIONS if is_windows(server) else LINUX_PREPARE_ACTIONS
    return isinstance(actions, list) and bool(actions) and all(a in allowed for a in actions)


def vmlinux_base(server):
    tool = server.get("tool") or ""
    if tool.endswith("/bin/analyze-kdump"):
        return tool[:-len("/bin/analyze-kdump")] + "/vmlinux"
    return "/opt/kdump-analyzer/vmlinux"


def _kv(out):
    info = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if sep and re.fullmatch(r"[a-z_]+", key):
            info[key] = value.strip()
    return info


def _num(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- Windows 서버

def _win_lines(out):
    info = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip():
            info[key.strip()] = value.strip()
    return info


def win_test_server(server):
    script = WIN_FIND_CDB + WIN_DUMPS + r"""$t=%s;$d=%s
"host=$env:COMPUTERNAME";"user=$env:USERNAME"
if(Test-Path -LiteralPath $t){$v=(& $t -Version 2>$null|Select-Object -First 1);"tool=$v"}else{"tool="}
$c=Find-Cdb;if($c){"crash=cdb $((Get-Item -LiteralPath $c).VersionInfo.ProductVersion)"}else{"crash="}
"vmcores=$(@(Get-Dumps $d).Count)"
""" % (ps_quote(server["tool"]), ps_quote(server["crash_dir"]))
    code, out = ssh_text(server, win_argv(script), timeout=60)
    info = {"ok": code == 0, "raw": out.strip()[-600:]}
    info.update(_win_lines(out))
    if code == 0:
        info["method"] = "installed" if info.get("tool") else ("upload" if info.get("crash") else "none")
    return info


def win_server_version(server):
    script = r"""$t=%s
if(Test-Path -LiteralPath $t){$v=(& $t -Version 2>$null|Select-Object -First 1);"version=$v";$b=Split-Path -Parent (Split-Path -Parent $t);"prefix=$b";$f=Join-Path $b '.install-info';if(Test-Path -LiteralPath $f){Get-Content -LiteralPath $f|Where-Object{$_ -match '^(SOURCE|INSTALLED_AT)='}}}else{"version="}""" % ps_quote(server["tool"])
    code, out = ssh_text(server, win_argv(script), timeout=60)
    info = {"ok": code == 0, "server": server["name"], "os": "windows"}
    if code != 0:
        info["error"] = (out.strip().splitlines() or ["SSH 접속 실패"])[-1][-300:]
        return info
    for key, value in _win_lines(out).items():
        if key in ("version", "prefix", "SOURCE", "INSTALLED_AT"):
            info[key.lower()] = value
    info["installed"] = bool(info.get("version"))
    match = TOOL_VERSION_RE.match(info.get("version", ""))
    if match:
        info["version"], info["commit"] = match.group(1), match.group(2) or ""
        if not info.get("installed_at"):
            info["installed_at"] = match.group(3) or ""
    return info


def win_upload_name():
    """분석 스크립트를 보낼 원격 임시 파일 이름(접속 계정의 홈 폴더 기준)."""
    return "kdump-analyzer-%s.ps1" % uuid.uuid4().hex


def scp_upload(server, local_path, remote_name, timeout=120):
    """로컬 파일을 원격 계정의 홈 폴더에 remote_name으로 보냅니다. (종료 코드, 출력)

    Windows 서버에는 표준 입력으로 큰 데이터를 보내지 않습니다. Windows OpenSSH를 거친 PowerShell은
    표준 입력이 크면(실제 VM에서 수십 KB) 끝을 받지 못하고 멈추는 일이 불규칙하게 생깁니다. scp는 안정적입니다.
    """
    if not re.match(r"^[A-Za-z0-9._-]+$", remote_name):
        raise ApiError(400, "원격 파일 이름이 올바르지 않습니다.")
    ssh = ssh_args(server)
    options = ssh[1:-1]
    # ssh의 -p(포트)는 scp에서 -P입니다.
    options = ["-P" if o == "-p" else o for o in options]
    target = ssh[-1]
    user, _, host = target.rpartition("@")
    if ":" in host:
        host = "[%s]" % host
    dest = "%s%s:%s" % (user + "@" if user else "", host, remote_name)
    try:
        result = subprocess.run([ssh_tool("scp"), "-q"] + options + [local_path, dest], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        return 124, b"scp timeout"
    except OSError as error:
        return 127, ("scp를 실행할 수 없습니다: %s" % error).encode()


def fetch_win_script(repo, channel, branch):
    """업데이트 설정(최신 릴리스 또는 브랜치)의 Windows 분석 스크립트를 GitHub에서 받습니다. (정보, 내용)"""
    info = fetch_latest(repo, channel, branch)
    if not info.get("ok"):
        raise ApiError(502, info.get("error") or "GitHub에서 버전 정보를 읽지 못했습니다.")
    url = "https://raw.githubusercontent.com/%s/%s/winbin/analyze-windump.ps1" % (repo, info["commit"])
    try:
        data = _http_get(url, timeout=30)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ApiError(400, "GitHub %s v%s에는 Windows 분석 스크립트가 없습니다 (1.22.0부터 들어 있습니다)."
                           % (info["ref"], info.get("version", "?")))
        raise ApiError(502, "Windows 분석 스크립트를 받지 못했습니다: %s" % error)
    except Exception as error:  # noqa: BLE001 - 네트워크 오류는 화면에 그대로 보여줍니다.
        raise ApiError(502, "Windows 분석 스크립트를 받지 못했습니다: %s" % error)
    if b"analyze-windump" not in data[:4096] and b"$ScriptVersion" not in data:
        raise ApiError(502, "받은 파일이 Windows 분석 스크립트가 아닙니다: %s" % url)
    return info, data


def win_report_command(server, vmcore, method, limit):
    """Windows 서버에서 리포트를 만드는 명령 (argv, 먼저 홈 폴더로 보낼 분석 스크립트 이름 또는 None)."""
    args = "-Dump %s -TimeoutSec %d" % (ps_quote(vmcore), limit)
    if method == "installed":
        return win_argv("& %s %s; exit $LASTEXITCODE" % (ps_quote(server["tool"]), args)), None
    # 무설치 실행: scp로 홈 폴더에 보낸 분석 스크립트를 실행하고 지웁니다.
    name = win_upload_name()
    script = ("$f=Join-Path $HOME %s;"
              "try{& $f %s}finally{Remove-Item -LiteralPath $f -ErrorAction SilentlyContinue};exit $LASTEXITCODE"
              % (ps_quote(name), args))
    return win_argv(script), name


def win_install_command(server, version, commit, label):
    """분석 스크립트를 서버 설정의 경로(...\bin\analyze-windump.ps1)에 설치하는 명령
    (argv, 먼저 홈 폴더로 보낼 분석 스크립트 이름)."""
    name = win_upload_name()
    script = ("$f=Join-Path $HOME %s;$t=%s;$base=Split-Path -Parent (Split-Path -Parent $t);"
              "try{New-Item -ItemType Directory -Force -Path (Split-Path -Parent $t),(Join-Path $base 'logs')|Out-Null;"
              "Copy-Item -LiteralPath $f -Destination $t -Force -ErrorAction Stop}"
              "finally{Remove-Item -LiteralPath $f -ErrorAction SilentlyContinue};"
              "Set-Content -LiteralPath (Join-Path $base '.install-info') -Encoding UTF8 -Value @('VERSION=%s','COMMIT=%s',('INSTALLED_AT='+(Get-Date -Format 'yyyy-MM-dd HH:mm')),'SOURCE=%s');"
              "'설치: '+$t" % (ps_quote(name), ps_quote(server["tool"]), version.replace("'", ""), commit,
                               label.replace("'", "")))
    return win_argv(script), name


# Windows SDK 설치 관리자(winsdksetup.exe). learn.microsoft.com/windows/apps/windows-sdk/downloads 맨 위의 '설치 관리자' 링크.
WIN_SDK_URL = "https://go.microsoft.com/fwlink/?linkid=2382519"

# 서버 준비 탭의 Windows 설치 항목. 출력은 작업 로그에 그대로 남습니다.
WIN_PREPARE = {
    # 블루스크린 때 커널 메모리 덤프를 남기게 합니다. 이미 덤프를 만들게 설정돼 있으면 종류는 바꾸지 않습니다.
    "dumpconf": r"""$k='HKLM:\SYSTEM\CurrentControlSet\Control\CrashControl'
$cur=(Get-ItemProperty -Path $k -ErrorAction SilentlyContinue).CrashDumpEnabled
if($null -eq $cur -or $cur -eq 0){Set-ItemProperty -Path $k -Name CrashDumpEnabled -Value 2 -Type DWord;"CrashDumpEnabled: $(if($null -eq $cur){'없음'}else{$cur}) -> 2 (커널 메모리 덤프)"}else{"덤프 종류는 그대로 둡니다: CrashDumpEnabled=$cur"}
Set-ItemProperty -Path $k -Name AutoReboot -Value 1 -Type DWord
Set-ItemProperty -Path $k -Name Overwrite -Value 1 -Type DWord
'AutoReboot=1 (덤프 뒤 자동 재시작), Overwrite=1 (MEMORY.DMP 덮어쓰기)'
'재부팅한 뒤부터 적용됩니다.'""",
    # 페이지 파일이 없으면 커널 덤프를 쓰지 못할 수 있어, 시스템이 크기를 관리하게 합니다.
    "pagefile": r"""$cs=Get-CimInstance Win32_ComputerSystem
if($cs.AutomaticManagedPagefile){'이미 시스템이 페이지 파일 크기를 관리합니다. 페이지 파일이 없다면 재부팅한 뒤 다시 점검해 주세요.'}
else{Set-CimInstance -InputObject $cs -Property @{AutomaticManagedPagefile=$true};"페이지 파일을 '시스템이 관리하는 크기'로 바꿨습니다. 재부팅한 뒤 적용됩니다."}""",
    # Windows SDK 설치 관리자를 받아 Microsoft 서명을 확인한 뒤 Debugging Tools for Windows만 설치합니다.
    "cdb": WIN_FIND_CDB + r"""$ErrorActionPreference='Stop'
$c=Find-Cdb;if($c){"이미 설치되어 있습니다: $c";exit 0}
$d=Join-Path $env:TEMP ('kdump-analyzer-sdk-'+[guid]::NewGuid().ToString('N'));New-Item -ItemType Directory -Path $d|Out-Null
try{$f=Join-Path $d 'winsdksetup.exe';$log=Join-Path $d 'sdk.log'
[Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
'[1/3] Windows SDK 설치 관리자 받는 중: '+%s
Invoke-WebRequest -UseBasicParsing -Uri %s -OutFile $f
$s=Get-AuthenticodeSignature -LiteralPath $f
if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation'){"[2/3] Microsoft 서명을 확인하지 못해 실행하지 않습니다: $($s.Status) $($s.SignerCertificate.Subject)";exit 3}
'[2/3] 서명 확인: '+$s.SignerCertificate.Subject
'[3/3] Debugging Tools for Windows 설치 중 (몇 분 걸립니다)'
$p=Start-Process -FilePath $f -ArgumentList ('/features OptionId.WindowsDesktopDebuggers /quiet /norestart /log "'+$log+'"') -Wait -PassThru
$c=Find-Cdb;if($c){"설치했습니다: $c";exit 0}
"설치 관리자가 끝났지만 cdb.exe를 찾지 못했습니다 (종료 코드 $($p.ExitCode)). 설치 로그 끝부분:"
if(Test-Path -LiteralPath $log){Get-Content -LiteralPath $log -Tail 15}
exit 4}finally{Remove-Item -LiteralPath $d -Recurse -Force -ErrorAction SilentlyContinue}""" % (ps_quote(WIN_SDK_URL), ps_quote(WIN_SDK_URL)),
}

WIN_DUMP_MODES = {"0": "만들지 않음", "1": "전체 메모리 덤프", "2": "커널 메모리 덤프", "3": "작은 메모리 덤프(Minidump)",
                  "7": "자동 메모리 덤프"}


def win_prepare_check(server):
    """Windows 서버의 덤프 분석 환경 점검. 서버에서 바꾸는 것은 없습니다(설치는 WIN_PREPARE 항목으로)."""
    script = WIN_FIND_CDB + r"""$c=Find-Cdb;"cdb=$c";if($c){"cdb_version=$((Get-Item -LiteralPath $c).VersionInfo.ProductVersion)"}
$cc=Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CrashControl' -ErrorAction SilentlyContinue;"dump_mode=$($cc.CrashDumpEnabled)";"dump_file=$($cc.DumpFile)";"auto_reboot=$($cc.AutoReboot)"
$pf=@(Get-CimInstance Win32_PageFileUsage -ErrorAction SilentlyContinue);"pagefile_mb=$(($pf|Measure-Object AllocatedBaseSize -Sum).Sum)"
$os=Get-CimInstance Win32_OperatingSystem;"os_name=$($os.Caption)";"kernel=$($os.Version)";"mem_kb=$($os.TotalVisibleMemorySize)"
$dr=Get-PSDrive ($env:SystemDrive.TrimEnd(':'));"disk_free=$($dr.Free)";"system_drive=$env:SystemDrive"
"admin=$(([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))"
"""
    code, out = ssh_text(server, win_argv(script), timeout=90)
    if code != 0 and "cdb=" not in out:
        raise ApiError(502, "서버를 점검하지 못했습니다: %s" % (out.strip().splitlines() or ["SSH 접속 실패"])[-1][-300:])
    i = _win_lines(out)
    tool = win_server_version(server)
    items = []

    def add(item_id, label, status, detail, action=None, note=None):
        items.append({"id": item_id, "label": label, "status": status, "detail": detail, "action": action, "note": note})

    mode = i.get("dump_mode", "")
    if mode in ("", "0"):
        add("dumpconf", "덤프 설정", "missing", "블루스크린 때 덤프를 만들지 않음 (CrashDumpEnabled=%s)" % (mode or "없음"),
            "dumpconf", "커널 메모리 덤프로 설정합니다. 재부팅한 뒤부터 적용됩니다.")
    else:
        add("dumpconf", "덤프 설정", "ok", "%s · %s" % (WIN_DUMP_MODES.get(mode, "CrashDumpEnabled=" + mode), i.get("dump_file") or "MEMORY.DMP"))
    pagefile = _num(i.get("pagefile_mb"))
    if pagefile:
        add("pagefile", "페이지 파일", "ok", "%d MB" % pagefile)
    else:
        add("pagefile", "페이지 파일", "missing", "없음 · 페이지 파일이 없으면 커널 덤프를 만들지 못할 수 있습니다", "pagefile",
            "'시스템이 관리하는 크기'로 설정합니다. 재부팅한 뒤 적용됩니다.")
    if i.get("cdb"):
        add("cdb", "디버거 (cdb)", "ok", "cdb %s · %s" % (i.get("cdb_version", ""), i["cdb"]))
    else:
        add("cdb", "디버거 (cdb)", "missing", "Debugging Tools for Windows가 없음", "cdb",
            "서버가 Microsoft에서 Windows SDK 설치 관리자를 받아(인터넷 필요) 서명을 확인한 뒤 디버거만 설치합니다.")
    free = _num(i.get("disk_free"))
    if free:
        add("disk", "저장 공간", "ok" if free > 5 * 1024 ** 3 else "warn",
            "%s 여유 %.1f GB%s" % (i.get("system_drive", ""), free / 1024 ** 3,
                                   "" if free > 5 * 1024 ** 3 else " · 덤프와 심볼에 공간이 부족할 수 있습니다"))
    if tool.get("installed"):
        add("tool", "분석 스크립트", "ok", "v%s %s" % (tool.get("version", ""), tool.get("prefix", "")))
    else:
        add("tool", "분석 스크립트", "missing", "설치되어 있지 않음 · 무설치 실행으로도 분석할 수 있습니다", "tool")
    if i.get("admin") != "True":
        add("admin", "관리자 권한", "missing", "접속 계정이 관리자가 아님", None,
            "MEMORY.DMP를 읽으려면 관리자 계정으로 접속해야 합니다.")
    return {"os": i.get("os_name", "Windows"), "family": "Windows", "kernel": i.get("kernel", ""), "pkg": "",
            "root": i.get("admin") == "True", "items": items}


def debuginfo_note(os_id, debian, kernel):
    """서버 준비의 디버그 커널 설치 안내(배포판·커널 종류별)."""
    if os_id == "ubuntu":
        return "dbgsym 저장소(ddebs.ubuntu.com)를 추가합니다."
    if debian:
        return "debug 저장소를 추가합니다."
    pkg = "kernel-uek" if "uek" in kernel else ("kernel-rt" if ".rt" in kernel or "+rt" in kernel else "kernel")
    if os_id == "ol":
        return "Oracle Linux debuginfo 저장소(oss.oracle.com)가 없으면 추가하고 %s-debuginfo를 설치합니다." % pkg
    if os_id == "rhel":
        return "구독의 debug 저장소(rhel-<버전>-…-debug-rpms)를 켜고 %s-debuginfo를 설치합니다. 구독이 없으면 실패합니다." % pkg
    return "debuginfo 저장소에서 %s-debuginfo를 설치합니다." % pkg


def prepare_check(server):
    """서버의 kdump 분석 환경을 점검해 항목 목록으로 돌려줍니다. 서버에서 바꾸는 것은 없습니다."""
    if is_windows(server):
        return win_prepare_check(server)
    code, out = ssh_text(server, ["sh", "-c", REMOTE_CHECK, "sh", server["crash_dir"], vmlinux_base(server)],
                         timeout=60)
    if code != 0 and "os_id=" not in out:
        raise ApiError(502, "서버를 점검하지 못했습니다: %s" % (out.strip().splitlines() or ["SSH 접속 실패"])[-1][-300:])
    i = _kv(out)
    tool = server_version(server)
    debian = i.get("pkg") == "apt"
    family = "Ubuntu·Debian" if debian else ("RHEL 계열" if i.get("pkg") in ("dnf", "yum") else (i.get("pkg") or "알 수 없음"))
    mem_kb, swap_kb = _num(i.get("mem_kb")), _num(i.get("swap_kb"))
    reserved = _num(i.get("crashkernel_bytes"))
    items = []

    def add(item_id, label, status, detail, action=None, note=None):
        items.append({"id": item_id, "label": label, "status": status, "detail": detail,
                      "action": action, "note": note})

    if not i.get("kdump_tool"):
        add("kdump", "kdump 서비스", "missing", "설치되어 있지 않음 (%s)" % ("kdump-tools" if debian else "kexec-tools"), "kdump")
    elif debian and i.get("use_kdump") not in ("1", "true", "yes"):
        add("kdump", "kdump 서비스", "missing", "설치됨, 꺼져 있음 (/etc/default/kdump-tools: USE_KDUMP=%s)"
            % (i.get("use_kdump") or "없음"), "kdump", "USE_KDUMP=1로 켜고 서비스를 다시 시작합니다.")
    elif i.get("kdump_active") == "failed":
        add("kdump", "kdump 서비스", "missing", "시작 실패 (%s)" % i.get("kdump_tool"), "kdump",
            "원인은 서버에서 journalctl -u %s -b 로 확인합니다. 다시 시도하면 서비스를 다시 시작합니다."
            % ("kdump-tools" if debian else "kdump"))
    elif i.get("kdump_enabled") != "enabled":
        add("kdump", "kdump 서비스", "missing", "설치됨, 부팅 때 켜지지 않음 (%s)" % i.get("kdump_enabled", "?"), "kdump")
    else:
        add("kdump", "kdump 서비스", "ok", "%s · %s" % (i.get("kdump_tool"), i.get("kdump_active") or "?"))

    if reserved > 0:
        add("crashkernel", "crashkernel 예약", "ok", "%d MB 예약됨 (%s)" % (reserved // 1048576, i.get("crashkernel_now") or "?"))
    elif i.get("crashkernel_next"):
        add("crashkernel", "crashkernel 예약", "warn", "설정됨(%s), 아직 예약 안 됨: 재부팅 필요" % i["crashkernel_next"],
            None, "재부팅하면 적용됩니다. 메모리 크기가 설정 범위에 들지 않으면 재부팅 후에도 예약되지 않습니다.")
    else:
        add("crashkernel", "crashkernel 예약", "missing", "설정 없음", "crashkernel", "설정 뒤 재부팅해야 적용됩니다.")

    if i.get("kdump_ready") == "1":
        add("ready", "kdump 동작 준비", "ok", "패닉이 나면 vmcore를 저장할 수 있는 상태")
    else:
        add("ready", "kdump 동작 준비", "warn", "아직 준비 안 됨 (위 두 항목을 마치고 재부팅하면 준비됩니다)")

    if i.get("crash"):
        add("crash", "crash", "ok", i["crash"])
    else:
        add("crash", "crash", "missing", "설치되어 있지 않음 (이 서버에서 분석하려면 필요)", "crash")

    if i.get("vmlinux"):
        add("debuginfo", "디버그 커널 (실행 중인 커널)", "ok", i["vmlinux"])
    else:
        add("debuginfo", "디버그 커널 (실행 중인 커널)", "missing", "%s 용 vmlinux 없음" % i.get("kernel", "?"), "debuginfo",
            "수백 MB~1GB를 받습니다. %s" % debuginfo_note(i.get("os_id"), debian, i.get("kernel", "")))

    if mem_kb and mem_kb < 3 * 1048576 and swap_kb < 1536 * 1024:
        add("swap", "메모리·swap", "warn", "메모리 %.1f GB, swap %.1f GB: crash 실행 중 OOM 위험" % (mem_kb / 1048576, swap_kb / 1048576),
            "swap", "crash는 디버그 정보를 읽을 때 약 1.5GB를 씁니다.")
    else:
        add("swap", "메모리·swap", "ok", "메모리 %.1f GB, swap %.1f GB" % (mem_kb / 1048576, swap_kb / 1048576))

    disk_kb = _num(i.get("disk_kb"))
    if disk_kb and mem_kb and disk_kb < mem_kb:
        add("disk", "덤프 저장 공간", "warn", "%s 여유 %.1f GB (메모리보다 작음)" % (server["crash_dir"], disk_kb / 1048576))
    else:
        add("disk", "덤프 저장 공간", "ok", "%s 여유 %.1f GB" % (server["crash_dir"], disk_kb / 1048576))

    if tool.get("installed"):
        add("tool", "analyze-kdump", "ok", "v%s %s" % (tool.get("version"), tool.get("commit") or ""))
    else:
        add("tool", "analyze-kdump", "info", "설치 안 됨 (무설치 실행으로도 분석 가능)", "tool")

    return {"os": i.get("os_name") or i.get("os_id") or "?", "family": family, "kernel": i.get("kernel"),
            "pkg": i.get("pkg"), "root": i.get("uid") == "0", "items": items}


# 서버에 보낼 설치 묶음. install.sh가 복사하는 파일만 담습니다.
BUNDLE_FILES = ("install.sh", "VERSION", "README.md", "CHANGELOG.md", "LICENSE",
                "analyze-kdump.conf.sample", "servers.conf.sample")
BUNDLE_DIRS = ("bin", "completion", "docs")


def build_bundle():
    """설치 파일을 푸는 셸 스크립트를 만듭니다. 최소 설치 서버에는 tar가 없을 수 있어 base64(coreutils)만 씁니다.
    서버에서 sh -s -- <대상 디렉터리>로 실행합니다."""
    lines = ['set -e', 'd="$1"', 'mkdir -p ' + " ".join('"$d/%s"' % d for d in BUNDLE_DIRS)]

    def add(rel, mode):
        with open(os.path.join(REPO_DIR, rel), "rb") as f:
            data = f.read().replace(b"\r\n", b"\n")  # Windows에서 CRLF로 받았더라도 리눅스용으로 맞춥니다.
        target = '"$d"/' + shlex.quote(rel.replace(os.sep, "/"))
        encoded = base64.encodebytes(data).decode("ascii").rstrip("\n")
        lines.extend(["base64 -d > %s <<'KDUMP_TOOLS_EOF'" % target, encoded, "KDUMP_TOOLS_EOF",
                      "chmod %o %s" % (mode, target)])

    for rel in BUNDLE_FILES:
        if os.path.isfile(os.path.join(REPO_DIR, rel)):
            add(rel, 0o755 if rel.endswith(".sh") else 0o644)
    for folder in BUNDLE_DIRS:
        base = os.path.join(REPO_DIR, folder)
        for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            if os.path.isfile(os.path.join(base, name)) and NAME_RE.match(name):
                add(os.path.join(folder, name), 0o755 if folder == "bin" else 0o644)
    return ("\n".join(lines) + "\n").encode("ascii")


# 원격에서 설치 위치를 찾고 install.sh를 실행합니다.
# $1 도구 경로, $2 local|github, $3 저장소, $4 브랜치나 태그, $5 커밋, $6 원본 설명, $7 heads|tags
REMOTE_INSTALL = with_install_fallback(r"""
tool="$1"; mode="$2"; repo="$3"; branch="$4"; commit="$5"; label="$6"; kind="${7:-heads}"
t=$(command -v "$tool" 2>/dev/null || true)
if [ -n "$t" ]; then t=$(readlink -f "$t"); else t="$tool"; fi
case "$t" in
  /*/bin/analyze-kdump) prefix=${t%/bin/analyze-kdump} ;;
  analyze-kdump)
    # 경로 대신 명령 이름(analyze-kdump)이 설정돼 있는데 등록된 명령이 없으면(처음 설치, 삭제 뒤 다시 설치)
    # 기본 위치에 설치합니다. 예전 위치에만 설치돼 있으면 그곳을 씁니다(install.sh와 같은 규칙).
    if [ ! -e /opt/kdump-analyzer/bin/analyze-kdump ] && [ -x /opt/kdump-tools/bin/analyze-kdump ]; then
      prefix=/opt/kdump-tools
    else
      prefix=/opt/kdump-analyzer
    fi
    echo "등록된 $tool 명령이 없어 $prefix 에 설치합니다." ;;
  *) echo "설치 위치를 알 수 없습니다: $tool (서버 설정의 원격 analyze-kdump 경로를 /opt/kdump-analyzer/bin/analyze-kdump 형태로 지정해 주세요)"; exit 3 ;;
esac
[ "$(id -u)" -eq 0 ] || { echo "root 권한이 필요합니다. 서버 설정에서 sudo를 켜 주세요(비밀번호 없는 sudo 필요)."; exit 4; }
tmp=$(mktemp -d /tmp/kdump-tools-update.XXXXXX) || exit 5
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/src"
if [ "$mode" = local ]; then
  echo "[1/2] 웹 UI가 보낸 파일 푸는 중"
  command -v base64 >/dev/null 2>&1 || { echo "서버에 base64(coreutils)가 없습니다."; exit 6; }
  sh -s -- "$tmp/src" || { echo "파일을 풀지 못했습니다."; exit 6; }
else
  echo "[1/2] GitHub에서 받는 중: $repo ($branch)"
  if command -v git >/dev/null 2>&1; then
    git -c advice.detachedHead=false clone -q --depth 1 --branch "$branch" "https://github.com/$repo.git" "$tmp/src" || exit 7
    commit=$(git -c safe.directory="$tmp/src" -C "$tmp/src" rev-parse HEAD 2>/dev/null || echo "$commit")
  elif command -v curl >/dev/null 2>&1 && command -v tar >/dev/null 2>&1; then
    curl -fsSL "https://codeload.github.com/$repo/tar.gz/refs/$kind/$branch" | tar xz -C "$tmp/src" --strip-components=1 || exit 7
  else
    echo "서버에 git이 없고 curl·tar도 없어 GitHub에서 받을 수 없습니다. '웹 UI 버전 설치'를 사용해 주세요."; exit 7
  fi
fi
[ -f "$tmp/src/install.sh" ] || { echo "install.sh가 없습니다."; exit 8; }
echo "[2/2] 설치 중: v$(head -n 1 "$tmp/src/VERSION" 2>/dev/null | tr -d '[:space:]') -> $prefix"
set -- --prefix "$prefix"
bin_dir=$(sed -n 's/^BIN_DIR=//p' "$prefix/.install-info" 2>/dev/null | head -n 1)
[ -n "$bin_dir" ] && set -- "$@" --bin-dir "$bin_dir"
if grep -q -- '--commit)' "$tmp/src/install.sh"; then
  [ -n "$commit" ] && set -- "$@" --commit "$commit"
  set -- "$@" --source "$label"
fi
bash "$tmp/src/install.sh" "$@"
status=$?
# install.sh는 일부 명령 등록을 건너뛰면 2를 반환하지만 설치는 끝난 상태입니다.
[ "$status" -eq 2 ] && status=0
exit $status
""", 1)


# 원격 설치를 새 기본 위치로 옮깁니다. 먼저 웹 UI 버전으로 업그레이드해 install.sh --move-to가 있게 한 뒤 실행합니다.
# $1 도구 경로, $2 옮길 위치
MOVE_TARGET = "/opt/kdump-analyzer"
LEGACY_PREFIX = "/opt/kdump-tools"
REMOTE_MOVE = with_install_fallback(r"""
tool="$1"; dest="$2"
t=$(command -v "$tool" 2>/dev/null || true)
if [ -n "$t" ]; then t=$(readlink -f "$t"); else t="$tool"; fi
case "$t" in
  /*/bin/analyze-kdump) prefix=${t%/bin/analyze-kdump} ;;
  *) echo "설치 위치를 알 수 없습니다: $tool"; exit 3 ;;
esac
[ "$(id -u)" -eq 0 ] || { echo "root 권한이 필요합니다. 서버 설정에서 sudo를 켜 주세요(비밀번호 없는 sudo 필요)."; exit 4; }
if [ ! -f "$prefix/install.sh" ] || ! grep -q -- '--move-to)' "$prefix/install.sh"; then
  echo "설치된 install.sh가 설치 위치 옮기기를 지원하지 않습니다: $prefix/install.sh"; exit 5
fi
echo "설치 위치 옮기기: $prefix -> $dest"
bash "$prefix/install.sh" --prefix "$prefix" --move-to "$dest"
status=$?
# install.sh는 일부 명령 등록을 건너뛰면 2를 반환하지만 옮기기는 끝난 상태입니다.
[ "$status" -eq 2 ] && status=0
exit $status
""", 1)


# 서버의 analyze-kdump를 지웁니다. 설치된 install.sh의 판에 기대지 않도록 여기서 직접 합니다.
# $1 도구 경로, $2 program(프로그램 파일만, 설정·서버 목록·로그·vmlinux는 남김) | all(설치 디렉터리 통째로)
UNINSTALL_MODES = ("program", "all")
# install.sh가 설치 디렉터리에 복사하는 것(BUNDLE_FILES·BUNDLE_DIRS)과 설치 정보
# tests는 GitHub에서 설치하거나 저장소에서 install.sh를 실행할 때 함께 복사됩니다.
PROGRAM_FILES = BUNDLE_DIRS + BUNDLE_FILES + ("tests", ".install-info")
REMOTE_UNINSTALL = with_install_fallback(r"""
tool="$1"; mode="$2"; shift 2
t=$(command -v "$tool" 2>/dev/null || true)
if [ -n "$t" ]; then t=$(readlink -f "$t"); else t="$tool"; fi
case "$t" in
  /*/bin/analyze-kdump) prefix=${t%/bin/analyze-kdump} ;;
  *) echo "설치 위치를 알 수 없습니다: $tool"; exit 3 ;;
esac
[ "$(id -u)" -eq 0 ] || { echo "root 권한이 필요합니다. 서버 설정에서 sudo를 켜 주세요(비밀번호 없는 sudo 필요)."; exit 4; }
case "$prefix" in
  ""|/|/bin|/sbin|/boot|/dev|/etc|/home|/lib|/lib64|/opt|/proc|/root|/run|/srv|/sys|/tmp|/usr|/var|/usr/*|/etc/*|/var/*)
    echo "이 위치는 지우지 않습니다: $prefix"; exit 5 ;;
esac
if [ ! -f "$prefix/.install-info" ] && [ ! -x "$prefix/bin/analyze-kdump" ]; then
  echo "analyze-kdump 설치가 아닙니다: $prefix"; exit 5
fi
bin_dir=$(sed -n 's/^BIN_DIR=//p' "$prefix/.install-info" 2>/dev/null | head -n 1)
[ -n "$bin_dir" ] || bin_dir=/usr/sbin
for link in "$bin_dir"/*; do
  [ -L "$link" ] || continue
  case "$(readlink -f "$link")" in
    "$prefix"/bin/*) rm -f "$link" && echo "명령 해제: $link" ;;
  esac
done
c=/etc/bash_completion.d/kdump-tools
if [ -f "$c" ] && grep -q analyze-kdump "$c" 2>/dev/null; then rm -f "$c" && echo "자동완성 해제: $c"; fi
if [ "$mode" = all ]; then
  # 설치 위치를 옮긴 뒤 남긴 예전 경로 링크도 지웁니다.
  for l in /opt/kdump-tools /opt/kdump-analyzer; do
    if [ -L "$l" ] && [ "$(readlink -f "$l")" = "$prefix" ]; then rm -f "$l" && echo "링크 삭제: $l"; fi
  done
  rm -rf -- "$prefix" || exit 6
  echo "설치 디렉터리를 지웠습니다: $prefix"
else
  for f in "$@"; do
    if [ -e "$prefix/$f" ] || [ -L "$prefix/$f" ]; then rm -rf -- "${prefix:?}/$f" || exit 6; fi
  done
  echo "프로그램 파일을 지웠습니다: $prefix"
  left=$(ls -A "$prefix" 2>/dev/null)
  if [ -n "$left" ]; then echo "남긴 것 (설정·서버 목록·로그·vmlinux):"; echo "$left" | sed 's/^/  /'; else rmdir "$prefix" 2>/dev/null; fi
fi
""", 1)


def win_uninstall_command(server, mode):
    """Windows 서버의 분석 스크립트를 지우는 명령. program은 bin과 설치 정보만, all은 설치 폴더 통째로(로그·심볼 포함)."""
    script = (r"""$t=%s;$mode=%s
$bin=Split-Path -Parent $t;$base=Split-Path -Parent $bin
if((Split-Path -Leaf $bin) -ne 'bin' -or -not $base -or $base.Length -le 3){"이 위치는 지우지 않습니다: $base";exit 5}
if(-not (Test-Path -LiteralPath (Join-Path $base '.install-info')) -and -not (Test-Path -LiteralPath $t)){"설치되어 있지 않습니다: $t";exit 5}
if($mode -eq 'all'){Remove-Item -LiteralPath $base -Recurse -Force -ErrorAction Stop;"설치 폴더를 지웠습니다: $base"}
else{foreach($p in @($bin,(Join-Path $base '.install-info'))){if(Test-Path -LiteralPath $p){Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop}}
"프로그램 파일을 지웠습니다: $bin"
$left=@(Get-ChildItem -LiteralPath $base -Force -ErrorAction SilentlyContinue|ForEach-Object{$_.Name})
if($left.Count){'남긴 것 (로그·심볼): '+($left -join ', ')}else{Remove-Item -LiteralPath $base -Force -ErrorAction SilentlyContinue}}"""
              % (ps_quote(server["tool"]), ps_quote(mode)))
    return win_argv(script)


# ---------------------------------------------------------------- 분석 작업

class JobCancelled(Exception):
    pass


class FifoSlot:
    """먼저 온 작업부터 하나씩 실행하게 하는 대기열입니다. 같은 서버에서 crash를 동시에 돌리지 않으려고 씁니다
    (메모리가 작은 서버에서는 crash 두 개가 동시에 돌면 OOM으로 죽을 수 있습니다)."""

    def __init__(self, label):
        self.label = label
        self.cond = threading.Condition()
        self.queue = []

    def reserve(self, job):
        with self.cond:
            if job not in self.queue:
                self.queue.append(job)

    @contextlib.contextmanager
    def hold(self, job):
        self.reserve(job)
        with self.cond:
            while self.queue[0] is not job:
                if job.cancelled:
                    self.queue.remove(job)
                    self.cond.notify_all()
                    raise JobCancelled()
                job.status = "queued"
                job.phase = "%s 대기 중 (앞에 %d개)" % (self.label, self.queue.index(job))
                self.cond.wait(0.5)
            if job.cancelled:
                self.queue.remove(job)
                self.cond.notify_all()
                raise JobCancelled()
        job.status = "running"
        if job.run_started is None:
            job.run_started = time.time()
        try:
            yield
        finally:
            with self.cond:
                self.queue.remove(job)
                self.cond.notify_all()


class Job:
    def __init__(self, kind, server, vmcore=None, report=None):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind            # report | llm | reanalyze | upgrade
        self.server = server
        self.vmcore = vmcore
        self.report = report
        self.analysis = None
        self.status = "running"     # queued | running | done | error | cancelled
        self.cancelled = False
        self.run_started = None     # 대기열을 지나 실제로 시작한 시각
        self.phase = "준비 중"
        self.progress = None        # {"current", "total", "label", "elapsed"}
        self.logs = []
        self.error = None
        self.method = None
        self.source = None          # upgrade: local | github
        self.actions = []           # prepare: 실행할 준비 동작
        self.step_label = ""        # prepare: 지금 실행 중인 동작 이름
        self.version = None         # upgrade: 설치 후 서버 버전
        self.saved = None           # download: 웹 UI 데이터 폴더에 저장한 파일 경로
        self.auto = False           # 새 덤프 자동 분석이 시작한 작업
        self.started = time.time()
        self.finished = None
        self.lock = threading.Lock()

    def log(self, line):
        line = ANSI_RE.sub("", line).rstrip()
        if line:
            with self.lock:
                self.logs.append(line)
                del self.logs[:-300]

    def to_dict(self):
        with self.lock:
            return {"id": self.id, "kind": self.kind, "server": self.server, "vmcore": self.vmcore,
                    "report": self.report, "analysis": self.analysis, "status": self.status,
                    "phase": self.phase, "progress": self.progress, "logs": self.logs[-60:],
                    "error": self.error, "method": self.method, "source": self.source, "actions": self.actions,
                    "version": self.version, "started": self.started, "saved": self.saved, "auto": self.auto,
                    "elapsed": int((self.finished or time.time()) - (self.run_started or self.started))}


class Jobs:
    def __init__(self, store):
        self.store = store
        self.items = {}
        self.lock = threading.Lock()
        self.server_slots = {}
        self.llm_slot = FifoSlot("LLM 분석")

    def server_slot(self, name):
        with self.lock:
            return self.server_slots.setdefault(name, FifoSlot("서버 작업"))

    def start(self, job, target, reserve=None):
        """reserve에 대기열을 주면 요청한 순서대로 자리를 잡아 둡니다(여러 개를 한 번에 시작할 때 순서 보장)."""
        with self.lock:
            self.items[job.id] = job
        if reserve is not None:
            reserve.reserve(job)
            job.status, job.phase = "queued", "%s 대기 중" % reserve.label
        thread = threading.Thread(target=self._run, args=(job, target), daemon=True)
        thread.start()
        return job

    def get(self, job_id):
        with self.lock:
            job = self.items.get(job_id)
        if not job:
            raise ApiError(404, "작업을 찾을 수 없습니다.")
        return job

    def recent(self):
        with self.lock:
            jobs = sorted(self.items.values(), key=lambda j: j.started, reverse=True)
        # 진행 중이거나 대기 중인 작업은 모두, 끝난 작업은 최근 20개만 돌려줍니다.
        active = [j for j in jobs if j.status in ("queued", "running")]
        return [j.to_dict() for j in active + [j for j in jobs if j not in active][:20]]

    def cancel(self, job_id):
        job = self.get(job_id)
        # 덤프 받기는 오래 걸릴 수 있어 진행 중에도 멈출 수 있습니다(받던 파일은 지움).
        if job.status != "queued" and not (job.kind == "download" and job.status == "running"):
            raise ApiError(409, "대기 중인 작업만 취소할 수 있습니다.")
        job.cancelled = True
        return job

    def _run(self, job, target):
        try:
            target(job)
            job.status = "done"
            job.phase = "완료"
        except JobCancelled:
            job.status = "cancelled"
            job.phase = "취소됨" + (" (리포트는 저장됨)" if job.report else "")
        except ApiError as error:
            job.status, job.error = "error", error.message
        except kdump_llm.LLMError as error:
            job.status, job.error = "error", "LLM 분석 실패: %s" % error
        except Exception as error:  # noqa: BLE001 - 화면에 원인을 보여주기 위해 모두 잡습니다.
            job.status, job.error = "error", "%s: %s" % (type(error).__name__, error)
        finally:
            job.finished = time.time()
            if job.error:
                job.log("오류: " + job.error)
            if job.auto:
                try:
                    self.store.add_auto_log({
                        "id": job.id, "server": job.server, "vmcore": job.vmcore, "kind": job.kind,
                        "status": job.status, "started": job.started, "finished": job.finished,
                        "report": job.report, "analysis": job.analysis, "error": job.error})
                except Exception as error:  # noqa: BLE001 - 기록을 못 남겨도 작업 결과는 그대로 둡니다.
                    print("자동 분석 기록을 남기지 못했습니다: %s" % error, file=sys.stderr)

    # ---- crash 리포트 생성

    def _stream(self, job, server, argv, stdin=None, timeout=None):
        """원격 명령의 출력을 읽으면서 진행 표시(\\r로 갱신되는 줄)를 진행률로 바꿉니다.

        timeout(초)을 주면 원격에서는 REMOTE_TIMEOUT 감시로, 로컬에서는 감시 타이머로 이중으로 끊습니다.
        시간을 넘기면 (124, 출력)을 돌려주고 job.timed_out을 켭니다.
        """
        if timeout and not is_windows(server):
            # Windows는 분석 스크립트가 -TimeoutSec으로 직접 cdb를 끝내고, 여기서는 아래 감시만 합니다.
            argv = with_remote_timeout(argv, timeout)
        proc = subprocess.Popen(ssh_args(server) + [remote_command(server, argv)],
                                stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        started = time.time()
        watchdog = None
        expired = threading.Event()
        if timeout:
            # 네트워크가 끊겨 원격 timeout의 결과가 돌아오지 않는 경우를 위한 로컬 감시
            def expire():
                expired.set()
                try:
                    proc.kill()
                except OSError:
                    pass
            watchdog = threading.Timer(timeout + KILL_GRACE + 30, expire)
            watchdog.daemon = True
            watchdog.start()
        if stdin:
            # 표준 입력은 따로 보내면서 출력을 읽습니다. 원격이 입력을 다 받기 전에 끝나면(설치 위치 오류 등)
            # 쓰기가 BrokenPipeError로 실패하는데, 그래도 원격이 남긴 이유가 작업 로그에 보이도록 무시합니다.
            def feed():
                try:
                    proc.stdin.write(stdin)
                except OSError:
                    pass
                finally:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
            threading.Thread(target=feed, daemon=True).start()
        buffer = ""
        text_all = []
        while True:
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            pieces, buffer = split_stream(buffer)
            for segment, sep in pieces:
                segment = ANSI_RE.sub("", segment)
                if segment.startswith("내려받는 중:") and job.progress:
                    job.progress = dict(job.progress, label="%s · %s" % (job.step_label, segment.strip()))
                progress = PROGRESS_RE.search(segment)
                if progress:
                    job.progress = {"current": int(progress.group(1)), "total": int(progress.group(2)),
                                    "label": progress.group(3), "elapsed": int(progress.group(4))}
                if sep == "\n":
                    job.log(segment)
                    text_all.append(segment)
        if buffer:
            job.log(buffer)
            text_all.append(buffer)
        proc.wait()
        if watchdog:
            watchdog.cancel()
        code = proc.returncode
        if code != 0 and any("Permission denied (publickey" in line for line in text_all[-10:]):
            hint = passphrase_hint(server)
            if hint:
                job.log(hint)
                text_all.append(hint)
        # 원격 timeout은 124(TERM) 또는 137(KILL)로 끝납니다. 다른 코드여도 제한 시간을 다 썼다면 시간 초과로 봅니다.
        if timeout and (expired.is_set() or code in (124, 137) or (code != 0 and time.time() - started >= timeout)):
            code = 124
            job.timed_out = True
            job.log("시간 제한(%s)을 넘겨 중단했습니다." % human_duration(timeout))
        return code, "\n".join(text_all)

    def start_report(self, server_name, vmcore, kind, auto=False):
        """리포트(kind=report) 또는 리포트 + LLM 분석(kind=llm) 작업을 그 서버의 대기열에 넣습니다."""
        job = Job(kind, server_name, vmcore=vmcore)
        job.auto = auto
        return self.start(job, lambda j: self.run_report(j, kind == "llm"), self.server_slot(server_name))

    def active_vmcores(self, server_name):
        with self.lock:
            return {j.vmcore for j in self.items.values()
                    if j.server == server_name and j.vmcore and j.status in ("queued", "running")}

    def active_results(self, server_name):
        """진행 중이거나 대기 중인 작업이 읽거나 쓰는 리포트·분석 파일 이름."""
        with self.lock:
            return {n for j in self.items.values()
                    if j.server == server_name and j.status in ("queued", "running")
                    for n in (j.report, j.analysis) if n}

    def run_report(self, job, llm):
        server = self.store.server(job.server)
        with self.server_slot(server["name"]).hold(job):
            self._run_report(job, server)
        if llm:
            self.run_llm(job)

    def _run_report_windows(self, job, server):
        job.phase = "서버 확인 중"
        method = server.get("method") or "auto"
        if method == "auto":
            method = probe_method(server)
            if method not in ("installed", "upload"):
                raise ApiError(502, "Windows 서버에 분석 스크립트나 cdb(Debugging Tools for Windows)가 없어 분석할 수 없습니다.")
        job.method = method
        job.log("분석 방식: %s" % ("원격 설치본 실행" if method == "installed" else "무설치 실행"))
        limit = crash_timeout_seconds(self.store.settings())
        argv, upload = win_report_command(server, job.vmcore, method, limit)
        if upload:
            self._win_upload(job, server, upload)
        job.phase = "cdb 리포트 생성 중"
        code, text = self._stream(job, server, argv, timeout=limit + 120)
        remote_report = remote_json = ""
        for line in text.splitlines():
            if line.startswith("report:"):
                remote_report = line.split(":", 1)[1].strip()
            elif line.startswith("json:"):
                remote_json = line.split(":", 1)[1].strip()
        if not remote_report:
            raise ApiError(502, "리포트를 만들지 못했습니다 (종료 코드 %d). 로그를 확인해 주세요." % code)
        job.phase = "리포트 가져오는 중"
        fetch_code, data = fetch_remote_file(server, remote_report)
        if fetch_code != 0:
            raise ApiError(502, "리포트를 가져오지 못했습니다.")
        name = re.split(r"[\\/]", remote_report)[-1]
        if not FILE_RE.match(name):
            name = "kdump-report-%s.txt" % time.strftime("%Y%m%d-%H%M%S")
        local_report = os.path.join(self.store.report_dir(server["name"]), name)
        with open(local_report, "wb") as f:
            f.write(data)
        job.report = name
        job.log("리포트 저장: %s" % name)
        if remote_json:
            self._fetch_summary(job, server, remote_json, local_report)
        if code != 0:
            raise ApiError(502, "cdb 실행이 실패했거나 버그체크를 읽지 못했습니다 (종료 코드 %d). 리포트 끝의 실행 로그를 확인해 주세요." % code)

    def _run_report(self, job, server):
        if is_windows(server):
            return self._run_report_windows(job, server)
        job.phase = "서버 확인 중"
        method = server.get("method") or "auto"
        if method == "auto":
            method = probe_method(server)
            if method not in ("installed", "upload"):
                raise ApiError(502, "원격 서버에 analyze-kdump나 crash가 없어 분석할 수 없습니다.")
        job.method = method
        job.log("분석 방식: %s" % ("원격 설치본 실행" if method == "installed" else "무설치 실행"))

        tmpdir = None
        if method == "installed":
            argv = ["env", "ANALYZE_KDUMP_PROGRESS=1", "sh", "-c", with_install_fallback('exec "$1" -r "$2"', 1),
                    "sh", server["tool"], job.vmcore]
            stdin = None
        else:
            code, out = ssh_text(server, ["mktemp", "-d", "/tmp/kdump-tools.XXXXXX"])
            tmpdir = out.strip().splitlines()[-1:] or [""]
            tmpdir = tmpdir[0]
            if code != 0 or not tmpdir.startswith("/tmp/kdump-tools."):
                raise ApiError(502, "원격 임시 디렉터리를 만들지 못했습니다: %s" % out.strip()[-300:])
            with open(ANALYZE_SCRIPT, "rb") as f:
                script = f.read()
            code, out = ssh_run(server, ["sh", "-c", 'cat > "$1/analyze-kdump" && chmod 700 "$1/analyze-kdump"',
                                         "sh", tmpdir], stdin=script)
            if code != 0:
                raise ApiError(502, "스크립트를 보내지 못했습니다: %s" % out.decode(errors="replace")[-300:])
            argv = ["env", "ANALYZE_KDUMP_PROGRESS=1", "REPORT_DIR=%s/logs" % tmpdir,
                    "ANALYZE_KDUMP_CONF=%s/none.conf" % tmpdir, tmpdir + "/analyze-kdump", "-r", job.vmcore]
            stdin = None

        try:
            job.phase = "crash 리포트 생성 중"
            limit = crash_timeout_seconds(self.store.settings())
            code, text = self._stream(job, server, argv, stdin, timeout=limit)
            remote_report = remote_json = ""
            for line in text.splitlines():
                if line.startswith("report:"):
                    remote_report = line.split(":", 1)[1].strip()
                elif line.startswith("json:"):
                    remote_json = line.split(":", 1)[1].strip()
            if not remote_report:
                if getattr(job, "timed_out", False):
                    raise ApiError(504, "crash 실행이 시간 제한(%s)을 넘겨 중단했습니다. 덤프가 크거나 crash가 멈춘 것일 수 있습니다. "
                                        "설정의 crash 제한 시간을 늘리거나 서버에서 직접 확인해 주세요." % human_duration(limit))
                raise ApiError(502, "리포트를 만들지 못했습니다 (종료 코드 %d). 로그를 확인해 주세요." % code)

            job.phase = "리포트 가져오는 중"
            fetch_code, data = fetch_remote_file(server, remote_report)
            if fetch_code != 0:
                raise ApiError(502, "리포트를 가져오지 못했습니다.")
            name = os.path.basename(remote_report)
            if not FILE_RE.match(name):
                name = "kdump-report-%s.txt" % time.strftime("%Y%m%d-%H%M%S")
            local_report = os.path.join(self.store.report_dir(server["name"]), name)
            with open(local_report, "wb") as f:
                f.write(data)
            job.report = name
            job.log("리포트 저장: %s" % name)
            if remote_json:
                self._fetch_summary(job, server, remote_json, local_report)
            if code != 0:
                raise ApiError(502, "crash 실행이 실패했습니다 (종료 코드 %d). 리포트 끝의 crash 실행 로그를 확인해 주세요." % code)
        finally:
            if tmpdir:
                ssh_run(server, ["rm", "-rf", tmpdir])

    def _fetch_summary(self, job, server, remote_json, local_report):
        """리포트 옆의 JSON 요약을 가져옵니다. 없거나 깨졌으면 리포트만 남기고 넘어갑니다."""
        code, data = fetch_remote_file(server, remote_json, timeout=60)
        try:
            if code != 0:
                raise ValueError("가져오지 못했습니다")
            if not isinstance(json.loads(data.decode("utf-8")), dict):
                raise ValueError("형식이 올바르지 않습니다")
        except ValueError as error:  # UnicodeDecodeError, JSONDecodeError 포함
            job.log("JSON 요약은 건너뜁니다: %s" % error)
            return
        with open(summary_path(local_report), "wb") as f:
            f.write(data)
        job.log("JSON 요약 저장: %s" % os.path.basename(summary_path(local_report)))

    # ---- 서버의 analyze-kdump 설치·업그레이드

    def run_prepare(self, job):
        server = self.store.server(job.server)
        with self.server_slot(server["name"]).hold(job):
            failed = []
            for n, action in enumerate(job.actions, 1):
                job.phase = "%d/%d %s" % (n, len(job.actions), PREPARE_LABELS[action])
                job.step_label = PREPARE_LABELS[action]
                job.progress = {"current": n - 1, "total": len(job.actions), "label": job.step_label, "elapsed": 0}
                job.log("===== %s =====" % PREPARE_LABELS[action])
                if action == "tool":
                    job.source = "local"
                    try:
                        self._run_upgrade(job, server)
                    except ApiError as error:
                        job.log(error.message)
                        failed.append(action)
                    continue
                if is_windows(server):
                    argv = win_argv(WIN_PREPARE[action])
                else:
                    argv = ["sh", "-c", REMOTE_PREPARE, "sh", action, vmlinux_base(server)]
                code, _ = self._stream(job, server, argv, timeout=PREPARE_TIMEOUT)
                if code != 0:
                    job.log("실패 (종료 코드 %d)" % code)
                    failed.append(action)
            job.progress = {"current": len(job.actions), "total": len(job.actions), "label": "완료", "elapsed": 0}
            if failed:
                raise ApiError(502, "일부 항목이 실패했습니다: %s. 로그를 확인해 주세요."
                               % ", ".join(PREPARE_LABELS[a] for a in failed))

    def run_upgrade(self, job):
        server = self.store.server(job.server)
        with self.server_slot(server["name"]).hold(job):
            self._run_upgrade(job, server)

    def _win_upload(self, job, server, name, local_path=WIN_SCRIPT):
        job.phase = "분석 스크립트 보내는 중"
        code, out = scp_upload(server, local_path, name)
        if code != 0:
            text = with_ssh_hint(server, code, out).decode("utf-8", "replace").strip()
            if text:
                job.log(text)
            raise ApiError(502, "분석 스크립트를 서버로 보내지 못했습니다 (scp 종료 코드 %d)." % code)

    def _install_windows(self, job, server):
        temp = None
        if job.source == "github":
            # 서버에 인터넷이 없어도 되도록 웹 UI가 GitHub에서 받아 scp로 보냅니다.
            repo, channel, branch = update_source(self.store.settings())
            job.phase = "GitHub에서 받는 중"
            info, data = fetch_win_script(repo, channel, branch)
            version, commit = info["version"], info["commit"]
            label = "github:%s@%s" % (repo, info["ref"])
            ref = info["ref"] if info["ref"] == "v" + version else "%s (v%s)" % (info["ref"], version)
            job.log("GitHub %s %s의 분석 스크립트를 설치합니다 (커밋 %s): %s" % (repo, ref, commit[:7], server["tool"]))
            fd, temp = tempfile.mkstemp(prefix="kdump-analyzer-", suffix=".ps1")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            local_path = temp
        else:
            local = local_info()
            version, commit = local["version"], local["commit"]
            label = "webui:%s" % (commit[:7] or "v" + version)
            job.log("웹 UI 버전 v%s의 분석 스크립트를 설치합니다: %s" % (version, server["tool"]))
            local_path = WIN_SCRIPT
        try:
            argv, upload = win_install_command(server, version, commit, label)
            self._win_upload(job, server, upload, local_path)
        finally:
            if temp:
                os.remove(temp)
        job.phase = "설치 중"
        code, _ = self._stream(job, server, argv, timeout=300)
        if code != 0:
            raise ApiError(502, "설치에 실패했습니다 (종료 코드 %d). 관리자 계정인지 확인해 주세요." % code)
        info = win_server_version(server)
        job.version = info.get("version")
        job.log("설치된 버전: %s" % (info.get("version") or "확인 실패"))

    def _run_upgrade(self, job, server):
        if is_windows(server):
            return self._install_windows(job, server)
        settings = self.store.settings()
        repo, channel, branch = update_source(settings)
        if not REPO_RE.match(repo) or not BRANCH_RE.match(branch):
            raise ApiError(400, "업데이트 저장소나 브랜치 형식이 올바르지 않습니다.")
        ref, ref_kind = branch, "heads"
        if job.source == "local":
            local = local_info()
            commit = local["commit"]
            label = "webui:%s" % (commit[:7] or "v" + local["version"])
            job.phase = "설치 파일 만드는 중 (v%s)" % local["version"]
            stdin = build_bundle()
            job.log("웹 UI 버전 v%s%s 를 보냅니다 (%d KB)" % (
                local["version"], " (%s)" % commit[:7] if commit else "", max(1, len(stdin) // 1024)))
        else:
            if channel == "release":
                job.phase = "최신 릴리스 확인 중"
                try:
                    ref, ref_kind = latest_release_tag(repo)[0], "tags"
                except Exception as error:  # noqa: BLE001
                    raise ApiError(502, "최신 릴리스를 확인하지 못했습니다: %s" % error)
                job.log("GitHub 최신 릴리스 %s를 설치합니다" % ref)
            commit, label, stdin = "", "github:%s@%s" % (repo, ref), None
        job.phase = "설치 중"
        code, _ = self._stream(job, server, ["sh", "-c", REMOTE_INSTALL, "sh", server["tool"], job.source,
                                             repo, ref, commit, label, ref_kind], stdin, timeout=PREPARE_TIMEOUT)
        if code != 0:
            raise ApiError(502, "설치에 실패했습니다 (종료 코드 %d). 로그를 확인해 주세요. 기존 설치는 그대로입니다." % code)
        job.phase = "설치 확인 중"
        info = server_version(server)
        job.version = info.get("version")
        job.log("설치된 버전: %s" % (info.get("version") or "확인 실패"))

    def run_uninstall(self, job):
        server = self.store.server(job.server)
        with self.server_slot(server["name"]).hold(job):
            self._run_uninstall(job, server)

    def _run_uninstall(self, job, server):
        mode = job.actions[0] if job.actions else "program"
        job.phase = "설치 확인 중"
        before = server_version(server)
        if not before.get("ok"):
            raise ApiError(502, "서버에 접속하지 못했습니다: %s" % before.get("error", ""))
        if not before.get("installed"):
            raise ApiError(400, "이 서버에는 설치된 분석 도구가 없습니다.")
        job.log("%s v%s (%s)를 지웁니다: %s" % ("분석 스크립트" if is_windows(server) else "analyze-kdump",
                                          before.get("version", "?"), before.get("prefix") or server["tool"],
                                          "설치 폴더 통째로" if mode == "all" else "프로그램 파일만"))
        job.phase = "삭제 중"
        if is_windows(server):
            argv = win_uninstall_command(server, mode)
        else:
            argv = ["sh", "-c", REMOTE_UNINSTALL, "sh", server["tool"], mode] + list(PROGRAM_FILES)
        code, _ = self._stream(job, server, argv, timeout=600)
        if code != 0:
            raise ApiError(502, "삭제하지 못했습니다 (종료 코드 %d). 로그를 확인해 주세요." % code)
        job.phase = "삭제 확인 중"
        after = server_version(server)
        if after.get("installed"):
            raise ApiError(502, "삭제한 뒤에도 설치가 남아 있습니다 (v%s). 로그를 확인해 주세요." % after.get("version", "?"))
        job.log("삭제를 마쳤습니다. 이 서버는 이제 무설치 실행으로 분석합니다.")

    def run_download(self, job):
        server = self.store.server(job.server)
        with self.server_slot(server["name"]).hold(job):
            self._run_download(job, server)

    def _run_download(self, job, server):
        """덤프를 웹 UI 데이터 폴더(dumps/<서버>/)로 받습니다. Linux는 sudo로 읽어 SSH로, Windows는 scp로 받습니다."""
        if not dump_in_dir(server, job.vmcore or ""):
            raise ApiError(400, "덤프 디렉터리(%s) 안의 덤프만 받을 수 있습니다." % server["crash_dir"])
        job.phase = "덤프 크기 확인 중"
        item = next((i for i in list_vmcores(server) if i["path"] == job.vmcore), None)
        if not item:
            raise ApiError(404, "서버에 덤프가 없습니다: %s" % job.vmcore)
        size = item["size"]
        folder = os.path.join(self.store.dir, "dumps", server["name"])
        os.makedirs(folder, exist_ok=True)
        free = shutil.disk_usage(folder).free
        if free < size + 1024 ** 3:
            raise ApiError(507, "웹 UI를 실행하는 컴퓨터의 남은 공간이 모자랍니다: 필요 %s, 남은 공간 %s (여유 1GB 포함)"
                           % (human_size(size + 1024 ** 3), human_size(free)))
        base = local_dump_name(server, job.vmcore)
        dest, n = os.path.join(folder, base), 2
        while os.path.exists(dest):
            stem, ext = os.path.splitext(base)
            dest, n = os.path.join(folder, "%s-%d%s" % (stem, n, ext)), n + 1
        part = dest + ".part"
        job.log("받는 중: %s (%s) -> %s" % (job.vmcore, human_size(size), dest))
        if is_windows(server):
            argv = scp_download_args(server, job.vmcore, part)
            out = open(os.devnull, "wb")
        else:
            argv = ssh_args(server) + [remote_command(server, ["sh", "-c", REMOTE_DUMP_CAT, "sh", server["crash_dir"], job.vmcore])]
            out = open(part, "wb")
        started = time.time()
        try:
            with out:
                proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.PIPE)
                while proc.poll() is None:
                    if job.cancelled:
                        proc.kill()
                        break
                    got = os.path.getsize(part) if os.path.exists(part) else 0
                    job.phase = "받는 중"
                    job.progress = {"current": got // 1048576, "total": max(1, size // 1048576),
                                    "label": "%s / %s" % (human_size(got), human_size(size)),
                                    "elapsed": int(time.time() - started)}
                    time.sleep(1)
                err = with_ssh_hint(server, proc.returncode or 1, proc.communicate()[1]).decode("utf-8", "replace").strip()
            got = os.path.getsize(part) if os.path.exists(part) else 0
            if job.cancelled:
                raise JobCancelled()
            if proc.returncode != 0 or got != size:
                if err:
                    job.log(err[-500:])
                raise ApiError(502, "덤프를 받지 못했습니다 (종료 코드 %s, 받은 크기 %s / %s)."
                               % (proc.returncode, human_size(got), human_size(size)))
            os.replace(part, dest)
            part = None
        finally:
            if part and os.path.exists(part):
                os.remove(part)
        job.saved = dest
        job.progress = None
        job.log("저장했습니다: %s (%d초)" % (dest, time.time() - started))

    def run_move(self, job):
        server = self.store.server(job.server)
        with self.server_slot(server["name"]).hold(job):
            self._run_move(job, server)

    def _run_move(self, job, server):
        if is_windows(server):
            raise ApiError(400, "설치 위치 옮기기는 Linux 서버에서만 합니다.")
        job.phase = "설치 위치 확인 중"
        before = server_version(server)
        if not before.get("ok"):
            raise ApiError(502, "서버에 접속하지 못했습니다: %s" % before.get("error", ""))
        if not before.get("installed"):
            raise ApiError(400, "이 서버에는 analyze-kdump가 설치되어 있지 않습니다.")
        prefix = before.get("prefix") or ""
        if prefix != LEGACY_PREFIX:
            raise ApiError(400, "예전 기본 위치(%s)에 설치된 서버만 옮길 수 있습니다. 지금 위치: %s" % (LEGACY_PREFIX, prefix or "알 수 없음"))
        job.log("지금 위치: %s (v%s) -> 옮길 위치: %s" % (prefix, before.get("version", "?"), MOVE_TARGET))

        # 1) 옮기기 기능이 있는 install.sh가 필요하므로 웹 UI 버전으로 먼저 업그레이드합니다.
        job.log("===== 1/2 웹 UI 버전으로 업그레이드 =====")
        job.source = "local"
        self._run_upgrade(job, server)

        # 2) 설정·서버 목록·vmlinux·로그까지 통째로 옮깁니다.
        job.log("===== 2/2 설치 위치 옮기기 =====")
        job.phase = "설치 위치 옮기는 중"
        code, _ = self._stream(job, server, ["sh", "-c", REMOTE_MOVE, "sh", server["tool"], MOVE_TARGET],
                               timeout=PREPARE_TIMEOUT)
        if code != 0:
            raise ApiError(502, "설치 위치를 옮기지 못했습니다 (종료 코드 %d). 로그를 확인해 주세요. "
                                "옮기기 전에 멈췄다면 기존 설치는 그대로입니다." % code)

        # 서버 설정의 원격 경로가 예전 위치를 가리키면 새 위치로 바꿉니다(예전 경로 링크로도 동작은 합니다).
        tool = server.get("tool") or ""
        if tool.startswith(LEGACY_PREFIX + "/"):
            updated = dict(server, tool=MOVE_TARGET + tool[len(LEGACY_PREFIX):])
            self.store.save_server(updated, original=server["name"])
            job.log("서버 설정의 원격 analyze-kdump 경로를 바꿨습니다: %s" % updated["tool"])
            server = updated
        job.phase = "설치 확인 중"
        info = server_version(server)
        job.version = info.get("version")
        job.log("설치 위치: %s, 버전: %s" % (info.get("prefix") or "확인 실패", info.get("version") or "확인 실패"))
        if info.get("prefix") != MOVE_TARGET:
            raise ApiError(502, "옮긴 뒤 설치 위치가 %s가 아닙니다. 로그를 확인해 주세요." % MOVE_TARGET)

    # ---- LLM 분석

    def run_llm(self, job):
        with self.llm_slot.hold(job):
            self._run_llm(job)

    def _run_llm(self, job):
        settings = self.store.settings()
        path = self.store.result_path(job.server, job.report)
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        job.phase = "LLM 분석 중 (%s)" % settings.get("provider")
        job.progress = None
        job.log("LLM 분석 시작: %s %s" % (settings.get("provider"), kdump_llm.resolve_model(settings) or ""))
        result = kdump_llm.analyze(text, settings)

        run_id = job.report[len("kdump-report-"):-len(".txt")]
        directory = self.store.report_dir(job.server)
        name = "kdump-analysis-%s.txt" % run_id
        n = 2
        while os.path.exists(os.path.join(directory, name)):
            name = "kdump-analysis-%s-%d.txt" % (run_id, n)
            n += 1
        with open(os.path.join(directory, name), "w", encoding="utf-8") as f:
            f.write(kdump_llm.analysis_header(path, settings))
            f.write(result.rstrip() + "\n")
        job.analysis = name
        job.log("분석 저장: %s" % name)


# ---------------------------------------------------------------- HTTP

class AutoWatcher:
    """새 덤프 자동 분석: 자동 분석을 켠 서버의 덤프 목록을 주기적으로 읽어, 새로 생긴 덤프로 작업을 시작합니다.

    - 켠 뒤 처음 확인할 때는 이미 있던 덤프를 기준으로만 기록하고 분석하지 않습니다(예전 덤프를 한꺼번에 돌리지 않게).
    - 같은 경로라도 수정 시각이 바뀌면 새 덤프로 봅니다(Windows의 MEMORY.DMP는 블루스크린마다 덮어씀).
    - 방금 쓰인 덤프(SETTLE초 이내)는 다 써질 때까지 다음 확인으로 미룹니다.
    - 본 덤프 목록은 데이터 폴더의 auto-seen.json에 남아 웹 UI를 다시 시작해도 이어집니다.
    """

    TICK = 30        # 확인할 서버가 있는지 보는 간격(초)
    SETTLE = 60      # 수정 시각이 이보다 최근인 덤프는 아직 쓰는 중일 수 있어 미룹니다(초)

    def __init__(self, store, jobs, list_dumps=None, now=time.time):
        self.store = store
        self.jobs = jobs
        self.list_dumps = list_dumps or list_vmcores
        self.now = now
        self.lock = threading.Lock()
        self.status = {}     # 서버 이름 -> {"checked", "next", "error", "found", "baseline"}
        self.stop = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not self.stop.wait(self.TICK):
            try:
                self.tick()
            except Exception as error:  # noqa: BLE001 - 감시 스레드는 멈추지 않게 합니다.
                print("자동 분석 확인 중 오류: %s" % error, file=sys.stderr)

    def interval(self):
        try:
            minutes = int(self.store.settings().get("auto_interval") or DEFAULT_SETTINGS["auto_interval"])
        except (TypeError, ValueError):
            minutes = DEFAULT_SETTINGS["auto_interval"]
        return max(1, min(minutes, 1440)) * 60

    def tick(self, force=False):
        """확인할 때가 된 서버를 확인합니다. force면 시각과 상관없이 모두 확인합니다."""
        servers = [s for s in self.store.servers() if s.get("auto", "off") != "off"]
        names = {s["name"] for s in servers}
        seen = self.store._load("auto-seen.json", {})
        # 자동 분석을 끄거나 지운 서버의 기록은 버립니다. 다시 켜면 그때 있는 덤프를 새 기준으로 삼습니다.
        dropped = [n for n in seen if n not in names]
        with self.lock:
            for n in list(self.status):
                if n not in names:
                    del self.status[n]
        now = self.now()
        changed = bool(dropped)
        for n in dropped:
            del seen[n]
        for server in servers:
            st = self.status.get(server["name"], {})
            if not force and st.get("next", 0) > now:
                continue
            changed |= self.check(server, seen, now)
        if changed:
            with self.store.lock:
                self.store._save("auto-seen.json", seen)

    def check(self, server, seen, now):
        name = server["name"]
        st = {"checked": now, "next": now + self.interval(), "error": None, "found": 0}
        try:
            items = self.list_dumps(server)
        except Exception as error:  # noqa: BLE001 - 접속 실패는 화면에 보여 주고 다음 주기에 다시 봅니다.
            st["error"] = getattr(error, "message", str(error))[:300]
            with self.lock:
                self.status[name] = dict(self.status.get(name, {}), **st)
            return False
        known = seen.get(name)
        current = {i["path"]: i["mtime"] for i in items}
        if known is None:
            # 처음: 지금 있는 덤프를 기준으로 삼습니다.
            seen[name] = {"since": now, "dumps": current}
            st["baseline"] = len(current)
            with self.lock:
                self.status[name] = st
            return True
        dumps = known.setdefault("dumps", {})
        active = self.jobs.active_vmcores(name)
        kind = "llm" if server.get("auto") == "llm" else "report"
        for path, mtime in sorted(current.items(), key=lambda kv: kv[1]):
            if dumps.get(path) == mtime:
                continue
            if now - mtime < self.SETTLE:
                continue  # 아직 쓰는 중일 수 있습니다. 다음 확인 때 다시 봅니다.
            dumps[path] = mtime
            if path in active:
                continue
            self.jobs.start_report(name, path, kind, auto=True)
            st["found"] += 1
        # 서버에서 사라진 덤프는 기록에서도 지웁니다(같은 이름으로 다시 생기면 새 덤프로 봄).
        for path in [p for p in dumps if p not in current]:
            del dumps[path]
        with self.lock:
            self.status[name] = st
        return True

    def snapshot(self):
        with self.lock:
            return {name: dict(st) for name, st in self.status.items()}


class App:
    def __init__(self, store, port, token=None, supervised=False):
        self.store = store
        self.jobs = Jobs(store)
        self.port = port
        self.token = token or secrets.token_urlsafe(24)
        self.supervised = supervised      # 감시 프로세스 아래에서 실행 중이면 화면에서 다시 시작할 수 있음
        self.started_at = time.time()
        self.httpd = None
        self.restart_requested = False
        self.started_version = version_text()  # 이 서버 프로세스를 시작할 때의 버전
        self.latest = None
        threading.Thread(target=self.check_latest, daemon=True).start()
        for name in store.protect_existing_secrets():
            print("평문으로 저장돼 있던 비밀을 암호화했습니다: secrets/%s" % name)
        self.auto = AutoWatcher(store, self.jobs)
        self.auto.start()

    def check_latest(self):
        settings = self.store.settings()
        self.latest = fetch_latest(*update_source(settings), base=local_info()["commit"])
        return self.latest

    def public_settings(self):
        settings = self.store.settings()
        settings["api_key_saved"] = bool(settings.get("api_key_file") and os.path.exists(settings["api_key_file"]))
        settings["cli_token_saved"] = bool(settings.get("cli_token_file") and os.path.exists(settings["cli_token_file"]))
        settings["secret_protection"] = kdump_llm.secret_protection()
        return settings


class Handler(http.server.BaseHTTPRequestHandler):
    app = None
    server_version = "kdump-webui"

    def log_message(self, fmt, *args):  # 접속 로그는 콘솔을 어지럽히므로 남기지 않습니다.
        pass

    # ---- 보안 확인

    def _host_ok(self):
        host = self.headers.get("Host", "")
        allowed = {"127.0.0.1:%d" % self.app.port, "localhost:%d" % self.app.port}
        if host not in allowed:
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + h for h in allowed}:
            return False
        return True

    def _authed(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            key, _, value = part.strip().partition("=")
            if key == "kt" and secrets.compare_digest(value, self.app.token):
                return True
        return False

    # ---- 응답

    def _send(self, status, body, content_type="application/json; charset=utf-8", headers=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False))

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            raise ApiError(400, "요청 형식이 올바르지 않습니다.")

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_DELETE(self):
        self._handle("DELETE")

    def _handle(self, method):
        if not self._host_ok():
            return self._send(403, "forbidden", "text/plain")
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)

        if method == "GET" and url.path == "/" and query.get("t", [""])[0]:
            if secrets.compare_digest(query["t"][0], self.app.token):
                return self._send(302, "", "text/plain", {
                    "Location": "/", "Set-Cookie": "kt=%s; Path=/; HttpOnly; SameSite=Strict" % self.app.token})
            return self._send(403, "invalid token", "text/plain")

        if not self._authed():
            return self._send(403, "<meta charset=utf-8><p>kdump-analyzer 웹 UI를 시작할 때 출력된 주소(토큰 포함)로 접속해 주세요.</p>",
                              "text/html; charset=utf-8")

        try:
            if url.path.startswith("/api/"):
                return self._api(method, url.path, query)
            if method == "GET":
                return self._static(url.path)
            raise ApiError(404, "not found")
        except ApiError as error:
            self._json(error.status, {"error": error.message})
        except kdump_llm.LLMError as error:
            self._json(502, {"error": str(error)})
        except (ValueError, TypeError) as error:
            # 숫자 칸에 글자를 넣는 등 잘못된 입력은 연결을 끊지 않고 이유를 돌려줍니다.
            self._json(400, {"error": "입력 값이 올바르지 않습니다: %s" % error})

    def _static(self, path):
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        if not re.match(r"^[A-Za-z0-9._-]+$", name):
            raise ApiError(404, "not found")
        full = os.path.join(STATIC_DIR, name)
        if not os.path.isfile(full):
            raise ApiError(404, "not found")
        types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
        with open(full, "rb") as f:
            self._send(200, f.read(), types.get(os.path.splitext(name)[1], "application/octet-stream"),
                       {"Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'"})

    def _api(self, method, path, query):
        app, store = self.app, self.app.store
        parts = path.strip("/").split("/")[1:]

        if parts == ["state"] and method == "GET":
            return self._json(200, {"version": version_text(), "settings": app.public_settings(),
                                    "servers": store.servers(), "jobs": app.jobs.recent(),
                                    "auto": app.auto.snapshot(),
                                    "platform": sys.platform, "api": API_LEVEL,
                                    "running_version": app.started_version,
                                    "supervised": app.supervised, "started_at": app.started_at})
        if parts == ["auto"] and method == "GET":
            return self._json(200, {"status": app.auto.snapshot(),
                                    "jobs": [j for j in app.jobs.recent() if j.get("auto")]})
        if parts == ["auto", "log"] and method == "GET":
            # 최근 자동 분석: 끝난 작업 기록(auto-log.json)과 지금 진행 중이거나 대기 중인 자동 작업
            active = [j for j in app.jobs.recent() if j.get("auto") and j.get("status") in ("queued", "running")]
            return self._json(200, {"log": store.auto_log(), "active": active})
        if parts == ["auto", "check"] and method == "POST":
            app.auto.tick(force=True)
            return self._json(200, {"status": app.auto.snapshot(),
                                    "jobs": [j for j in app.jobs.recent() if j.get("auto")]})
        if parts == ["shutdown"] and method == "POST":
            body = self._body()
            with app.jobs.lock:
                active = [j for j in app.jobs.items.values() if j.status in ("queued", "running")]
            if active and not body.get("force"):
                raise ApiError(409, "진행 중이거나 대기 중인 작업이 %d개 있습니다. 끝난 뒤 종료해 주세요." % len(active))
            threading.Timer(0.3, app.httpd.shutdown).start()
            return self._json(200, {"ok": True})
        if parts == ["restart"] and method == "POST":
            body = self._body()
            if not app.supervised:
                raise ApiError(409, "이 웹 UI는 화면에서 다시 시작할 수 없는 방식으로 실행되었습니다. "
                                    "콘솔에서 Ctrl+C로 끈 뒤 python webui/kdump-webui.py로 다시 실행해 주세요.")
            with app.jobs.lock:
                active = [j for j in app.jobs.items.values() if j.status in ("queued", "running")]
            if active and not body.get("force"):
                raise ApiError(409, "진행 중이거나 대기 중인 작업이 %d개 있습니다. 끝난 뒤 다시 시작해 주세요." % len(active))
            app.restart_requested = True
            # 응답을 보낸 뒤 서버를 멈춥니다. serve_forever가 끝나면 RESTART_EXIT로 종료합니다.
            threading.Timer(0.3, app.httpd.shutdown).start()
            return self._json(200, {"ok": True, "version": version_text()})

        if parts == ["servers"] and method == "POST":
            body = self._body()
            return self._json(200, store.save_server(body, body.get("original")))
        if len(parts) == 2 and parts[0] == "servers" and method == "DELETE":
            store.delete_server(parts[1])
            return self._json(200, {"ok": True})
        if len(parts) == 3 and parts[0] == "servers" and parts[2] == "test" and method == "POST":
            return self._json(200, test_server(store.server(parts[1])))
        if len(parts) == 3 and parts[0] == "servers" and parts[2] == "prepare" and method == "GET":
            return self._json(200, prepare_check(store.server(parts[1])))
        if len(parts) == 3 and parts[0] == "servers" and parts[2] == "version" and method == "GET":
            return self._json(200, server_version(store.server(parts[1])))
        if parts == ["versions"] and method == "GET":
            if query.get("check", [""])[0] == "1" or app.latest is None:
                app.check_latest()
            return self._json(200, {"local": local_info(), "latest": app.latest})
        if parts == ["self-update"] and method == "POST":
            result = self_update(store.settings())
            app.check_latest()
            result["latest"] = app.latest
            return self._json(200, result)
        if len(parts) == 3 and parts[0] == "servers" and parts[2] == "vmcores" and method == "GET":
            server = store.server(parts[1])
            return self._json(200, {"vmcores": list_vmcores(server)})
        if len(parts) == 3 and parts[0] == "servers" and parts[2] == "disk" and method == "GET":
            return self._json(200, {"disk": dump_disk(store.server(parts[1]))})
        if len(parts) == 3 and parts[0] == "servers" and parts[2] == "dump-delete" and method == "POST":
            body = self._body()
            server = store.server(parts[1])
            if body.get("confirm") != server["name"]:
                raise ApiError(400, "확인을 위해 서버 이름을 입력해 주세요.")
            if any(j.get("vmcore") == body.get("path") and j["status"] in ("queued", "running")
                   for j in app.jobs.recent() if j["server"] == server["name"]):
                raise ApiError(409, "이 덤프로 진행 중이거나 대기 중인 작업이 있어 지우지 않았습니다.")
            ok, message = delete_dump(server, body.get("path", ""))
            if not ok:
                raise ApiError(502, "덤프를 지우지 못했습니다: %s" % message)
            return self._json(200, {"ok": True, "message": message})

        if parts == ["jobs"] and method == "POST":
            body = self._body()
            server = store.server(body.get("server", ""))
            kind = body.get("kind")
            if kind in ("report", "llm"):
                vmcore = body.get("vmcore", "")
                if not valid_vmcore_path(server, vmcore):
                    raise ApiError(400, "vmcore 경로가 올바르지 않습니다.")
                job = app.jobs.start_report(server["name"], vmcore, kind)
            elif kind == "prepare":
                actions = body.get("actions")
                if not valid_prepare_actions(server, actions):
                    raise ApiError(400, "준비 항목을 골라 주세요.")
                job = Job(kind, server["name"])
                job.actions = [a for a in PREPARE_ACTIONS if a in actions]  # 정해진 순서로 실행
                app.jobs.start(job, app.jobs.run_prepare, app.jobs.server_slot(server["name"]))
            elif kind == "upgrade":
                source = body.get("source")
                if source not in ("local", "github"):
                    raise ApiError(400, "설치 원본은 local 또는 github여야 합니다.")
                job = Job(kind, server["name"])
                job.source = source
                app.jobs.start(job, app.jobs.run_upgrade, app.jobs.server_slot(server["name"]))
            elif kind == "download":
                vmcore = body.get("vmcore", "")
                if not dump_in_dir(server, vmcore):
                    raise ApiError(400, "덤프 디렉터리 안의 덤프만 받을 수 있습니다.")
                job = Job(kind, server["name"], vmcore=vmcore)
                app.jobs.start(job, app.jobs.run_download, app.jobs.server_slot(server["name"]))
            elif kind == "move":
                job = Job(kind, server["name"])
                job.source = "local"
                app.jobs.start(job, app.jobs.run_move, app.jobs.server_slot(server["name"]))
            elif kind == "uninstall":
                mode = body.get("mode")
                if mode not in UNINSTALL_MODES:
                    raise ApiError(400, "삭제 범위는 program 또는 all이어야 합니다.")
                job = Job(kind, server["name"])
                job.actions = [mode]
                app.jobs.start(job, app.jobs.run_uninstall, app.jobs.server_slot(server["name"]))
            elif kind == "reanalyze":
                store.result_path(server["name"], body.get("report", ""))
                job = Job(kind, server["name"], report=body["report"])
                app.jobs.start(job, app.jobs.run_llm, app.jobs.llm_slot)
            else:
                raise ApiError(400, "알 수 없는 작업입니다.")
            return self._json(200, job.to_dict())
        if parts == ["jobs", "batch"] and method == "POST":
            body = self._body()
            server = store.server(body.get("server", ""))
            kind = body.get("kind")
            vmcores = body.get("vmcores")
            if kind not in ("report", "llm", "llm-only"):
                raise ApiError(400, "알 수 없는 작업입니다.")
            if not isinstance(vmcores, list) or not 1 <= len(vmcores) <= 100:
                raise ApiError(400, "vmcore를 1~100개 골라 주세요.")
            for vmcore in vmcores:
                if not valid_vmcore_path(server, vmcore):
                    raise ApiError(400, "vmcore 경로가 올바르지 않습니다.")
            created, skipped = [], []
            if kind == "llm-only":
                # vmcore마다 가장 최근 리포트로 LLM 분석만 합니다(crash를 다시 실행하지 않음).
                latest = {}
                for record in store.history(server["name"]):
                    rep_ = record.get("report") or {}
                    path_ = rep_.get("vmcore")
                    if path_ and (path_ not in latest or rep_["mtime"] > latest[path_]["mtime"]):
                        latest[path_] = rep_
                for vmcore in vmcores:
                    if vmcore not in latest:
                        skipped.append(vmcore)
                        continue
                    job = Job("reanalyze", server["name"], vmcore=vmcore, report=latest[vmcore]["name"])
                    app.jobs.start(job, app.jobs.run_llm, app.jobs.llm_slot)
                    created.append(job)
            else:
                for vmcore in vmcores:
                    job = Job(kind, server["name"], vmcore=vmcore)
                    app.jobs.start(job, lambda j, llm=(kind == "llm"): app.jobs.run_report(j, llm),
                                   app.jobs.server_slot(server["name"]))
                    created.append(job)
            return self._json(200, {"jobs": [j.to_dict() for j in created], "skipped": skipped})
        if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "cancel" and method == "POST":
            return self._json(200, app.jobs.cancel(parts[1]).to_dict())
        if len(parts) == 2 and parts[0] == "jobs" and method == "GET":
            return self._json(200, app.jobs.get(parts[1]).to_dict())

        if parts == ["results"] and method == "GET":
            server = query.get("server", [""])[0]
            store.server(server)
            return self._json(200, {"results": store.results(server)})
        if parts == ["results", "delete"] and method == "POST":
            body = self._body()
            server = body.get("server", "")
            if not NAME_RE.match(server or ""):
                raise ApiError(400, "잘못된 서버 이름입니다.")
            deleted = store.delete_results(server, body.get("names"), busy=app.jobs.active_results(server))
            return self._json(200, {"deleted": deleted})
        if parts == ["history"] and method == "GET":
            server = query.get("server", [""])[0]
            if server and not NAME_RE.match(server):
                raise ApiError(400, "잘못된 서버 이름입니다.")
            return self._json(200, {"records": store.history(server or None)})
        if parts == ["file"] and method == "GET":
            path_ = store.result_path(query.get("server", [""])[0], query.get("name", [""])[0])
            with open(path_, encoding="utf-8", errors="replace") as f:
                content = f.read()
            summary = None if "-analysis-" in path_ else load_summary(path_)
            return self._json(200, {"content": content, "summary": summary})
        if parts == ["export"] and method == "GET":
            return self._json(200, store.export_data(query.get("server", [""])[0], query.get("name", [""])[0],
                                                     mask=query.get("mask", ["0"])[0] == "1"))

        if parts == ["settings"] and method == "POST":
            body = self._body()
            if "provider" in body and body["provider"] not in kdump_llm.PROVIDERS:
                raise ApiError(400, "알 수 없는 provider입니다.")
            for key in ("max_report_chars", "max_tokens", "timeout", "crash_timeout", "auto_interval"):
                if key in body:
                    body[key] = int(body[key])
            if "auto_interval" in body and not 1 <= body["auto_interval"] <= 1440:
                raise ApiError(400, "자동 분석 확인 주기는 1~1440분이어야 합니다.")
            if "crash_timeout" in body and not 1 <= body["crash_timeout"] <= 1440:
                raise ApiError(400, "crash 제한 시간은 1~1440분이어야 합니다.")
            if "update_repo" in body and not REPO_RE.match(str(body["update_repo"])):
                raise ApiError(400, "업데이트 저장소는 owner/repo 형식이어야 합니다.")
            if "update_branch" in body and not BRANCH_RE.match(str(body["update_branch"])):
                raise ApiError(400, "업데이트 브랜치 이름이 올바르지 않습니다.")
            if "update_channel" in body and body["update_channel"] not in UPDATE_CHANNELS:
                raise ApiError(400, "업데이트 채널은 release 또는 branch여야 합니다.")
            store.save_settings(body)
            return self._json(200, app.public_settings())
        if parts == ["secrets", "api-key"] and method == "POST":
            value = (self._body().get("value") or "").strip()
            if not value:
                raise ApiError(400, "키를 입력해 주세요.")
            provider = store.settings().get("provider")
            path_ = store.save_secret("%s-api-key" % provider, value)
            store.save_settings({"api_key_file": path_})
            return self._json(200, app.public_settings())
        if parts == ["secrets", "cli-token"] and method == "POST":
            value = (self._body().get("value") or "").strip()
            if not value or re.search(r"\s", value):
                raise ApiError(400, "토큰 한 줄을 붙여넣어 주세요.")
            path_ = store.save_secret("claude-oauth-token", value)
            store.save_settings({"cli_token_file": path_})
            return self._json(200, app.public_settings())

        if parts == ["models"] and method == "GET":
            return self._json(200, {"models": kdump_llm.list_models(store.settings())})
        if parts == ["cli", "status"] and method == "GET":
            return self._json(200, kdump_llm.cli_status(store.settings()))
        if parts == ["cli", "test"] and method == "POST":
            settings = store.settings()
            started = time.time()
            if settings.get("provider") in kdump_llm.CLI_PROVIDERS:
                reply = kdump_llm.call_cli(settings, "Reply with exactly: OK", "ping", timeout=120)
            else:
                reply = kdump_llm.call_api(settings, "Reply with exactly: OK", "ping")
            return self._json(200, {"reply": reply[-300:], "elapsed": round(time.time() - started, 1)})

        raise ApiError(404, "알 수 없는 API입니다: %s %s" % (method, path))


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    # 다시 시작할 때 같은 포트를 바로 쓰려면 리눅스·macOS에서는 SO_REUSEADDR가 필요합니다.
    # Windows의 SO_REUSEADDR는 다른 프로그램이 쓰는 포트까지 빼앗을 수 있어 켜지 않습니다.
    allow_reuse_address = os.name != "nt"


def parse_args():
    parser = argparse.ArgumentParser(description="kdump-analyzer 웹 UI")
    parser.add_argument("--port", type=int, default=8730)
    parser.add_argument("--data-dir", default=os.path.join(os.path.expanduser("~"), ".kdump-tools-web"))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-supervisor", action="store_true",
                        help="감시 프로세스 없이 실행합니다(화면의 다시 시작 버튼을 쓸 수 없음)")
    parser.add_argument("--launch", action="store_true",
                        help="바로가기용: 이미 실행 중이면 그 화면을 열고, 아니면 새로 시작합니다(콘솔 없이 실행할 때 사용)")
    parser.add_argument("--install-shortcut", action="store_true",
                        help="Windows 바탕화면과 시작 메뉴에 아이콘 바로가기를 만듭니다")
    parser.add_argument("--remove-shortcut", action="store_true", help="--install-shortcut으로 만든 바로가기를 지웁니다")
    parser.add_argument("--shortcut-dir", help="바로가기를 만들 폴더(기본: 바탕화면과 시작 메뉴)")
    return parser.parse_args()


def bind_free_port(start):
    for candidate in range(start, start + 10):
        try:
            return Server(("127.0.0.1", candidate), Handler), candidate
        except OSError:
            continue
    sys.exit("사용할 수 있는 포트가 없습니다 (%d~%d)." % (start, start + 9))


def bind_exact_port(port, wait=20):
    """다시 시작할 때는 앞 서버가 막 놓은 포트를 다시 잡습니다. 잠깐 사용 중일 수 있어 기다립니다."""
    deadline = time.time() + wait
    while True:
        try:
            return Server(("127.0.0.1", port), Handler)
        except OSError:
            if time.time() > deadline:
                raise
            time.sleep(0.5)


RUN_INFO = "run.json"
APP_NAME = "kdump-analyzer 웹 UI"
# 예전 이름으로 만든 바로가기. 새로 만들거나 지울 때 함께 지웁니다.
LEGACY_APP_NAMES = ("kdump-tools 웹 UI",)


def run_info_path(data_dir):
    return os.path.join(data_dir, RUN_INFO)


def read_run_info(data_dir):
    try:
        with open(run_info_path(data_dir), encoding="utf-8") as f:
            info = json.load(f)
        return info if isinstance(info.get("port"), int) and info.get("token") else None
    except (OSError, ValueError, AttributeError):
        return None


def write_run_info(data_dir, port, token):
    os.makedirs(data_dir, exist_ok=True)
    path = run_info_path(data_dir)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "port": port, "token": token, "started": time.time()}, f)


def remove_run_info(data_dir):
    try:
        info = read_run_info(data_dir)
        if info and info.get("pid") == os.getpid():
            os.remove(run_info_path(data_dir))
    except OSError:
        pass


def instance_alive(info):
    """저장된 정보의 서버가 실제로 응답하는지 확인합니다(토큰 주소로 접속해 봄)."""
    # 토큰 주소(/?t=)는 쿠키를 심고 다른 주소로 넘기는 응답이라, 쿠키를 직접 보내 상태 API로 확인합니다.
    try:
        request = urllib.request.Request("http://127.0.0.1:%d/api/state" % info["port"],
                                         headers={"Cookie": "kt=%s" % info["token"]})
        with urllib.request.urlopen(request, timeout=2) as res:
            return res.status == 200
    except Exception:  # noqa: BLE001
        return False


def instance_url(info):
    return "http://127.0.0.1:%d/?t=%s" % (info["port"], info["token"])


def setup_log(data_dir):
    """콘솔이 없으면(pythonw) 출력할 곳이 없어 print가 실패하므로 데이터 폴더의 로그 파일로 보냅니다."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "webui.log")
    try:
        if os.path.getsize(path) > 1024 * 1024:
            os.replace(path, path + ".old")
    except OSError:
        pass
    log = open(path, "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log


def show_error(message):
    """콘솔이 없을 때는 오류를 대화 상자로 알립니다."""
    print(message, file=sys.stderr)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x10)  # MB_ICONERROR
        except Exception:  # noqa: BLE001
            pass


def launch(args):
    """바로가기에서 실행: 이미 떠 있으면 그 화면을 열고, 아니면 새로 시작합니다."""
    info = read_run_info(args.data_dir)
    if info and instance_alive(info):
        if not args.no_browser:
            webbrowser.open(instance_url(info))
        print("이미 실행 중입니다: http://127.0.0.1:%d/" % info["port"], flush=True)
        return
    supervise(args)


def powershell_quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def shortcut_command(args):
    """바로가기 설치·삭제용 PowerShell 명령. 시스템의 실행 정책은 건드리지 않습니다(-Command)."""
    if os.name != "nt":
        sys.exit("바로가기는 Windows에서만 만들 수 있습니다.")
    python = sys.executable
    pythonw = os.path.join(os.path.dirname(python), "pythonw.exe")
    if not os.path.exists(pythonw):
        sys.exit("pythonw.exe를 찾을 수 없습니다(%s). Python을 다시 설치하거나 'py launcher'를 확인해 주세요." % pythonw)
    script = os.path.abspath(__file__)
    repo = os.path.dirname(os.path.dirname(script))
    icon = os.path.join(repo, "windows", "kdump-tools.ico")
    arguments = '"%s" --launch' % script
    if args.data_dir != parse_defaults().data_dir:
        arguments += ' --data-dir "%s"' % os.path.abspath(args.data_dir)
    if args.shortcut_dir:
        folders = "@(%s)" % powershell_quote(os.path.abspath(args.shortcut_dir))
    else:
        folders = "@([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))"
    name = APP_NAME + ".lnk"
    # 예전 이름의 바로가기는 새로 만들 때도 지워서 아이콘이 두 개 생기지 않게 합니다.
    legacy = ", ".join(powershell_quote(n + ".lnk") for n in LEGACY_APP_NAMES)
    remove_legacy = ("foreach ($f in %s) { foreach ($n in @(%s)) { $p = Join-Path $f $n; "
                     "if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p; 'removed: ' + $p } } }; ") % (folders, legacy)
    if args.remove_shortcut:
        body = remove_legacy + "foreach ($f in %s) { $p = Join-Path $f %s; if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p; 'removed: ' + $p } }" % (
            folders, powershell_quote(name))
    else:
        body = remove_legacy + ("$sh = New-Object -ComObject WScript.Shell; foreach ($f in %s) { New-Item -ItemType Directory -Force -Path $f | Out-Null; "
                "$p = Join-Path $f %s; $l = $sh.CreateShortcut($p); $l.TargetPath = %s; $l.Arguments = %s; "
                "$l.WorkingDirectory = %s; $l.IconLocation = %s; $l.Description = %s; $l.WindowStyle = 7; $l.Save(); 'created: ' + $p }") % (
            folders, powershell_quote(name), powershell_quote(pythonw), powershell_quote(arguments), powershell_quote(repo),
            powershell_quote(icon + ",0"), powershell_quote("kdump vmcore 분석 웹 UI"))
    return body


def parse_defaults():
    class Defaults:
        data_dir = os.path.join(os.path.expanduser("~"), ".kdump-tools-web")
    return Defaults


def manage_shortcut(args):
    command = shortcut_command(args)
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                             "[Console]::OutputEncoding = [Text.Encoding]::UTF8; " + command],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = result.stdout.decode("utf-8", errors="replace").strip()
    print(text or ("완료" if result.returncode == 0 else "실패"))
    if result.returncode != 0:
        sys.exit(result.returncode)
    if not args.remove_shortcut:
        print("\n바탕화면과 시작 메뉴의 '%s' 아이콘을 더블클릭하면 콘솔 없이 실행되고 브라우저가 열립니다." % APP_NAME)


def print_banner(data_dir, url):
    print("kdump-analyzer 웹 UI v%s" % version_text())
    print("데이터: %s" % data_dir)
    print("접속 주소 (이 주소로만 접속할 수 있습니다):")
    print("  " + url, flush=True)


def detach_supervisor_pipe():
    """감시 프로세스와 연결된 표준 입력을 따로 떼어 두고, 표준 입력은 빈 장치로 바꿉니다.
    이 파이프는 닫히지 않으므로 그대로 두면 ssh·git·CLI 같은 하위 명령이 물려받아 입력을 기다리며 멈춥니다."""
    pipe_fd = os.dup(0)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.close(devnull)
    if os.name == "nt":
        # 하위 프로세스는 C 런타임의 0번이 아니라 Win32 표준 입력 핸들을 물려받으므로 그것도 바꿉니다.
        import ctypes
        import msvcrt
        ctypes.windll.kernel32.SetStdHandle(-10, msvcrt.get_osfhandle(0))  # STD_INPUT_HANDLE
    return pipe_fd


def watch_supervisor(pipe_fd):
    """감시 프로세스가 사라지면(창을 닫거나 강제 종료) 파이프가 닫히므로 서버도 끝냅니다."""
    try:
        while os.read(pipe_fd, 4096):
            pass
    except OSError:
        pass
    os._exit(0)


def serve(args, supervised=False):
    store = Store(args.data_dir)
    if supervised:
        port = int(os.environ[ENV_PORT])
        httpd = bind_exact_port(port)
        token = os.environ[ENV_TOKEN]
    else:
        httpd, port = bind_free_port(args.port)
        token = None
    app = App(store, port, token=token, supervised=supervised)
    app.httpd = httpd
    Handler.app = app
    if supervised:
        threading.Thread(target=watch_supervisor, args=(detach_supervisor_pipe(),), daemon=True).start()
    else:
        url = "http://127.0.0.1:%d/?t=%s" % (port, app.token)
        print_banner(args.data_dir, url)
        if not args.no_browser:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    if app.restart_requested:
        os._exit(RESTART_EXIT)
    if not supervised:
        print("\n종료합니다.")


def supervise(args):
    """콘솔을 맡아 서버 프로세스를 띄웁니다. 서버가 RESTART_EXIT로 끝나면 디스크에 있는 (업데이트된) 코드로
    다시 띄웁니다. 토큰과 포트는 처음 정한 값을 계속 써서 브라우저가 다시 로그인하지 않아도 됩니다."""
    probe, port = bind_free_port(args.port)
    probe.server_close()
    token = secrets.token_urlsafe(24)
    url = "http://127.0.0.1:%d/?t=%s" % (port, token)
    print_banner(args.data_dir, url)
    write_run_info(args.data_dir, port, token)
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    env = dict(os.environ, **{ENV_WORKER: "1", ENV_TOKEN: token, ENV_PORT: str(port)})
    argv = [sys.executable, os.path.abspath(__file__)] + [a for a in sys.argv[1:] if a != "--launch"]
    try:
        while True:
            # 표준 출력·오류를 명시해야 콘솔이 없을 때(pythonw)도 하위 프로세스가 유효한 핸들을 받습니다.
            child = subprocess.Popen(argv, env=env, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=sys.stderr)
            try:
                code = child.wait()
            except KeyboardInterrupt:
                # 파이프를 닫으면 서버 프로세스가 스스로 끝납니다. 끝나지 않으면 강제로 끝냅니다.
                try:
                    child.stdin.close()
                    child.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
                    child.kill()
                print("\n종료합니다.")
                return
            if code == RESTART_EXIT:
                print("다시 시작합니다: v%s" % version_text(), flush=True)
                continue
            if code == 0:
                print("종료했습니다.", flush=True)
            sys.exit(code)
    finally:
        remove_run_info(args.data_dir)


def main():
    args = parse_args()
    if args.install_shortcut or args.remove_shortcut:
        return manage_shortcut(args)
    setup_log(args.data_dir)
    try:
        if os.environ.get(ENV_WORKER) == "1":
            serve(args, supervised=True)
        elif args.no_supervisor:
            serve(args)
        elif args.launch:
            launch(args)
        else:
            supervise(args)
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001 - 콘솔이 없으면 오류가 보이지 않으므로 대화 상자로 알립니다.
        show_error("웹 UI를 시작하지 못했습니다.\n\n%s: %s\n\n자세한 내용: %s" % (
            type(error).__name__, error, os.path.join(args.data_dir, "webui.log")))
        raise


if __name__ == "__main__":
    main()
