# kdump-tools

`kdump-tools`는 Linux `vmcore` 분석을 조금 더 빠르게 시작하기 위한 보조 도구 모음입니다.

현재는 `vmcore`에서 커널 버전을 확인한 뒤, 해당 버전에 맞는 `vmlinux` 디버그 심볼을 찾아 `crash`를 실행하는 `analyze-kdump` 스크립트를 제공합니다.

## 주요 기능

- `vmcore` 파일의 커널 버전 자동 확인
- 커널 버전에 맞는 `vmlinux` 경로 자동 매칭 (`VMLINUX_BASE`, 설치된 debuginfo 경로 순으로 탐색)
- 매칭되는 `vmlinux`가 없을 때 필요한 설치 명령 안내 (RHEL 계열, Debian/Ubuntu)
- `crash <vmlinux> <vmcore>` 실행 자동화
- `/var/crash` 같은 덤프 디렉터리를 지정하면 가장 최근 `vmcore` 자동 선택
- `-report` 옵션으로 셸 진입 없이 명령별 섹션으로 구분된 요약 리포트 파일 생성
- 선택적으로 LLM을 연동해 원인분석과 조치 권고 추가 (민감정보 마스킹, 섹션 단위 입력 축소)
- 자동화에서 결과를 판별할 수 있는 종료 코드
- 터미널 메뉴 UI(`analyze-kdump-ui`): vmcore 선택, 분석, 결과 보기, 접속 서버 관리, 설정을 메뉴로 처리하고 원격 서버도 SSH로 분석

## 디렉터리 구조

권장 설치 위치는 `/opt/kdump-tools`입니다.

```text
/opt/kdump-tools/
├── README.md
├── VERSION                    # 버전 번호
├── .install-info              # 설치한 버전·커밋·시각 (install.sh가 기록)
├── install.sh                 # 설치·업데이트·명령 등록 (/usr/sbin)
├── analyze-kdump.conf.sample
├── servers.conf.sample
├── bin/
│   ├── analyze-kdump
│   └── analyze-kdump-ui
├── completion/
│   └── kdump-tools.bash       # bash 자동완성
├── logs/
│   └── remote/<서버 이름>/   # 메뉴 UI로 분석한 원격 서버의 리포트와 분석
└── vmlinux/
    └── <kernel-version>/
        └── vmlinux
```

현재 저장소에는 스크립트와 기본 디렉터리만 포함되어 있습니다. 실제 `vmlinux` 파일은 크기가 크고 시스템마다 필요 버전이 다르므로, 분석 대상 커널 버전에 맞춰 별도로 준비합니다.

## 요구 사항

- `bash`
- `crash`
- 분석 대상 `vmcore`
- `vmcore`의 커널 버전과 일치하는 `vmlinux`
- LLM 분석을 쓸 경우 `curl`, `python3`
- 분석 서버 메모리: `crash`가 커널 디버그 정보를 읽을 때 RHEL 9 커널 기준 약 1.5GB를 사용합니다. 메모리가 2GB 이하인 서버나 VM에서는 swap을 추가합니다. 메모리가 부족하면 `crash`가 OOM으로 강제 종료되고 종료 코드 `2`가 반환됩니다.

RHEL 계열 시스템에서는 보통 `crash`와 `debuginfo-install`을 사용할 수 있어야 합니다.

```bash
dnf install -y crash dnf-plugins-core
```

## 설치

저장소를 받은 뒤 `install.sh`를 root로 실행합니다. 파일을 `/opt/kdump-tools`에 복사하고 모든 명령(`analyze-kdump`, `analyze-kdump-ui`)을 `/usr/sbin`에 등록하므로, 이후에는 어디서나 명령 이름만으로 실행할 수 있습니다.

```bash
git clone https://github.com/621dev/kdump-tools.git
sudo ./kdump-tools/install.sh
```

```bash
sudo analyze-kdump-ui
sudo analyze-kdump -r /var/crash
```

- **설정과 데이터:** 이미 있는 `analyze-kdump.conf`, `servers.conf`, `logs/`, `vmlinux/`는 덮어쓰지 않습니다. 새 버전을 받은 뒤 다시 실행하면 업데이트됩니다.
- **등록 위치:** `/usr/sbin`에 심볼릭 링크로 등록합니다. RHEL 계열은 sudo의 `secure_path`에 `/usr/local/*`가 없어서, `/usr/local/bin`에 두면 `sudo analyze-kdump-ui`가 명령을 찾지 못합니다. 같은 이름의 일반 파일이 이미 있으면 덮어쓰지 않고 건너뜁니다.
- **자동완성:** `/etc/bash_completion.d`가 있으면 `analyze-kdump` 옵션과 경로의 Tab 자동완성도 등록합니다. 새 셸부터 적용됩니다.
- **도구 점검:** 설치가 끝나면 crash, whiptail, python3, curl, ssh가 있는지 보여줍니다.
- **설치 옵션:** 설치 위치와 등록 위치는 `--prefix`, `--bin-dir`로 바꿀 수 있습니다.
- **설치 정보:** 설치한 버전, 커밋, 시각, 원본, 등록 위치를 `/opt/kdump-tools/.install-info`에 기록하고, `install.sh` 자신도 `/opt/kdump-tools`에 복사합니다. 저장소 폴더를 지워도 업데이트와 해제를 할 수 있습니다.

등록을 해제하려면 다음을 실행합니다. 등록한 명령과 자동완성만 지우고, `/opt/kdump-tools`(설정, 서버 목록, 로그, vmlinux)는 남깁니다.

```bash
sudo /opt/kdump-tools/install.sh --uninstall
```

## 버전 확인과 업데이트

```bash
analyze-kdump --version
# analyze-kdump 1.4.0 (commit b13f701), 설치 2026-11-03 16:00
```

업데이트는 메뉴(`sudo analyze-kdump-ui` → **버전 확인 / 업데이트**)에서 하는 것이 가장 간단합니다.

- **현재·최신 버전 표시:** 현재 설치본의 버전과 커밋, GitHub의 최신 버전과 커밋을 보여주고, 업데이트가 있으면 **변경 내역**(그 사이 커밋 목록)을 볼 수 있습니다.
- **업데이트 알림:** 마지막으로 확인한 결과는 메인 메뉴에 `▲ 업데이트 가능`으로 표시됩니다. 메인 메뉴를 열 때는 네트워크에 접속하지 않습니다.
- **GitHub에서 업데이트:** 최신 코드를 받아(`git`, 없으면 `curl`+`tar`) 같은 위치에 다시 설치합니다. 끝나면 새 버전으로 메뉴를 다시 시작할 수 있습니다.
- **서버의 디렉터리에서 업데이트 (폐쇄망):** 인터넷이 막힌 서버라면 다른 곳에서 받은 저장소를 서버에 복사한 뒤 그 경로를 지정합니다.
- **유지되는 것:** 설정, 접속 서버 목록, 로그, vmlinux는 그대로 유지됩니다. 업데이트는 root로 실행해야 하고, `install.sh`로 설치한 경우에만 메뉴에서 할 수 있습니다.
- **저장소 변경:** 업데이트할 저장소와 브랜치는 설정 메뉴의 `KDUMP_TOOLS_REPO`(기본 `621dev/kdump-tools`)와 `KDUMP_TOOLS_BRANCH`(기본 `main`)로 바꿀 수 있습니다.

명령으로 업데이트하려면 저장소에서 최신 코드를 받은 뒤 `install.sh`를 다시 실행합니다.

```bash
cd kdump-tools && git pull && sudo ./install.sh
```

원격 서버는 분석 방식에 따라 다릅니다. **원격 설치본 실행** 방식으로 쓰는 서버는 그 서버에서도 업데이트해야 합니다. 연결 테스트 화면에서 원격 서버의 버전을 확인할 수 있습니다. **무설치 실행**은 매번 메뉴를 실행한 서버의 최신 버전을 보내서 쓰고, **vmcore 가져오기**는 원격에 설치할 것이 없습니다.

## 사용법

```bash
analyze-kdump /path/to/vmcore
```

`install.sh`를 쓰지 않았다면 `/opt/kdump-tools/bin/analyze-kdump`처럼 전체 경로로 실행합니다.

요약 리포트만 생성하려면 `-report` 또는 `-r` 옵션을 사용합니다.

```bash
/opt/kdump-tools/bin/analyze-kdump -report /path/to/vmcore
/opt/kdump-tools/bin/analyze-kdump -r /path/to/vmcore
```

생성된 리포트를 LLM으로 분석해 원인분석 섹션까지 추가하려면 `-llm` 옵션을 함께 사용합니다. `-llm`은 자동으로 리포트 모드를 켭니다.

```bash
LLM_API_KEY="<api-key>" /opt/kdump-tools/bin/analyze-kdump -llm /path/to/vmcore
```

이미 만든 리포트를 LLM으로만 분석하려면 `--llm-report`를 사용합니다. crash와 vmcore가 필요 없으므로, 다른 서버에서 가져온 리포트를 분석하거나 같은 리포트를 다른 모델로 다시 분석할 때 씁니다. 분석 파일은 리포트와 같은 디렉터리에 저장되고, 이미 분석 파일이 있으면 `-2`, `-3`처럼 번호를 붙여 덮어쓰지 않습니다.

```bash
/opt/kdump-tools/bin/analyze-kdump --llm-report /opt/kdump-tools/logs/kdump-report-20260701-100000-12345.txt
```

기본 설정 파일은 `/opt/kdump-tools/analyze-kdump.conf`입니다. 저장소에는 샘플 파일인 `analyze-kdump.conf.sample`만 포함하고, 실제 설정 파일인 `analyze-kdump.conf`는 Git에 올리지 않습니다. 다른 설정 파일을 사용하려면 `-config` 옵션으로 지정합니다.

```bash
/opt/kdump-tools/bin/analyze-kdump -config /path/to/analyze-kdump.conf -report /path/to/vmcore
```

vmcore 파일 대신 디렉터리를 지정할 수도 있습니다. 디렉터리 안에 `vmcore`가 있으면 그 파일을, 없으면 하위 디렉터리의 `*/vmcore` 중 가장 최근 파일을 사용합니다.

```bash
/opt/kdump-tools/bin/analyze-kdump -report /var/crash
```

conf 파일에서 `DEFAULT_VMCORE`를 지정하면 명령줄에서 vmcore 경로를 생략할 수 있습니다. `DEFAULT_VMCORE="/var/crash"`처럼 디렉터리로 지정하면 항상 최근 덤프를 분석합니다.

```bash
/opt/kdump-tools/bin/analyze-kdump -report
```

스크립트는 다음 순서로 동작합니다.

1. `crash --osrelease <vmcore>`로 `vmcore`의 커널 버전을 확인합니다.
2. 다음 순서로 `vmlinux`를 찾습니다.
   - `${VMLINUX_BASE}/<kernel-version>/vmlinux`
   - `/usr/lib/debug/lib/modules/<kernel-version>/vmlinux` (RHEL 계열 debuginfo 설치 경로)
   - `/usr/lib/debug/boot/vmlinux-<kernel-version>` (Debian/Ubuntu dbgsym 설치 경로)
3. 파일이 있으면 기본 모드에서는 `crash <vmlinux> <vmcore>`를 실행합니다.
4. `-report` 모드에서는 `crash` 셸에 진입하지 않고 `/opt/kdump-tools/logs/kdump-report-<timestamp>-<pid>.txt` 파일을 생성합니다.
5. LLM 분석이 활성화되어 있으면 생성된 리포트 내용을 API로 보내 원인분석, 근거, 영향 범위, 권고 조치를 별도 분석 파일로 저장합니다.
6. 파일이 없으면 필요한 `vmlinux` 준비 명령을 안내하고 종료합니다.

### 진행 표시

터미널에서 실행하면 crash 리포트 생성은 진행 바와 현재 명령으로, LLM 분석은 경과 시간으로 진행 상황을 stderr에 보여줍니다. 출력을 파일이나 파이프로 받으면 진행 표시는 나오지 않습니다. 파이프로 받으면서도 진행 표시를 보려면 `ANALYZE_KDUMP_PROGRESS=1`을 지정합니다. 메뉴 UI는 이 변수를 켜고 실행합니다.

### 종료 코드

| 코드 | 의미 |
|------|------|
| `0` | 정상 |
| `1` | 사용법, 환경, 입력 오류 (vmcore/vmlinux 없음, conf 권한 문제 등) |
| `2` | `crash` 실행 실패. 리포트 끝의 `crash 실행 로그` 섹션에 오류가 남고, LLM 분석은 건너뜀 |
| `3` | 리포트는 생성했지만 LLM 분석 실패. 사유는 분석 파일에 기록됨 |

예상 출력 예시는 다음과 같습니다.

```text
vmcore:  /var/crash/127.0.0.1-2026-07-01-10:00:00/vmcore
kernel:  4.18.0-553.el8_10.x86_64
vmlinux: /opt/kdump-tools/vmlinux/4.18.0-553.el8_10.x86_64/vmlinux
```

리포트 모드에서는 다음과 같이 생성된 파일 경로를 출력합니다.

```text
report:  /opt/kdump-tools/logs/kdump-report-20260701-100000-12345.txt
analysis: /opt/kdump-tools/logs/kdump-analysis-20260701-100000-12345.txt
```

리포트와 분석 파일은 같은 실행 ID(`<timestamp>-<pid>`)를 쓰므로 짝을 쉽게 찾을 수 있고, 같은 초에 여러 번 실행해도 덮어쓰지 않습니다.

리포트에는 기본 메타데이터와 함께 `sys`, `bt`, `bt -a`, `ps`, `log`, `kmem -i`, `mount`, `files` 명령 결과가 `===== crash> <명령> =====` 섹션으로 구분되어 들어갑니다. 마지막 `===== crash 실행 로그 =====` 섹션에는 crash 시작 메시지, 경고, 명령 오류가 남습니다.

각 명령의 출력은 crash의 `명령 > 파일` 리다이렉션으로 따로 받습니다. 따라서 `REPORT_COMMANDS`에 직접 `>` 리다이렉션을 쓴 명령은 리포트 섹션이 비어 있게 됩니다. `set scroll off`처럼 `set`으로 시작하는 명령은 섹션을 만들지 않습니다.

LLM 분석이 활성화된 경우 원본 crash 리포트와 별도로 `kdump-analysis-<timestamp>-<pid>.txt` 파일이 생성됩니다. API 호출이나 응답 파싱에 실패해도 원본 crash 리포트는 유지되며, 실패 이유는 분석 파일에 기록되고 종료 코드 `3`을 반환합니다. LLM 출력이 토큰 한도에서 잘린 경우 분석 파일 끝에 경고가 붙습니다.

### LLM 입력 축소와 민감정보 마스킹

리포트가 `LLM_MAX_REPORT_CHARS`보다 길면 섹션 단위로 줄입니다. 짧은 섹션(`sys`, `kmem -i` 등)은 그대로 두고, 긴 섹션끼리 남은 분량을 가중치에 따라 나눕니다. `bt`, `log`가 가장 많이 배정받고, `log`는 패닉 메시지가 있는 뒷부분을 남깁니다.

`LLM_MASK_SENSITIVE`가 켜져 있으면(기본값) LLM으로 보내는 내용에서만 호스트명(`sys`의 `NODENAME`), IPv4 주소, MAC 주소, 이메일을 `<HOSTNAME>`, `<IPV4>`, `<MAC>`, `<EMAIL>`로 바꿉니다. 로컬 리포트 파일은 원본 그대로 유지됩니다. IPv6 주소, 사용자명, 파일 경로는 마스킹하지 않으니, 외부 전송이 곤란한 환경이라면 `LLM_BASE_URL`로 사내 OpenAI 호환 서버(vLLM, Ollama 등)를 사용합니다.

```bash
LLM_PROVIDER="openai"
LLM_BASE_URL="http://llm.internal:8000/v1/chat/completions"
LLM_MODEL="<served-model-name>"
```

## 설정 파일

`analyze-kdump.conf.sample`은 bash 변수 형식으로 작성된 샘플입니다. 실제 운영 설정은 `/opt/kdump-tools/analyze-kdump.conf` 또는 `-config`로 지정한 파일에 작성합니다.

conf 파일은 셸 스크립트로 읽혀 실행되므로, 소유자가 root 또는 실행 사용자이고 group/other 쓰기 권한이 없어야 합니다. 조건을 만족하지 않으면 스크립트가 실행을 거부합니다.

```bash
chown root:root /opt/kdump-tools/analyze-kdump.conf
chmod 644 /opt/kdump-tools/analyze-kdump.conf
```

```bash
VMLINUX_BASE="/opt/kdump-tools/vmlinux"
REPORT_DIR="/opt/kdump-tools/logs"
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
- `LLM_MODEL`: 사용할 모델명. 비우면 `openai`는 `gpt-4o-mini`, `claude`는 `claude-sonnet-5-5`, `claude-code`와 `codex`는 CLI 기본 모델을 사용합니다. `gemini`는 반드시 지정합니다
- `LLM_CLI_PATH`: `claude-code`/`codex` provider에서 실행할 CLI 경로. 기본값은 `claude` 또는 `codex`
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
mkdir -p /opt/kdump-tools/secrets
printf '%s\n' '<gemini-api-key>' > /opt/kdump-tools/secrets/gemini-api-key
chmod 600 /opt/kdump-tools/secrets/gemini-api-key
```

이 경우 실제 `analyze-kdump.conf`에는 다음처럼 지정합니다.

```bash
LLM_PROVIDER="gemini"
LLM_MODEL="gemini-3.5-flash"
LLM_API_KEY_FILE="/opt/kdump-tools/secrets/gemini-api-key"
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
| Claude Code | `npm install -g @anthropic-ai/claude-code` | `claude` 실행 후 `/login` | 다른 PC에서 `claude setup-token`으로 장기 토큰을 발급받아 `CLAUDE_CODE_OAUTH_TOKEN` 환경변수로 지정 |
| Codex CLI | `npm install -g @openai/codex` | `codex login` | `codex login --device-auth` (기기 코드 방식) |

로그인 정보는 CLI가 저장하고 자동으로 갱신하므로, 한 번 로그인하면 보통 다시 로그인할 필요가 없습니다. 오래 쓰지 않았거나, 다른 곳에서 로그아웃했거나, 비밀번호를 바꿔 세션이 만료되면 CLI 오류(`OAuth session expired` 등)가 분석 파일에 남습니다. 그때 다시 로그인합니다.

화면 없는 서버에서 Claude Code를 쓸 때는 `claude setup-token`으로 발급한 장기 토큰을 root만 읽을 수 있는 파일에 두고, conf 파일에서 export합니다. conf는 셸 스크립트로 실행되므로 export한 변수가 CLI에 전달됩니다.

```bash
# 토큰 파일 준비 (토큰은 다른 PC에서 claude setup-token으로 발급)
install -m 600 /dev/null /opt/kdump-tools/secrets/claude-oauth-token
vi /opt/kdump-tools/secrets/claude-oauth-token

# analyze-kdump.conf
LLM_PROVIDER="claude-code"
export CLAUDE_CODE_OAUTH_TOKEN="$(cat /opt/kdump-tools/secrets/claude-oauth-token)"
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

## vmlinux 추가 방법

분석하려는 `vmcore`의 커널 버전에 해당하는 `vmlinux`가 없다면 디버그 심볼을 설치합니다. 설치된 debuginfo 경로는 자동으로 탐색하므로, 분석 서버에 debuginfo를 설치했다면 복사하지 않아도 됩니다.

RHEL 계열 (`kernel-rt`, Oracle `kernel-uek`이면 패키지 이름을 바꿉니다):

```bash
KVER="<kernel-version>"
dnf debuginfo-install -y "kernel-$KVER"
```

Debian/Ubuntu (dbgsym 저장소 설정 필요):

```bash
KVER="<kernel-version>"
apt-get install -y "linux-image-$KVER-dbgsym"
```

여러 커널 버전의 `vmlinux`를 한 곳에 보관하려면 `/opt/kdump-tools/vmlinux` 아래에 복사합니다.

```bash
mkdir -p "/opt/kdump-tools/vmlinux/$KVER"
cp "/usr/lib/debug/lib/modules/$KVER/vmlinux" "/opt/kdump-tools/vmlinux/$KVER/"
```

예를 들어 커널 버전이 `4.18.0-553.el8_10.x86_64`라면 최종 파일 경로는 다음과 같아야 합니다.

```text
/opt/kdump-tools/vmlinux/4.18.0-553.el8_10.x86_64/vmlinux
```

### 커널 모듈 심볼

패닉이 커널 모듈(서드파티 드라이버 등) 안에서 발생했다면 모듈 debuginfo를 불러와야 `bt`에 심볼이 제대로 나옵니다. `REPORT_COMMANDS` 맨 앞에 `mod -S`를 추가합니다. 모듈 debuginfo가 기본 경로에 없으면 `mod -S <디렉터리>`로 지정합니다.

```bash
REPORT_COMMANDS="
mod -S
sys
bt
bt -a
log
"
```

hung task 패닉을 분석할 때는 D 상태 프로세스의 스택이 핵심이므로 `foreach UN bt`를 추가하는 것을 권장합니다.

## 터미널 메뉴 UI

`analyze-kdump-ui`는 장애 현장에서 SSH나 서버 콘솔로 접속한 상태로 쓰는 메뉴 화면입니다. 명령 옵션을 외우지 않아도 vmcore 선택부터 결과 확인까지 메뉴로 진행합니다.

```bash
sudo analyze-kdump-ui
```

요구 사항: `whiptail`(RHEL 계열 `newt` 패키지, 최소 설치에도 포함), `less`, 원격 서버를 쓸 경우 `ssh`. 화면 크기는 터미널 크기에 맞춰 조정됩니다.

조작 방법:

| 화면 | 키 |
|------|------|
| 메뉴 | ↑↓로 이동, Enter로 선택. 목록 끝의 `← 이전 메뉴로`나 `<뒤로>` 버튼(Tab으로 이동), 또는 Esc로 한 단계 위로 돌아갑니다. 메인 메뉴의 버튼은 `<종료>`입니다 |
| 서버·provider 선택(동그라미 목록) | 스페이스로 고르고 Enter로 확인 |
| 리포트·분석 보기 | ↑↓ PgUp PgDn으로 이동, `/`로 검색, **`q`로 이전 화면으로 돌아갑니다**(하단에 항상 안내 표시) |
| 리포트 생성이 끝난 뒤 | Enter를 누르면 결과 화면으로 넘어갑니다 |

진행 표시: crash 리포트 생성은 진행 바와 현재 명령(`[####....] 3/8 bt -a (12초)`)으로, 처음 vmlinux를 읽는 동안은 `crash 시작 중`과 경과 시간으로 보여줍니다. LLM 분석은 회전 표시와 경과 시간, vmcore 가져오기는 진행 바와 받은 크기로 보여줍니다. 원격 서버 확인 중에는 안내 화면이 뜹니다.

| 메뉴 | 내용 |
|------|------|
| vmcore 분석 | 선택한 서버의 crash 디렉터리에서 vmcore를 최근 순으로 보여주고, 리포트 생성 / 리포트 + LLM 분석 / crash 셸 진입 중 하나를 실행합니다. 끝나면 결과(종료 코드 의미 포함)와 리포트·분석 보기를 제공합니다 |
| 분석 결과 보기 | 선택한 서버의 리포트와 분석 파일을 최근 순으로 보여줍니다. 리포트를 골라 LLM으로 (다시) 분석할 수 있습니다 |
| 접속 서버 선택 | 분석할 서버를 고릅니다. "이 서버"는 메뉴를 실행한 서버입니다 |
| 접속 서버 관리 | 원격 서버를 추가·수정·삭제하고, 기본 분석 방식을 정하고, 연결 테스트(SSH, analyze-kdump, crash, vmcore 개수, 자동 선택될 분석 방식)를 합니다 |
| 설정 | `analyze-kdump.conf`의 주요 항목(경로, LLM provider·모델·키 파일·CLI·마스킹·한도)을 바꿉니다. API 키 자체는 저장하지 않고 키 파일 경로만 지정합니다 |
| kdump 원격 전송 안내 | 운영 서버의 vmcore를 이 서버로 자동 전송하는 `/etc/kdump.conf` 설정을 이 서버 주소로 채워 보여줍니다(중앙 분석 서버 구성) |
| 버전 확인 / 업데이트 | 현재·최신 버전과 변경 내역을 보여주고, GitHub나 서버의 디렉터리에서 업데이트합니다([버전 확인과 업데이트](#버전-확인과-업데이트)) |

### 상황별 사용 방식

| 상황 | 방법 | 운영 서버에 필요한 것 |
|------|------|------|
| 장애 서버에 직접 접속해 분석 | 그 서버에서 `analyze-kdump-ui` → "이 서버" | analyze-kdump, crash, vmlinux |
| 운영 서버에 아무것도 설치하지 않음 | **중앙 분석 서버**: 운영 서버 kdump가 vmcore를 분석 서버로 전송하고, 분석 서버에서 "이 서버"로 분석 | kdump 설정만 |
| 분석 서버에서 다른 서버의 vmcore를 분석 | 원격 서버로 등록하고 아래 세 가지 분석 방식 중 하나를 사용 | 방식에 따라 다름 |

원격 서버의 분석 방식은 서버마다 기본값을 정해 두고, 분석할 때마다 바꿀 수 있습니다.

| 분석 방식 | 원격 서버에 필요한 것 | 동작 |
|------|------|------|
| 원격 설치본 실행 (`installed`) | analyze-kdump, crash, vmlinux | 원격에 설치된 `analyze-kdump -r`로 리포트를 만들어 가져옵니다. 원격 서버의 설정을 따릅니다 |
| 무설치 실행 (`upload`) | crash, vmlinux | 이 서버의 analyze-kdump를 원격 `/tmp/kdump-tools.XXXXXX`로 보내 실행하고, 리포트를 가져온 뒤 임시 디렉터리를 지웁니다. 원격 설정 파일은 읽지 않습니다 |
| vmcore 가져오기 (`fetch`) | SSH 접속만 | vmcore(와 `vmcore-dmesg.txt`)를 이 서버의 crash 디렉터리 `<서버 이름>-<원래 디렉터리>/`로 복사해 이 서버에서 분석합니다. 디스크 공간을 먼저 확인하고, 같은 크기로 이미 가져온 vmcore는 다시 받지 않습니다. 이 서버에 해당 커널의 vmlinux가 필요합니다 |
| 자동 선택 (`auto`, 기본값) | — | 원격 설치본 → 무설치 실행(crash 있음) → vmcore 가져오기 순으로 고릅니다 |

- 무설치 실행이 원격의 vmlinux 부족으로 실패하면 vmcore를 가져와 이 서버에서 분석할지 묻습니다.
- 어느 방식이든 LLM 분석은 메뉴를 실행한 서버의 설정으로 합니다. 그래서 API 키나 구독 로그인을 원격 서버마다 둘 필요가 없고, 외부 통신이 막힌 서버의 리포트도 분석할 수 있습니다.
- 원격 서버에서 가져온 리포트와 분석은 `logs/remote/<서버 이름>/`에 모입니다.
- SSH는 키 인증으로 비밀번호 없이 접속할 수 있어야 합니다(`BatchMode`로 접속).
- root가 아닌 계정으로 접속하면 서버 설정에서 sudo를 켜고, 원격 서버에 비밀번호 없는 sudo(NOPASSWD)를 허용합니다. crash 셸 진입은 터미널을 연결하므로 sudo 비밀번호를 입력할 수 있습니다.

접속 서버 목록은 `/opt/kdump-tools/servers.conf`에 저장됩니다(`ANALYZE_KDUMP_SERVERS`로 변경 가능). 메뉴에서 관리하면 되고, 직접 편집할 때는 `servers.conf.sample` 형식을 따릅니다. 7번째 칸(분석 방식)을 생략하면 `auto`로 동작합니다.

```text
# 이름|접속대상(user@host)|포트|sudo 사용(yes/no)|원격 analyze-kdump 경로|crash 디렉터리|분석 방식
db01|ops@10.0.0.11|22|yes|/opt/kdump-tools/bin/analyze-kdump|/var/crash|auto
```

### 중앙 분석 서버 구성 (kdump 원격 전송)

운영 서버에는 아무것도 설치하지 않고, 패닉이 나면 kdump가 vmcore를 분석 서버로 바로 보내게 할 수 있습니다. 메뉴의 "kdump 원격 전송 안내"가 아래 설정을 분석 서버 주소로 채워 보여줍니다.

```bash
# [분석 서버] 전송 받을 계정과 디렉터리
useradd -m kdump
mkdir -p /var/crash && chown kdump /var/crash
```

```bash
# [운영 서버] /etc/kdump.conf
ssh kdump@<분석 서버 주소>
sshkey /root/.ssh/kdump_id_rsa
path /var/crash
core_collector makedumpfile -F -l --message-level 7 -d 31
```

```bash
# [운영 서버] SSH 키를 분석 서버에 등록하고 kdump 재시작
kdumpctl propagate
systemctl restart kdump
kdumpctl status
```

- vmcore는 분석 서버의 `/var/crash/<운영 서버 IP>-<시각>/`에 저장되고, 분석 서버에서 "이 서버"로 분석합니다.
- SSH 전송은 makedumpfile의 flattened 형식(`vmcore.flat`)으로 저장될 수 있습니다. 이 경우 `makedumpfile -R <디렉터리>/vmcore < <디렉터리>/vmcore.flat`로 변환한 뒤 분석합니다.
- NFS로 보내려면 `nfs <NFS 서버>:/export/crash`와 `path /`를 쓰고, 공유를 분석 서버의 `/var/crash`에 마운트합니다.
- 분석 서버의 `VMLINUX_BASE`(`/opt/kdump-tools/vmlinux/<커널 버전>/vmlinux`)에 운영 서버 커널 버전별 vmlinux를 모아 둡니다.

## 테스트 VM에서 검증하기

`tests/vm/kdump-vm-test.sh`는 테스트용 RHEL 계열 VM에서 실제 vmcore를 만들어 `analyze-kdump`를 검증합니다. **운영 서버에서는 실행하지 않습니다.** `panic` 단계는 커널을 즉시 패닉시킵니다.

```bash
sudo ./tests/vm/kdump-vm-test.sh setup    # kdump 설정. crashkernel이 새로 잡히면 재부팅 후 다시 실행
sudo ./tests/vm/kdump-vm-test.sh panic    # sysrq 패닉 -> 재부팅 후 /var/crash에 vmcore 생성
sudo ./tests/vm/kdump-vm-test.sh verify   # debuginfo 설치, analyze-kdump -r 실행, 섹션별 출력 점검
```

`verify --llm`을 쓰면 `LLM_API_KEY` 등 LLM 설정으로 분석 파일 생성까지 확인합니다.

## 로그 디렉터리

`logs/`는 분석 결과나 작업 기록을 남기기 위한 디렉터리입니다. `-report` 옵션으로 생성되는 요약 리포트가 이 디렉터리에 저장됩니다.
