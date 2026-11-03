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

## 디렉터리 구조

권장 설치 위치는 `/opt/kdump-tools`입니다.

```text
/opt/kdump-tools/
├── README.md
├── analyze-kdump.conf.sample
├── bin/
│   └── analyze-kdump
├── logs/
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

RHEL 계열 시스템에서는 보통 `crash`와 `debuginfo-install`을 사용할 수 있어야 합니다.

```bash
dnf install -y crash dnf-plugins-core
```

## 사용법

```bash
/opt/kdump-tools/bin/analyze-kdump /path/to/vmcore
```

경로를 매번 입력하지 않으려면 `/usr/sbin`에 심볼릭 링크를 만들 수 있습니다.

```bash
ln -s /opt/kdump-tools/bin/analyze-kdump /usr/sbin/analyze-kdump
```

이후에는 명령어만으로 실행할 수 있습니다.

```bash
analyze-kdump /path/to/vmcore
```

요약 리포트만 생성하려면 `-report` 또는 `-r` 옵션을 사용합니다.

```bash
/opt/kdump-tools/bin/analyze-kdump -report /path/to/vmcore
/opt/kdump-tools/bin/analyze-kdump -r /path/to/vmcore
```

생성된 리포트를 LLM으로 분석해 원인분석 섹션까지 추가하려면 `-llm` 옵션을 함께 사용합니다. `-llm`은 자동으로 리포트 모드를 켭니다.

```bash
LLM_API_KEY="<api-key>" /opt/kdump-tools/bin/analyze-kdump -llm /path/to/vmcore
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
- `LLM_PROVIDER`: `openai`, `gemini`, `claude` 중 하나. `openai`는 OpenAI 호환 Chat Completions API도 포함
- `LLM_BASE_URL`: provider 기본 엔드포인트 대신 사용할 API 엔드포인트
- `LLM_MODEL`: 사용할 모델명
- `LLM_MAX_TOKENS`: LLM이 생성할 최대 토큰 수. 기본값 `8192`. Gemini thinking 모델이나 OpenAI reasoning 모델은 내부 추론 토큰도 이 한도에 포함되므로 너무 작게 잡지 않습니다
- `LLM_OPENAI_TOKEN_PARAM`: OpenAI 요청에 쓸 토큰 한도 필드. `auto`(기본값)는 `LLM_BASE_URL`이 없으면 `max_completion_tokens`, 있으면 `max_tokens`를 사용합니다. `max_tokens`, `max_completion_tokens`, `none`으로 직접 지정할 수 있습니다
- `LLM_TEMPERATURE`: 비워 두면(기본값) 전송하지 않고 모델 기본값을 사용합니다. OpenAI reasoning 모델은 기본값 외의 temperature를 거부하므로 설정하지 않습니다
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
LLM_MODEL="claude-sonnet-4-5"
```

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

## 로그 디렉터리

`logs/`는 분석 결과나 작업 기록을 남기기 위한 디렉터리입니다. `-report` 옵션으로 생성되는 요약 리포트가 이 디렉터리에 저장됩니다.
