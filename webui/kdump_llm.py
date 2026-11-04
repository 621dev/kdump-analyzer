"""kdump 리포트 LLM 분석 (웹 UI용).

analyze-kdump(bash)의 LLM 처리 부분(민감정보 마스킹, 섹션 단위 입력 축소, provider 호출,
구독 CLI 실행)을 Windows에서도 쓸 수 있도록 Python 표준 라이브러리만으로 옮긴 모듈입니다.
분석 파일 형식은 analyze-kdump와 같습니다.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PROVIDERS = ("openai", "gemini", "claude", "claude-code", "codex")
CLI_PROVIDERS = ("claude-code", "codex")
DEFAULT_MODELS = {"openai": "gpt-4o-mini", "claude": "claude-sonnet-5-5"}

DEFAULT_PROMPT = """You are a senior Linux kernel crash dump analyst.
Analyze the crash report and write a concise Korean incident report.
Include: probable root cause, evidence, impacted subsystem/process, confidence, and recommended next actions.
If evidence is insufficient, say what additional crash commands or data are needed."""

MASK_NOTE = """

Some identifiers in the report are masked as <HOSTNAME>, <IPV4>, <MAC> or <EMAIL>. Treat them as placeholders, not as errors."""


class LLMError(Exception):
    pass


# ---------------------------------------------------------------- 입력 축소

SECTION_RE = re.compile(r"^===== (.+?) =====$", re.M)
# 섹션별 (가중치, 잘릴 때 남길 위치). log는 패닉 메시지가 끝에 있으므로 뒷부분을 남깁니다.
SECTION_POLICY = {
    "crash> sys": (2, "head"),
    "crash> bt": (3, "head"),
    "crash> bt -a": (2, "head"),
    "crash> foreach UN bt": (2, "head"),
    "taint 모듈 관련 태스크 (foreach bt에서 추림)": (2, "head"),
    "crash> log": (3, "tail"),
    "crash> ps": (1, "head"),
}


def _policy(title):
    if title.startswith("crash 실행 로그"):
        return 1, "tail"
    return SECTION_POLICY.get(title, (1, "both"))


def _cut(text, limit, keep):
    if len(text) <= limit:
        return text
    newline = text.find("\n")
    header = text[:newline + 1] if newline >= 0 else ""
    body = text[len(header):]
    marker = "\n[... %d chars truncated for LLM input ...]\n" % (len(text) - limit)
    room = max(limit - len(header) - len(marker), 0)
    if keep == "head":
        body = body[:room] + marker
    elif keep == "tail":
        body = marker + (body[len(body) - room:] if room > 0 else "")
    else:
        head_len = room // 2
        tail_len = room - head_len
        body = body[:head_len] + marker + (body[len(body) - tail_len:] if tail_len > 0 else "")
    return header + body


def fit(text, limit):
    """리포트를 limit 글자 이하로 섹션별로 줄입니다(짧은 섹션은 그대로, 긴 섹션끼리 가중치로 나눔)."""
    if limit <= 0 or len(text) <= limit:
        return text
    matches = list(SECTION_RE.finditer(text))
    if not matches:
        return _cut(text, limit, "both")

    preamble = text[:matches[0].start()]
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group(1), text[match.start():end]))

    budget = max(limit - len(preamble), 0)
    pending = list(range(len(sections)))
    alloc = {}
    while pending:
        unit = budget / sum(_policy(sections[i][0])[0] for i in pending)
        fitted = [i for i in pending if len(sections[i][1]) <= unit * _policy(sections[i][0])[0]]
        if not fitted:
            for i in pending:
                alloc[i] = int(unit * _policy(sections[i][0])[0])
            break
        for i in fitted:
            alloc[i] = len(sections[i][1])
            budget -= alloc[i]
        pending = [i for i in pending if i not in fitted]

    return preamble + "".join(
        _cut(body, alloc[i], _policy(title)[1]) for i, (title, body) in enumerate(sections)
    )


# ---------------------------------------------------------------- 마스킹

IPV4_RE = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])")
MAC_RE = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:])")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
NODENAME_RE = re.compile(r"^\s*NODENAME:\s*(\S+)", re.M)


def mask_text(text):
    """호스트명(sys의 NODENAME, LVM 이름 포함), IPv4, MAC, 이메일을 자리표시자로 바꿉니다."""
    for name in set(NODENAME_RE.findall(text)):
        short = name.split(".")[0]
        patterns = {value: r"(?![A-Za-z0-9-])" for value in (name, short)}
        if "-" in short:
            # device-mapper 이름에서는 '-'가 '--'로 바뀌고 뒤에 VG/LV 구분자 '-'가 붙습니다.
            patterns[short.replace("-", "--")] = r"(?=-(?!-)|[^A-Za-z0-9-]|$)"
        for value in sorted(patterns, key=len, reverse=True):
            if len(value) >= 3:
                text = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(value) + patterns[value], "<HOSTNAME>", text)
    text = EMAIL_RE.sub("<EMAIL>", text)
    text = MAC_RE.sub("<MAC>", text)
    text = IPV4_RE.sub("<IPV4>", text)
    return text


# ---------------------------------------------------------------- 공통

def read_secret(path):
    """비밀 파일의 첫 줄을 공백·CR 없이 읽습니다."""
    if not path:
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.readline().strip()


def build_input(report_text, settings):
    report = report_text
    mask = settings.get("mask", True)
    if mask:
        report = mask_text(report)
    report = fit(report, int(settings.get("max_report_chars") or 60000))
    system = DEFAULT_PROMPT
    prompt_file = settings.get("prompt_file")
    if prompt_file:
        with open(prompt_file, encoding="utf-8", errors="replace") as f:
            system = f.read()
    if mask:
        system += MASK_NOTE
    return system, report


def resolve_model(settings):
    model = settings.get("model") or ""
    if not model:
        model = DEFAULT_MODELS.get(settings.get("provider"), "")
    return model


# ---------------------------------------------------------------- API provider

def _http_json(url, headers, payload, timeout, retries=2):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    last = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")[:500]
            last = LLMError("API 응답 코드 %d: %s" % (error.code, body))
            if error.code not in (408, 429) and error.code < 500:
                raise last
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = LLMError("API 호출 실패: %s" % error)
        if attempt < retries:
            time.sleep(2 ** (attempt + 1))
    raise last


def _api_key(settings):
    key = os.environ.get("LLM_API_KEY", "") or read_secret(settings.get("api_key_file"))
    return key


def call_api(settings, system, user):
    provider = settings["provider"]
    model = resolve_model(settings)
    base = settings.get("base_url") or ""
    key = _api_key(settings)
    timeout = int(settings.get("timeout") or 120)
    max_tokens = int(settings.get("max_tokens") or 8192)
    temperature = settings.get("temperature")
    if not model:
        raise LLMError("모델을 설정해 주세요.")
    if not key and not (provider == "openai" and base):
        raise LLMError("API 키가 없습니다. 설정에서 API 키를 저장하거나 키 파일을 지정해 주세요.")

    headers = {"Content-Type": "application/json"}
    if provider == "openai":
        url = base or "https://api.openai.com/v1/chat/completions"
        if key:
            headers["Authorization"] = "Bearer " + key
        payload = {"model": model, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}]}
        payload["max_tokens" if base else "max_completion_tokens"] = max_tokens
        if temperature not in (None, ""):
            payload["temperature"] = float(temperature)
    elif provider == "gemini":
        name = model if model.startswith("models/") else "models/" + model
        url = base or "https://generativelanguage.googleapis.com/v1beta/%s:generateContent" % name
        headers["x-goog-api-key"] = key
        config = {"maxOutputTokens": max_tokens}
        if temperature not in (None, ""):
            config["temperature"] = float(temperature)
        payload = {"systemInstruction": {"parts": [{"text": system}]},
                   "contents": [{"role": "user", "parts": [{"text": user}]}],
                   "generationConfig": config}
    elif provider == "claude":
        url = base or "https://api.anthropic.com/v1/messages"
        headers["x-api-key"] = key
        headers["anthropic-version"] = settings.get("anthropic_version") or "2023-06-01"
        # Anthropic Messages API는 temperature를 받지 않으므로 보내지 않습니다.
        payload = {"model": model, "max_tokens": max_tokens, "system": system,
                   "messages": [{"role": "user", "content": user}]}
    else:
        raise LLMError("지원하지 않는 provider입니다: %s" % provider)

    data = _http_json(url, headers, payload, timeout, retries=int(settings.get("retry") or 2))
    return _extract(provider, data)


def _extract(provider, data):
    truncated = False
    parts = []
    if provider == "gemini":
        candidates = data.get("candidates") or []
        if not candidates and (data.get("promptFeedback") or {}).get("blockReason"):
            raise LLMError("Gemini가 요청을 차단했습니다: %s" % data["promptFeedback"]["blockReason"])
        for candidate in candidates:
            truncated |= candidate.get("finishReason") == "MAX_TOKENS"
            for part in (candidate.get("content") or {}).get("parts", []):
                if not part.get("thought") and part.get("text"):
                    parts.append(part["text"])
    elif provider == "claude":
        truncated = data.get("stop_reason") == "max_tokens"
        parts = [item["text"] for item in data.get("content", [])
                 if item.get("type", "text") == "text" and item.get("text")]
    else:
        choices = data.get("choices") or []
        if choices:
            truncated = choices[0].get("finish_reason") == "length"
            content = (choices[0].get("message") or {}).get("content") or choices[0].get("text") or ""
            if isinstance(content, list):
                content = "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
            parts = [content] if content else []
    text = "\n".join(parts).strip()
    if not text:
        if truncated:
            raise LLMError("응답이 출력 토큰 한도에서 잘려 비어 있습니다. 최대 토큰을 늘려 주세요.")
        raise LLMError("응답에서 분석 내용을 찾을 수 없습니다.")
    if truncated:
        text += "\n\n[경고] 출력 토큰 한도에 도달해 분석이 중간에 잘렸을 수 있습니다."
    return text


def list_models(settings):
    """provider의 모델 목록 API로 모델 이름을 가져옵니다. 구독 CLI는 별칭을 돌려줍니다."""
    provider = settings.get("provider")
    if provider == "claude-code":
        return ["sonnet", "opus", "haiku"]
    if provider == "codex":
        return []
    key = _api_key(settings)
    base = settings.get("base_url") or ""
    if not key and not (provider == "openai" and base):
        raise LLMError("API 키가 없습니다. 먼저 API 키를 저장해 주세요.")
    headers = {}
    if provider == "openai":
        url = (base or "https://api.openai.com/v1/chat/completions")
        url = re.sub(r"/chat/completions/?$", "", url) + "/models"
        if key:
            headers["Authorization"] = "Bearer " + key
    elif provider == "claude":
        url = re.sub(r"/messages/?$", "", base or "https://api.anthropic.com/v1/messages") + "/models?limit=100"
        headers["x-api-key"] = key
        headers["anthropic-version"] = settings.get("anthropic_version") or "2023-06-01"
    elif provider == "gemini":
        url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"
        headers["x-goog-api-key"] = key
    else:
        raise LLMError("모델 목록을 조회할 수 없는 provider입니다: %s" % provider)

    data = _http_json(url, headers, None, 15, retries=0)
    if provider == "gemini":
        return [m.get("name", "").replace("models/", "", 1) for m in data.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])]
    names = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    if provider == "openai" and not base:
        skip = re.compile(r"audio|tts|image|embedding|transcribe|realtime|search|moderation|dall-e|whisper")
        names = sorted(n for n in names if re.match(r"(gpt|o[0-9]|chatgpt)", n) and not skip.search(n))
    return names


# ---------------------------------------------------------------- 구독 CLI provider

def resolve_cli(settings):
    """CLI 실행 파일을 찾습니다. Windows의 npm 실행기(.cmd)는 안의 실제 .exe로 바꿉니다
    (.cmd를 거치면 cmd.exe가 인자를 다시 해석하기 때문)."""
    provider = settings.get("provider")
    name = "codex" if provider == "codex" else "claude"
    path = settings.get("cli_path") or ""
    if path and os.path.splitext(os.path.basename(path))[0].lower() != name:
        path = ""  # 다른 CLI(claude/codex)를 가리키면 무시
    found = shutil.which(path or name)
    if not found:
        raise LLMError("%s 명령을 찾을 수 없습니다. 설정에서 CLI 경로를 지정해 주세요." % name)
    if found.lower().endswith(".cmd"):
        with open(found, encoding="utf-8", errors="replace") as f:
            match = re.search(r'"%dp0%\\([^"]+\.exe)"', f.read())
        if match:
            exe = os.path.join(os.path.dirname(found), match.group(1))
            if os.path.exists(exe):
                found = exe
    return found


def _cli_env(cli, settings):
    env = dict(os.environ)
    # 상위 Claude Code 세션의 표시 변수가 남아 있으면 CLI가 다르게 동작할 수 있어 지웁니다.
    for key in list(env):
        if key == "CLAUDECODE" or key.startswith("CLAUDE_CODE_"):
            del env[key]
    env["PATH"] = os.path.dirname(cli) + os.pathsep + env.get("PATH", "")
    token = read_secret(settings.get("cli_token_file")) if settings.get("cli_token_file") else ""
    if token and settings.get("provider") == "claude-code":
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env


def call_cli(settings, system, user, timeout=None):
    provider = settings["provider"]
    cli = resolve_cli(settings)
    model = settings.get("model") or ""
    extra = (settings.get("cli_args") or "").split()
    timeout = timeout or int(settings.get("timeout") or 120)
    env = _cli_env(cli, settings)
    workdir = tempfile.mkdtemp(prefix="kdump-cli-")
    try:
        if provider == "claude-code":
            prompt_path = os.path.join(workdir, "system.txt")
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(system)
            cmd = [cli, "-p", "--output-format", "text", "--tools", "", "--strict-mcp-config",
                   "--no-session-persistence", "--system-prompt-file", prompt_path]
            if model:
                cmd += ["--model", model]
            cmd += extra
            result = subprocess.run(cmd, input=user.encode("utf-8"), stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, cwd=workdir, env=env, timeout=timeout)
            output = result.stdout.decode("utf-8", errors="replace").strip()
            log = result.stderr.decode("utf-8", errors="replace")
        else:
            out_path = os.path.join(workdir, "out.txt")
            cmd = [cli, "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--color", "never",
                   "--ephemeral", "--output-last-message", out_path]
            if model:
                cmd += ["--model", model]
            cmd += extra + ["-"]
            combined = system + "\n\n----- crash report -----\n" + user
            result = subprocess.run(cmd, input=combined.encode("utf-8"), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, cwd=workdir, env=env, timeout=timeout)
            log = result.stdout.decode("utf-8", errors="replace")
            output = ""
            if os.path.exists(out_path):
                with open(out_path, encoding="utf-8", errors="replace") as f:
                    output = f.read().strip()
    except subprocess.TimeoutExpired:
        raise LLMError("%s 응답이 %d초 안에 오지 않았습니다." % (os.path.basename(cli), timeout))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if result.returncode != 0:
        detail = (output + "\n" + log).strip()[-800:]
        raise LLMError("%s 실행 실패(exit %d). 로그인 상태와 사용 한도를 확인해 주세요.\n%s"
                       % (os.path.basename(cli), result.returncode, detail))
    if not output:
        raise LLMError("%s 응답이 비어 있습니다.\n%s" % (os.path.basename(cli), log.strip()[-800:]))
    return output


def cli_status(settings):
    """구독 CLI의 경로·버전·로그인 상태를 돌려줍니다."""
    cli = resolve_cli(settings)
    env = _cli_env(cli, settings)
    info = {"path": cli}

    def run(args):
        try:
            r = subprocess.run([cli] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               env=env, timeout=20, stdin=subprocess.DEVNULL)
            return r.returncode, r.stdout.decode("utf-8", errors="replace").strip()
        except (subprocess.TimeoutExpired, OSError) as error:
            return 1, str(error)

    info["version"] = run(["--version"])[1].splitlines()[0:1]
    info["version"] = info["version"][0] if info["version"] else ""
    if settings.get("provider") == "codex":
        code, text = run(["login", "status"])
    else:
        code, text = run(["auth", "status", "--text"])
    info["logged_in"] = code == 0
    info["status"] = text
    return info


# ---------------------------------------------------------------- 분석 실행

def analyze(report_text, settings):
    system, user = build_input(report_text, settings)
    if settings.get("provider") in CLI_PROVIDERS:
        return call_cli(settings, system, user)
    return call_api(settings, system, user)


def analysis_header(report_path, settings):
    model = resolve_model(settings) or "(CLI 기본값)"
    return ("kdump llm root cause analysis\n"
            "source_report: %s\n"
            "provider:  %s\n"
            "model:     %s\n"
            "masking:   %s\n"
            "generated: %s\n\n"
            % (report_path, settings.get("provider"), model,
               "on" if settings.get("mask", True) else "off",
               time.strftime("%Y-%m-%dT%H:%M:%S%z")))


if __name__ == "__main__":
    # 간단한 명령줄 사용: python kdump_llm.py <report> (설정은 환경변수 LLM_PROVIDER 등)
    if len(sys.argv) != 2:
        sys.exit("사용법: python kdump_llm.py <report-file>")
    with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
        text = f.read()
    conf = {"provider": os.environ.get("LLM_PROVIDER", "openai"), "model": os.environ.get("LLM_MODEL", ""),
            "base_url": os.environ.get("LLM_BASE_URL", ""), "api_key_file": os.environ.get("LLM_API_KEY_FILE", ""),
            "cli_path": os.environ.get("LLM_CLI_PATH", "")}
    print(analyze(text, conf))
