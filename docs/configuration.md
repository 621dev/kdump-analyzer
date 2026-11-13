# 설정 파일과 LLM

[README](../README.md) · [설치](install.md) · [요구 사항·네트워크](requirements.md) · [사용법](usage.md) · [설정·LLM](configuration.md) · [웹 UI](webui.md) · [Windows](windows.md) · [터미널 메뉴](terminal-ui.md) · [개발·검증](development.md)

`analyze-kdump.conf`의 항목과 LLM 연결(API 키, 구독 계정 Claude Code·Codex) 방법입니다.

## analyze-kdump.conf

`analyze-kdump.conf.sample`은 bash 변수 형식의 샘플입니다. 실제 설정은 `/opt/kdump-analyzer/analyze-kdump.conf`나 `-config`로 지정한 파일에 씁니다.

설정 파일은 셸 스크립트로 실행되므로 권한을 확인합니다. 소유자가 root나 실행 사용자가 아니거나, group·other에 쓰기 권한이 있으면 실행하지 않습니다.

```bash
chown root:root /opt/kdump-analyzer/analyze-kdump.conf
chmod 644 /opt/kdump-analyzer/analyze-kdump.conf
```

```bash
VMLINUX_BASE="/opt/kdump-analyzer/vmlinux"
REPORT_DIR="/opt/kdump-analyzer/logs"
REPORT_PREFIX="kdump-report"
ANALYSIS_PREFIX="kdump-analysis"

# 선택 사항
DEFAULT_VMCORE="/var/crash"

# 선택 사항: LLM 분석
LLM_ENABLED=0
LLM_PROVIDER="openai"
LLM_MODEL="gpt-4o-mini"
LLM_MAX_TOKENS=8192
LLM_MAX_REPORT_CHARS=60000
LLM_TIMEOUT=120
```

### 경로와 리포트

| 항목 | 설명 |
|---|---|
| `VMLINUX_BASE` | 커널 버전별 `vmlinux`를 찾을 기준 디렉터리 |
| `REPORT_DIR` | `-report` 결과를 저장할 디렉터리 |
| `REPORT_PREFIX` | 리포트 파일 이름 앞부분 |
| `ANALYSIS_PREFIX` | LLM 분석 파일 이름 앞부분 |
| `DEFAULT_VMCORE` | 명령에 vmcore를 주지 않았을 때 쓸 경로. 디렉터리면 가장 최근 덤프를 씁니다 |
| `REPORT_COMMANDS` | 리포트에 넣을 `crash` 명령 목록 |
| `REPORT_COMMAND_FILE` | `crash` 명령 목록을 따로 둔 파일 |

### LLM

| 항목 | 설명 |
|---|---|
| `LLM_ENABLED` | `1`, `true`, `yes`, `on`이면 `-report` 때 LLM 분석도 합니다 |
| `LLM_PROVIDER` | • `openai`: OpenAI와 OpenAI 호환 Chat Completions API<br>• `gemini`, `claude`<br>• `claude-code`, `codex`: 구독 계정으로 로그인한 CLI ([구독 계정으로 사용하기](#구독-계정으로-사용하기-claude-code--codex-cli)) |
| `LLM_MODEL` | 사용할 모델. 비우면 provider마다 다음을 씁니다.<br>• `openai`: `gpt-4o-mini`<br>• `claude`: `claude-sonnet-5-5`<br>• `claude-code`, `codex`: CLI 기본 모델<br>• `gemini`: 반드시 지정 |
| `LLM_API_KEY` | API 키. 설정 파일보다 환경변수로 넘기는 것을 권장합니다 |
| `LLM_API_KEY_FILE` | API 키 파일 경로<br>• 첫 줄만 읽고 CR과 앞뒤 공백을 지웁니다<br>• 권한이 `600`보다 넓으면 경고합니다 |
| `LLM_BASE_URL` | provider 기본 주소 대신 쓸 API 주소 |
| `LLM_MAX_TOKENS` | LLM이 만들 최대 토큰 수(기본 `8192`). Gemini thinking 모델과 OpenAI reasoning 모델은 내부 추론 토큰도 여기에 들어가므로 너무 작게 잡지 않습니다 |
| `LLM_OPENAI_TOKEN_PARAM` | OpenAI 요청의 토큰 한도 필드<br>• `auto`(기본): `LLM_BASE_URL`이 없으면 `max_completion_tokens`, 있으면 `max_tokens`<br>• 직접 지정: `max_tokens`, `max_completion_tokens`, `none` |
| `LLM_TEMPERATURE` | 비우면(기본) 보내지 않고 모델 기본값을 씁니다.<br>• `openai`, `gemini`에만 적용합니다<br>• OpenAI reasoning 모델은 기본값 외의 값을 거부하니 비워 둡니다<br>• Anthropic Messages API는 2026-10-21부터 이 값을 받지 않아, `claude`에는 지정해도 보내지 않습니다 |
| `LLM_MAX_REPORT_CHARS` | LLM에 보낼 리포트의 최대 글자 수. 넘으면 섹션 단위로 줄입니다 |
| `LLM_MASK_SENSITIVE` | 호스트명, IPv4, MAC, 이메일 가리기(기본 `1`) |
| `LLM_TIMEOUT` | LLM 호출 한 번의 제한 시간(초) |
| `LLM_RETRY` | 시간 초과, 429, 5xx 같은 일시 오류 때 다시 시도할 횟수(기본 `2`) |
| `LLM_PROMPT_FILE` | 기본 원인 분석 프롬프트 대신 쓸 파일 |
| `LLM_ANTHROPIC_VERSION` | Claude API에 보낼 Anthropic API 버전(기본 `2023-06-01`) |
| `LLM_CLI_PATH` | `claude-code`·`codex`에서 실행할 CLI 경로(기본 `claude` 또는 `codex`). 메뉴 설정에서 설치 위치를 찾아 고를 수 있습니다 |
| `LLM_CLI_TOKEN_FILE` | `claude-code`에서 쓸 장기 토큰 파일(`claude setup-token`으로 발급, 권한 600). 분석할 때 `CLAUDE_CODE_OAUTH_TOKEN`으로 넘깁니다 |
| `LLM_CLI_ARGS` | CLI에 덧붙일 인자. 공백으로 나누며 따옴표로 묶은 인자는 지원하지 않습니다. 예: `LLM_CLI_ARGS="--profile kdump"`(Codex) |

메뉴의 설정에서 모델을 고르면 다음처럼 보여 줍니다.
- API 키 방식(`openai`, `claude`, `gemini`, OpenAI 호환 서버): provider의 모델 목록 API로 실제 목록을 받아 보여 줍니다.
- `claude-code`: `sonnet`, `opus`, `haiku` 중에서 고릅니다.
- 목록을 받지 못하면 직접 입력합니다.

### 우선순위와 API 키

설정은 **명령줄 옵션 > 환경변수 > 설정 파일 > 스크립트 기본값** 순으로 적용합니다.
- 셸에 예전에 export한 `LLM_MODEL` 같은 변수가 남아 있으면 설정 파일보다 먼저 적용되니 주의합니다.
- 평소 설정은 설정 파일에 두고, 환경변수는 API 키처럼 실행할 때만 넘길 값에 씁니다.

API 키는 실행할 때 환경변수로 넘길 수 있습니다.

```bash
export LLM_API_KEY="<api-key>"
analyze-kdump -report -llm /path/to/vmcore
```

API 키를 파일로 두려면 `secrets/`에 저장하고 권한을 좁힙니다. 저장소의 `secrets/`는 `.gitignore`에 들어 있어 Git에 올라가지 않습니다.

```bash
mkdir -p /opt/kdump-analyzer/secrets
printf '%s\n' '<gemini-api-key>' > /opt/kdump-analyzer/secrets/gemini-api-key
chmod 600 /opt/kdump-analyzer/secrets/gemini-api-key
```

그다음 `analyze-kdump.conf`에 지정합니다.

```bash
LLM_PROVIDER="gemini"
LLM_MODEL="gemini-3.5-flash"
LLM_API_KEY_FILE="/opt/kdump-analyzer/secrets/gemini-api-key"
```

provider별 최소 설정입니다.

```bash
# OpenAI 또는 OpenAI 호환 API
LLM_PROVIDER="openai"
LLM_MODEL="gpt-4o-mini"

# Gemini
LLM_PROVIDER="gemini"
LLM_MODEL="gemini-3.5-flash"

# Claude
LLM_PROVIDER="claude"
LLM_MODEL="claude-sonnet-5-5"
```

### 구독 계정으로 사용하기 (Claude Code / Codex CLI)

API 키 대신 Claude 구독(Pro/Max)이나 ChatGPT 구독으로 로그인한 CLI로 분석합니다. 도구가 리포트를 줄이고 민감정보를 가린 뒤 CLI를 비대화 모드로 실행해, 결과를 분석 파일에 저장합니다.

```bash
# Claude Code (Claude Pro/Max 구독)
LLM_PROVIDER="claude-code"
LLM_MODEL=""            # 비우면 Claude Code 기본 모델. 예: "sonnet", "opus"

# Codex CLI (ChatGPT 구독)
LLM_PROVIDER="codex"
LLM_MODEL=""            # 비우면 Codex 설정(~/.codex/config.toml)의 기본 모델
```

분석 서버에 CLI를 설치하고, 리포트를 만들 계정(보통 root)으로 로그인해 둡니다.

| CLI | 설치 | 로그인 | 화면 없는 서버 |
|------|------|------|------|
| Claude Code | `npm install -g @anthropic-ai/claude-code` | `claude auth login` | `claude setup-token`으로 장기 토큰 발급 → `LLM_CLI_TOKEN_FILE` |
| Codex CLI | `npm install -g @openai/codex` | `codex login` | `codex login --device-auth` (기기 코드 방식) |

#### 메뉴로 설정하기 (권장)

`sudo analyze-kdump-ui` → **설정**에서 합니다. `LLM_PROVIDER`를 `claude-code`나 `codex`로 바꾸면 바로 인증할지 묻습니다.

- **CLI 설치:** CLI를 찾지 못하면 **설치**나 **설치된 위치 찾기**를 고릅니다. 설치는 root로 실행하고, 끝나면 설치된 전체 경로를 `LLM_CLI_PATH`에 저장한 뒤 로그인으로 넘어갑니다.
  - Claude Code는 두 가지 중에서 고릅니다.
    - **공식 설치 스크립트**(권장): `curl -fsSL https://claude.ai/install.sh | CLAUDE_INSTALL_ALLOW_SUDO=1 bash`. Node.js가 필요 없고 실행 계정의 `~/.local/bin/claude`에 설치합니다. 공식 스크립트는 sudo 실행을 기본으로 막지만, 분석을 root로 하므로 허용 옵션을 붙입니다.
    - **npm 전역 설치**: `npm install -g @anthropic-ai/claude-code` (Node.js 22 이상)
  - Codex: npm 전역 설치(`npm install -g @openai/codex`)
  - **Node.js 자동 준비:** npm 설치에 필요한 Node.js가 없거나 낮으면 패키지 관리자로 설치합니다.
    - RHEL 계열 기본 `nodejs`는 16이라 Claude Code에 부족해 `dnf module enable nodejs:22`로 22를 설치합니다.
    - Debian·Ubuntu는 `apt-get install nodejs npm`을 씁니다.
  - 인터넷이 막힌 서버에서는 설치할 수 없습니다. 다른 곳에서 설치한 CLI를 복사한 뒤 **설치된 위치 찾기**로 경로를 지정합니다.
- **구독 CLI 인증:** 현재 로그인 상태를 보여 주고, 다음 작업을 메뉴에서 실행합니다.
  - Claude Code:
    - 장기 토큰 발급(`claude setup-token`, 화면 없는 서버에 권장)
    - 다른 PC에서 발급한 토큰 붙여넣기
    - 브라우저 로그인(`claude auth login`)
    - 저장된 토큰 사용 중지
  - Codex: 기기 코드 로그인(`codex login --device-auth`), 브라우저 로그인
  - 공통: 연결 테스트(짧은 요청 한 번)
- **토큰 저장:** 장기 토큰은 `/opt/kdump-analyzer/secrets/claude-oauth-token`(폴더 700, 파일 600)에 두고, 설정에는 경로만 `LLM_CLI_TOKEN_FILE`로 남깁니다. 분석할 때는 `CLAUDE_CODE_OAUTH_TOKEN` 환경변수로만 넘기므로 `ps` 같은 명령 목록에 보이지 않습니다.
- **CLI 경로 찾기 (`LLM_CLI_PATH`):** 다음 위치에서 CLI를 찾아 버전과 함께 보여 줍니다.
  - PATH, `/usr/local/bin`, `/usr/bin`, `~/.local/bin`, `~/.npm-global/bin`
  - nvm 경로(`~/.nvm/versions/node/*/bin`)
  - RHEL 계열은 sudo 실행 경로에 `/usr/local/bin`이 없어, `npm install -g`로 설치한 `claude`를 이름만으로 찾지 못합니다. 이때 전체 경로를 고릅니다.
  - nvm으로 설치한 CLI는 같은 폴더의 `node`가 필요해, 실행할 때 그 폴더를 PATH 앞에 붙입니다.
- **실행 계정:** 메뉴를 `sudo`로 실행하면 CLI도 root로 실행되므로 root 계정으로 로그인해야 합니다.

로그인 정보는 CLI가 저장하고 자동으로 갱신하므로 보통 한 번만 로그인하면 됩니다. 오래 쓰지 않았거나, 다른 곳에서 로그아웃했거나, 비밀번호를 바꿔 세션이 끝나면 CLI 오류(`OAuth session expired` 등)가 분석 파일에 남습니다. 그때 메뉴의 구독 CLI 인증에서 다시 로그인합니다.

#### 설정 파일로 지정하기

```bash
LLM_PROVIDER="claude-code"
LLM_CLI_PATH="/usr/local/bin/claude"
LLM_CLI_TOKEN_FILE="/opt/kdump-analyzer/secrets/claude-oauth-token"   # root만 읽을 수 있게 600
```

#### 실행 방식

- **Claude Code:** `claude -p --output-format text --tools "" --strict-mcp-config --no-session-persistence --system-prompt <프롬프트>`로 실행하고 리포트는 표준입력으로 넘깁니다. `--bare` 모드는 구독(OAuth) 인증을 읽지 않아 쓰지 않습니다.
- **Codex:** `codex exec --skip-git-repo-check --sandbox read-only --color never --ephemeral --output-last-message <파일> -`로 실행하고, 지시문과 리포트를 합쳐 표준입력으로 넘깁니다.
- **격리:** 두 CLI 모두 빈 임시 디렉터리에서 실행해 프로젝트 설정 파일(`CLAUDE.md`, `AGENTS.md`)을 읽지 않게 합니다. 파일 읽기와 명령 실행 도구도 끄거나(Claude Code) 읽기 전용 샌드박스로 제한합니다(Codex).
- **제한 시간:** `LLM_TIMEOUT`을 CLI 실행 제한 시간으로 씁니다. 넘기면 종료 코드 `3`과 함께 이유를 분석 파일에 남깁니다.
- **적용되지 않는 설정:** `LLM_MAX_TOKENS`, `LLM_TEMPERATURE`, `LLM_RETRY`, API 키 관련 설정

#### 주의할 점

- **이용 약관:** 구독은 개인 사용을 전제로 합니다. 여러 사람이 쓰는 서버에서 자동으로 반복 호출한다면 API 키나 팀·엔터프라이즈 플랜을 씁니다.
- **사용 한도:** 구독의 시간당 한도에 걸리면 분석이 실패하고, CLI 오류 메시지가 분석 파일에 남습니다.
- **데이터:** 구독으로 보내도 리포트는 외부로 나갑니다. `LLM_MASK_SENSITIVE`의 가리기는 똑같이 적용합니다.
