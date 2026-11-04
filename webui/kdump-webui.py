#!/usr/bin/env python3
"""kdump-tools 웹 UI

노트북(Windows·macOS·Linux)에서 실행하는 로컬 웹 앱입니다. 브라우저로 조작하고,
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
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kdump_llm  # noqa: E402

APP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(APP_DIR)
STATIC_DIR = os.path.join(APP_DIR, "static")
ANALYZE_SCRIPT = os.path.join(REPO_DIR, "bin", "analyze-kdump")

NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
FILE_RE = re.compile(r"^kdump-(report|analysis)-[A-Za-z0-9._-]+\.txt$")
PROGRESS_RE = re.compile(r"crash 리포트 생성 \[[#.]+\] (\d+)/(\d+) (.*?) \((\d+)초\)")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

DEFAULT_SETTINGS = {
    "provider": "openai", "model": "", "base_url": "", "api_key_file": "",
    "cli_path": "", "cli_token_file": "", "cli_args": "",
    "mask": True, "max_report_chars": 60000, "max_tokens": 8192, "timeout": 300,
}
DEFAULT_SERVER = {
    "name": "", "target": "", "port": 22, "key_file": "", "sudo": True,
    "tool": "/opt/kdump-tools/bin/analyze-kdump", "crash_dir": "/var/crash", "method": "auto",
}


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
        if not server["target"] or re.search(r"\s", server["target"]):
            raise ApiError(400, "접속 대상(user@host)을 입력해 주세요.")
        if server["method"] not in ("auto", "installed", "upload"):
            raise ApiError(400, "분석 방식이 올바르지 않습니다.")
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
        path = os.path.join(self.dir, "secrets", filename)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value.strip() + "\n")
        return path

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
        records.sort(key=lambda r: r["time"], reverse=True)
        return records

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


HEAD_KEYS = ("vmcore", "kernel", "generated", "provider", "model", "source_report")
VERDICT_RE = re.compile(r"^\|\s*\**\s*(판정|결론|verdict|root cause)\s*\**\s*\|\s*(.+?)\s*\|?\s*$", re.I)


def _plain(text):
    text = re.sub(r"[*`]", "", text).strip()
    return text if len(text) <= 200 else text[:199] + "…"


def parse_result_head(path):
    """리포트·분석 파일 앞부분에서 기록 화면에 보일 정보를 읽습니다."""
    info = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(16384)
    except OSError:
        return info
    lines = head.splitlines()
    for line in lines[:12]:
        key, sep, value = line.partition(":")
        if sep and key.strip() in HEAD_KEYS:
            info[key.strip()] = value.strip()
    if "-analysis-" in os.path.basename(path):
        body = head.split("\n\n", 1)[-1]
        verdict = ""
        for line in body.splitlines():
            m = VERDICT_RE.match(line)
            if m:
                verdict = m.group(2)
                break
        if not verdict:  # 표가 없는 분석은 제목이 아닌 첫 문장을 씁니다.
            verdict = next((l for l in body.splitlines()
                            if l.strip() and not l.lstrip().startswith(("#", "|", "```", "---"))), "")
        info["verdict"] = _plain(verdict.lstrip("-*> 0123456789."))
    else:
        m = re.search(r'^\s*PANIC:\s*"?(.*?)"?\s*$', head, re.M)
        if m and m.group(1):
            info["panic"] = _plain(m.group(1))
    return info


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------- SSH

def ssh_args(server):
    args = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new", "-p", str(server.get("port") or 22)]
    if server.get("key_file"):
        args += ["-i", server["key_file"]]
    return args + [server["target"]]


def remote_command(server, argv):
    command = " ".join(shlex.quote(a) for a in argv)
    return ("sudo -n " + command) if server.get("sudo") else command


def ssh_run(server, argv, stdin=None, timeout=60):
    """원격 명령을 실행하고 (종료 코드, 출력)을 돌려줍니다."""
    try:
        result = subprocess.run(ssh_args(server) + [remote_command(server, argv)], input=stdin,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        return 124, b"SSH timeout"
    except OSError as error:
        return 127, ("ssh를 실행할 수 없습니다: %s" % error).encode()


def ssh_text(server, argv, timeout=60):
    code, out = ssh_run(server, argv, timeout=timeout)
    return code, out.decode("utf-8", errors="replace")


def probe_method(server):
    code, out = ssh_text(server, ["sh", "-c",
                                  'if [ -x "$1" ]; then echo installed; '
                                  'elif command -v crash >/dev/null 2>&1; then echo upload; '
                                  'else echo none; fi', "sh", server["tool"]], timeout=30)
    out = out.strip().splitlines()[-1:] or [""]
    return out[0] if code == 0 else ""


def test_server(server):
    code, out = ssh_text(server, ["sh", "-c", """
echo "host=$(hostname)"; echo "user=$(id -un)"
if [ -x "$1" ]; then echo "tool=$("$1" --version 2>/dev/null | grep '^analyze-kdump ' | head -n 1)"; [ -n "$("$1" --version 2>/dev/null | grep '^analyze-kdump ')" ] || echo "tool=installed (version unknown)"; else echo "tool="; fi
if command -v crash >/dev/null 2>&1; then v=$(crash --version 2>&1 | grep -m 1 .); echo "crash=${v:-installed}"; else echo "crash="; fi
echo "vmcores=$(ls -1 "$2"/*/vmcore 2>/dev/null | wc -l)"
""", "sh", server["tool"], server["crash_dir"]], timeout=40)
    info = {"ok": code == 0, "raw": out.strip()[-600:]}
    for line in out.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    if code == 0:
        info["method"] = "installed" if info.get("tool") else ("upload" if info.get("crash") else "none")
    return info


def list_vmcores(server):
    code, out = ssh_text(server, ["sh", "-c", 'stat -c "%Y %s %n" "$1"/*/vmcore 2>/dev/null | sort -rn',
                                  "sh", server["crash_dir"]], timeout=40)
    if code != 0:
        raise ApiError(502, "vmcore 목록을 읽지 못했습니다: %s" % out.strip()[-300:])
    items = []
    for line in out.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[0].isdigit():
            items.append({"mtime": int(parts[0]), "size": int(parts[1]), "path": parts[2]})
    return items


# ---------------------------------------------------------------- 분석 작업

class Job:
    def __init__(self, kind, server, vmcore=None, report=None):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind            # report | llm | reanalyze
        self.server = server
        self.vmcore = vmcore
        self.report = report
        self.analysis = None
        self.status = "running"     # running | done | error
        self.phase = "준비 중"
        self.progress = None        # {"current", "total", "label", "elapsed"}
        self.logs = []
        self.error = None
        self.method = None
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
                    "error": self.error, "method": self.method, "started": self.started,
                    "elapsed": int((self.finished or time.time()) - self.started)}


class Jobs:
    def __init__(self, store):
        self.store = store
        self.items = {}
        self.lock = threading.Lock()

    def start(self, job, target):
        with self.lock:
            self.items[job.id] = job
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
            jobs = sorted(self.items.values(), key=lambda j: j.started, reverse=True)[:20]
        return [j.to_dict() for j in jobs]

    def _run(self, job, target):
        try:
            target(job)
            job.status = "done"
            job.phase = "완료"
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

    # ---- crash 리포트 생성

    def _stream(self, job, server, argv, stdin=None):
        """원격 명령의 출력을 읽으면서 진행 표시(\\r로 갱신되는 줄)를 진행률로 바꿉니다."""
        proc = subprocess.Popen(ssh_args(server) + [remote_command(server, argv)],
                                stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if stdin:
            proc.stdin.write(stdin)
            proc.stdin.close()
        buffer = ""
        text_all = []
        while True:
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while True:
                match = re.search(r"[\r\n]", buffer)
                if not match:
                    break
                segment, sep, buffer = buffer[:match.start()], match.group(), buffer[match.end():]
                segment = ANSI_RE.sub("", segment)
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
        return proc.returncode, "\n".join(text_all)

    def run_report(self, job, llm):
        server = self.store.server(job.server)
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
            argv = ["env", "ANALYZE_KDUMP_PROGRESS=1", server["tool"], "-r", job.vmcore]
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
            code, text = self._stream(job, server, argv, stdin)
            remote_report = ""
            for line in text.splitlines():
                if line.startswith("report:"):
                    remote_report = line.split(":", 1)[1].strip()
            if not remote_report:
                raise ApiError(502, "리포트를 만들지 못했습니다 (종료 코드 %d). 로그를 확인해 주세요." % code)

            job.phase = "리포트 가져오는 중"
            fetch_code, data = ssh_run(server, ["cat", remote_report], timeout=120)
            if fetch_code != 0:
                raise ApiError(502, "리포트를 가져오지 못했습니다.")
            name = os.path.basename(remote_report)
            if not FILE_RE.match(name):
                name = "kdump-report-%s.txt" % time.strftime("%Y%m%d-%H%M%S")
            with open(os.path.join(self.store.report_dir(server["name"]), name), "wb") as f:
                f.write(data)
            job.report = name
            job.log("리포트 저장: %s" % name)
            if code != 0:
                raise ApiError(502, "crash 실행이 실패했습니다 (종료 코드 %d). 리포트 끝의 crash 실행 로그를 확인해 주세요." % code)
        finally:
            if tmpdir:
                ssh_run(server, ["rm", "-rf", tmpdir])

        if llm:
            self.run_llm(job)

    # ---- LLM 분석

    def run_llm(self, job):
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

class App:
    def __init__(self, store, port):
        self.store = store
        self.jobs = Jobs(store)
        self.port = port
        self.token = secrets.token_urlsafe(24)

    def public_settings(self):
        settings = self.store.settings()
        settings["api_key_saved"] = bool(settings.get("api_key_file") and os.path.exists(settings["api_key_file"]))
        settings["cli_token_saved"] = bool(settings.get("cli_token_file") and os.path.exists(settings["cli_token_file"]))
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
            return self._send(403, "<meta charset=utf-8><p>kdump-tools 웹 UI를 시작할 때 출력된 주소(토큰 포함)로 접속해 주세요.</p>",
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
                                    "platform": sys.platform})

        if parts == ["servers"] and method == "POST":
            body = self._body()
            return self._json(200, store.save_server(body, body.get("original")))
        if len(parts) == 2 and parts[0] == "servers" and method == "DELETE":
            store.delete_server(parts[1])
            return self._json(200, {"ok": True})
        if len(parts) == 3 and parts[0] == "servers" and parts[2] == "test" and method == "POST":
            return self._json(200, test_server(store.server(parts[1])))
        if len(parts) == 3 and parts[0] == "servers" and parts[2] == "vmcores" and method == "GET":
            return self._json(200, {"vmcores": list_vmcores(store.server(parts[1]))})

        if parts == ["jobs"] and method == "POST":
            body = self._body()
            server = store.server(body.get("server", ""))
            kind = body.get("kind")
            if kind in ("report", "llm"):
                vmcore = body.get("vmcore", "")
                if not vmcore.startswith("/") or "\n" in vmcore:
                    raise ApiError(400, "vmcore 경로가 올바르지 않습니다.")
                job = Job(kind, server["name"], vmcore=vmcore)
                app.jobs.start(job, lambda j: app.jobs.run_report(j, kind == "llm"))
            elif kind == "reanalyze":
                store.result_path(server["name"], body.get("report", ""))
                job = Job(kind, server["name"], report=body["report"])
                app.jobs.start(job, app.jobs.run_llm)
            else:
                raise ApiError(400, "알 수 없는 작업입니다.")
            return self._json(200, job.to_dict())
        if len(parts) == 2 and parts[0] == "jobs" and method == "GET":
            return self._json(200, app.jobs.get(parts[1]).to_dict())

        if parts == ["results"] and method == "GET":
            server = query.get("server", [""])[0]
            store.server(server)
            return self._json(200, {"results": store.results(server)})
        if parts == ["history"] and method == "GET":
            server = query.get("server", [""])[0]
            if server and not NAME_RE.match(server):
                raise ApiError(400, "잘못된 서버 이름입니다.")
            return self._json(200, {"records": store.history(server or None)})
        if parts == ["file"] and method == "GET":
            path_ = store.result_path(query.get("server", [""])[0], query.get("name", [""])[0])
            with open(path_, encoding="utf-8", errors="replace") as f:
                return self._json(200, {"content": f.read()})

        if parts == ["settings"] and method == "POST":
            body = self._body()
            if "provider" in body and body["provider"] not in kdump_llm.PROVIDERS:
                raise ApiError(400, "알 수 없는 provider입니다.")
            for key in ("max_report_chars", "max_tokens", "timeout"):
                if key in body:
                    body[key] = int(body[key])
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

        raise ApiError(404, "not found")


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def main():
    parser = argparse.ArgumentParser(description="kdump-tools 웹 UI")
    parser.add_argument("--port", type=int, default=8730)
    parser.add_argument("--data-dir", default=os.path.join(os.path.expanduser("~"), ".kdump-tools-web"))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    store = Store(args.data_dir)
    httpd = None
    port = args.port
    for candidate in range(args.port, args.port + 10):
        try:
            httpd = Server(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if not httpd:
        sys.exit("사용할 수 있는 포트가 없습니다 (%d~%d)." % (args.port, args.port + 9))

    Handler.app = App(store, port)
    url = "http://127.0.0.1:%d/?t=%s" % (port, Handler.app.token)
    print("kdump-tools 웹 UI v%s" % version_text())
    print("데이터: %s" % args.data_dir)
    print("접속 주소 (이 주소로만 접속할 수 있습니다):")
    print("  " + url, flush=True)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
