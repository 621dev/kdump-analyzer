# 설정 파일과 LLM

[README](../README.md) · [설치](install.md) · [사용법](usage.md) · [설정·LLM](configuration.md) · [웹 UI](webui.md) · [Windows](windows.md) · [터미널 메뉴](terminal-ui.md) · [개발·검증](development.md)

`analyze-kdump.conf` 항목과 LLM provider, 구독 계정(Claude Code·Codex) 설정입니다.

## analyze-kdump.conf

`analyze-kdump.conf.sample`은 bash 변수 형식으로 작성된 샘플입니다. 실제 운영 설정은 `/opt/kdump-analyzer/analyze-kdump.conf` 또는 `-config`로 지정한 파일에 작성합니다.

conf 파일은 셸 스크립트로 읽혀 실행되므로, 소유자가 root 또는 실행 사용자이고 group/other 쓰기 권한이 없어야 합니다. 조건을 만족하지 않으면 스크립트가 실행을 거부합니다.

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

설정 가능한 주요 항목은 다음과 같습니다.

- `VMLINUX_BASE`: 커널 버전별 `vmlinux` 파일을 찾을 기준 디렉터리
- `REPORT_DIR`: `-report` 결과 파일을 저장할 디렉터리
- `REPORT_PREFIX`: 생성되는 리포트 파일명 접두어
- `ANALYSIS_PREFIX`: 생성되는 LLM 분석 파일명 접두어
- `DEFAULT_VMCORE`: 명령줄 인자가 없을 때 사용할 기본 `vmcore` 경로. 디렉터리를 지정하면 가장 최근 `vmcore` 사용
- `REPORT_COMMANDS`: 리포트에 포함할 `crash` 명령 목록
- `REPORT_COMMAND_FILE`: 별도 파일로 관리하는 `crash` 명령 목록
- `LLM_ENABLED`: `1`, `true`, `yes`, `on`으로 설정하면 `-report` 실행 시 LLM 분석 추가
- `LLM_API_KEY`: LLM API 키. conf 파일에 저장하기보다 환경변수로 주입하는 방식을 권장
- `LLM_API_KEY_FILE`: API 키를 담은 파일 경로. 첫 줄만 읽고 CR과 앞뒤 공백은 제거합니다. 권한이 `600`보다 넓으면 경고합니다
- `LLM_PROVIDER`: `openai`, `gemini`, `claude`, `claude-code`, `codex` 중 하나. `openai`는 OpenAI 호환 Chat Completions API도 포함하고, `claude-code`와 `codex`는 구독 계정으로 로그인한 CLI를 사용합니다([구독 계정으로 사용하기](#구독-계정으로-사용하기-claude-code--codex-cli))
- `LLM_BASE_URL`: provider 기본 엔드포인트 대신 사용할 API 엔드포인트
- `LLM_MODEL`: 사용할 모델명. 비우면 `openai`는 `gpt-4o-mini`, `claude`는 `claude-sonnet-5-5`, `claude-code`와 `codex`는 CLI 기본 모델을 사용합니다. `gemini`는 반드시 지정합니다. 메뉴의 설정에서 고르면 API 키 방식(`openai`, `claude`, `gemini`, OpenAI 호환 서버)은 provider의 모델 목록 API로 실제 목록을 받아 보여주고, `claude-code`는 `sonnet`/`opus`/`haiku` 별칭에서 고릅니다. 목록을 받지 못하면 직접 입력합니다
- `LLM_CLI_PATH`: `claude-code`/`codex` provider에서 실행할 CLI 경로. 기본값은 `claude` 또는 `codex`. 메뉴의 설정에서 설치 위치를 자동으로 찾아 고를 수 있습니다
- `LLM_CLI_TOKEN_FILE`: `claude-code`에서 쓸 장기 토큰 파일(`claude setup-token`으로 발급, 권한 600). 분석할 때 `CLAUDE_CODE_OAUTH_TOKEN`으로 넘깁니다
- `LLM_CLI_ARGS`: CLI에 덧붙일 추가 인자. 공백으로 나뉘며 따옴표로 묶은 인자는 지원하지 않습니다. 예: `LLM_CLI_ARGS="--profile kdump"`(Codex)
- `LLM_MAX_TOKENS`: LLM이 생성할 최대 토큰 수. 기본값 `8192`. Gemini thinking 모델이나 OpenAI reasoning 모델은 내부 추론 토큰도 이 한도에 포함되므로 너무 작게 잡지 않습니다
- `LLM_OPENAI_TOKEN_PARAM`: OpenAI 요청에 쓸 토큰 한도 필드. `auto`(기본값)는 `LLM_BASE_URL`이 없으면 `max_completion_tokens`, 있으면 `max_tokens`를 사용합니다. `max_tokens`, `max_completion_tokens`, `none`으로 직접 지정할 수 있습니다
- `LLM_TEMPERATURE`: 비워 두면(기본값) 전송하지 않고 모델 기본값을 사용합니다. `openai`와 `gemini`에만 적용됩니다. OpenAI reasoning 모델은 기본값 외의 temperature를 거부하므로 설정하지 않습니다. Anthropic Messages API는 2026-10-21부터 temperature를 받지 않으므로 `claude` provider에는 설정해도 전송하지 않습니다
- `LLM_MAX_REPORT_CHARS`: LLM 입력으로 전달할 리포트 최대 문자 수. 초과 시 섹션 단위로 축소합니다
- `LLM_MASK_SENSITIVE`: LLM 입력의 호스트명, IPv4, MAC, 이메일 마스킹 여부. 기본값 `1`
- `LLM_TIMEOUT`: LLM API 호출 1회당 제한 시간(초)
- `LLM_RETRY`: 타임아웃, 429, 5xx 같은 일시 오류 시 재시도 횟수. 기본값 `2`
- `LLM_PROMPT_FILE`: 기본 원인분석 프롬프트 대신 사용할 프롬프트 파일
- `LLM_ANTHROPIC_VERSION`: Claude API에 전달할 Anthropic API 버전. 기본값은 `2023-06-01`

설정 우선순위는 **명령줄 옵션 > 환경변수 > conf 파일 > 스크립트 기본값**입니다. 셸에 예전에 export한 `LLM_MODEL` 같은 변수가 남아 있으면 conf 값보다 우선 적용되니 주의합니다. 운영 환경에서는 conf 파일로 관리하고, 환경변수는 API 키처럼 일회성으로 주입할 값에만 쓰는 방식을 권장합니다.

API 키는 다음처럼 실행 시 환경변수로 전달할 수 있습니다.

```bash
export LLM_API_KEY="<api-key>"
analyze-kdump -report -llm /path/to/vmcore
```

API 키를 파일로 저장해야 한다면 `secrets/` 디렉터리에 두고 권한을 제한합니다. 저장소 루트의 `secrets/`는 Git에 올라가지 않도록 `.gitignore`에 포함되어 있습니다.

```bash
mkdir -p /opt/kdump-analyzer/secrets
printf '%s\n' '<gemini-api-key>' > /opt/kdump-analyzer/secrets/gemini-api-key
chmod 600 /opt/kdump-analyzer/secrets/gemini-api-key
```

이 경우 실제 `analyze-kdump.conf`에는 다음처럼 지정합니다.

```bash
LLM_PROVIDER="gemini"
LLM_MODEL="gemini-3.5-flash"
LLM_API_KEY_FILE="/opt/kdump-analyzer/secrets/gemini-api-key"
```

Provider별 최소 설정 예시는 다음과 같습니다.

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

API 키 대신 Claude 구독(Pro/Max)이나 ChatGPT 구독으로 로그인한 CLI를 통해 분석할 수 있습니다. 툴이 리포트를 줄이고 마스킹한 뒤 CLI를 비대화 모드로 실행하고, 결과를 분석 파일에 저장합니다. API 키는 필요 없습니다.

```bash
# Claude Code (Claude Pro/Max 구독)
LLM_PROVIDER="claude-code"
LLM_MODEL=""            # 비우면 Claude Code 기본 모델. 예: "sonnet", "opus"

# Codex CLI (ChatGPT 구독)
LLM_PROVIDER="codex"
LLM_MODEL=""            # 비우면 Codex 설정(~/.codex/config.toml)의 기본 모델
```

분석 서버에 CLI를 설치하고, 리포트를 생성할 사용자(보통 root)로 로그인해 둡니다.

| CLI | 설치 | 로그인 | 화면 없는 서버 |
|------|------|------|------|
| Claude Code | `npm install -g @anthropic-ai/claude-code` | `claude auth login` | `claude setup-token`으로 장기 토큰 발급 → `LLM_CLI_TOKEN_FILE` |
| Codex CLI | `npm install -g @openai/codex` | `codex login` | `codex login --device-auth` (기기 코드 방식) |

**메뉴로 설정하기 (권장):** `sudo analyze-kdump-ui` → **설정**에서 진행합니다. `LLM_PROVIDER`를 `claude-code`나 `codex`로 바꾸면 인증을 바로 진행할지 묻습니다.

- **CLI 설치:** CLI를 찾지 못하면 **설치**와 **설치된 위치 찾기**를 고를 수 있습니다. 설치는 root로 실행하고, 끝나면 설치된 전체 경로를 `LLM_CLI_PATH`에 저장한 뒤 로그인 단계로 이어집니다.
  - Claude Code: **공식 설치 스크립트**(`curl -fsSL https://claude.ai/install.sh | CLAUDE_INSTALL_ALLOW_SUDO=1 bash`, 권장, Node.js 불필요, 실행 계정의 `~/.local/bin/claude`) 또는 **npm 전역 설치**(`npm install -g @anthropic-ai/claude-code`, Node.js 22 이상). 공식 스크립트는 sudo 실행을 기본으로 막지만, 분석이 root로 실행되므로 root에 설치하도록 허용 옵션을 지정합니다
  - Codex: npm 전역 설치(`npm install -g @openai/codex`)
  - **Node.js 자동 준비:** npm 설치에 Node.js가 없거나 버전이 낮으면 패키지 관리자로 설치합니다. RHEL 계열 기본 `nodejs`는 16이라 Claude Code에 부족하므로, `dnf module enable nodejs:22`로 Node.js 22를 설치합니다. Debian/Ubuntu는 `apt-get install nodejs npm`을 씁니다.
  - 인터넷이 막힌 서버에서는 설치할 수 없으니, 다른 곳에서 설치한 CLI를 복사한 뒤 **설치된 위치 찾기**로 경로를 지정합니다.
- **구독 CLI 인증:** 현재 로그인 상태를 보여주고, 다음 작업을 메뉴에서 실행합니다.
  - Claude Code: 장기 토큰 발급(`claude setup-token`, 화면 없는 서버 권장), 다른 PC에서 발급한 토큰 붙여넣기, 브라우저 로그인(`claude auth login`), 저장된 토큰 사용 중지
  - Codex: 기기 코드 로그인(`codex login --device-auth`), 브라우저 로그인
  - 공통: 연결 테스트(짧은 요청 1회)
- **토큰 저장:** 장기 토큰은 `/opt/kdump-analyzer/secrets/claude-oauth-token`(폴더 700, 파일 600)에 저장하고, 설정에는 경로만 `LLM_CLI_TOKEN_FILE`로 남깁니다. 분석할 때는 이 토큰을 `CLAUDE_CODE_OAUTH_TOKEN` 환경변수로만 넘기므로 `ps` 같은 명령줄 목록에 보이지 않습니다.
- **CLI 경로 자동 탐색 (`LLM_CLI_PATH`):** PATH, `/usr/local/bin`, `/usr/bin`, `~/.local/bin`, `~/.npm-global/bin`, nvm 경로(`~/.nvm/versions/node/*/bin`)에서 CLI를 찾아 버전과 함께 보여줍니다.
  - RHEL 계열은 sudo 실행 경로에 `/usr/local/bin`이 없어서, `npm install -g`로 설치한 `claude`를 이름만으로는 못 찾습니다. 이때 전체 경로를 고르면 됩니다.
  - nvm으로 설치한 CLI는 같은 폴더의 `node`가 필요하므로, 실행할 때 CLI가 있는 폴더를 PATH 앞에 붙입니다.
- **실행 계정:** 메뉴를 `sudo`로 실행하면 CLI도 root로 실행되므로, 로그인도 root 계정 기준입니다.

로그인 정보는 CLI가 저장하고 자동으로 갱신하므로, 한 번 로그인하면 보통 다시 로그인할 필요가 없습니다. 오래 쓰지 않았거나, 다른 곳에서 로그아웃했거나, 비밀번호를 바꿔 세션이 만료되면 CLI 오류(`OAuth session expired` 등)가 분석 파일에 남습니다. 그때 메뉴의 구독 CLI 인증에서 다시 로그인합니다.

설정 파일로 직접 지정할 때는 다음과 같이 씁니다.

```bash
LLM_PROVIDER="claude-code"
LLM_CLI_PATH="/usr/local/bin/claude"
LLM_CLI_TOKEN_FILE="/opt/kdump-analyzer/secrets/claude-oauth-token"   # root만 읽을 수 있게 600
```

실행 방식:

- **Claude Code:** `claude -p --output-format text --tools "" --strict-mcp-config --no-session-persistence --system-prompt <프롬프트>`로 실행하고, 리포트는 표준입력으로 넘깁니다. `--bare` 모드는 구독(OAuth) 인증을 읽지 않으므로 쓰지 않습니다.
- **Codex:** `codex exec --skip-git-repo-check --sandbox read-only --color never --ephemeral --output-last-message <파일> -`로 실행하고, 지시문과 리포트를 합쳐 표준입력으로 넘깁니다.
- 두 CLI 모두 프로젝트 설정 파일(`CLAUDE.md`, `AGENTS.md`)을 읽지 않도록 빈 임시 디렉터리에서 실행합니다. 또 파일 읽기와 명령 실행 도구를 끄거나(Claude Code) 읽기 전용 샌드박스로 제한합니다(Codex).
- `LLM_TIMEOUT`이 CLI 실행 제한 시간으로 쓰입니다. 시간을 넘기면 종료 코드 `3`과 함께 사유가 분석 파일에 남습니다.
- `LLM_MAX_TOKENS`, `LLM_TEMPERATURE`, `LLM_RETRY`, API 키 관련 설정은 CLI provider에 적용되지 않습니다.

주의할 점:

- **이용 약관:** 구독은 개인 사용을 전제로 합니다. 여러 사람이 공유하는 서버에서 자동으로 반복 호출하는 용도라면 API 키 방식이나 팀/엔터프라이즈 플랜을 사용합니다.
- **사용 한도:** 구독의 시간당 사용 한도에 걸리면 분석이 실패하고, CLI의 오류 메시지가 분석 파일에 기록됩니다.
- **데이터:** 구독 경로로 보내도 리포트는 외부로 전송됩니다. `LLM_MASK_SENSITIVE` 마스킹은 똑같이 적용됩니다.
