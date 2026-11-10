# analyze-kdump 사용법

[README](../README.md) · [설치](install.md) · [사용법](usage.md) · [설정·LLM](configuration.md) · [웹 UI](webui.md) · [Windows](windows.md) · [터미널 메뉴](terminal-ui.md) · [개발·검증](development.md)

명령으로 리포트와 LLM 분석을 만드는 방법, 리포트 구성, vmlinux 준비입니다.

## 기본 사용

```bash
analyze-kdump /path/to/vmcore
```

`install.sh`를 쓰지 않았다면 `/opt/kdump-analyzer/bin/analyze-kdump`처럼 전체 경로로 실행합니다.

요약 리포트만 생성하려면 `-report` 또는 `-r` 옵션을 사용합니다.

```bash
/opt/kdump-analyzer/bin/analyze-kdump -report /path/to/vmcore
/opt/kdump-analyzer/bin/analyze-kdump -r /path/to/vmcore
```

생성된 리포트를 LLM으로 분석해 원인분석 섹션까지 추가하려면 `-llm` 옵션을 함께 사용합니다. `-llm`은 자동으로 리포트 모드를 켭니다.

```bash
LLM_API_KEY="<api-key>" /opt/kdump-analyzer/bin/analyze-kdump -llm /path/to/vmcore
```

이미 만든 리포트를 LLM으로만 분석하려면 `--llm-report`를 사용합니다. crash와 vmcore가 필요 없으므로, 다른 서버에서 가져온 리포트를 분석하거나 같은 리포트를 다른 모델로 다시 분석할 때 씁니다. 분석 파일은 리포트와 같은 디렉터리에 저장되고, 이미 분석 파일이 있으면 `-2`, `-3`처럼 번호를 붙여 덮어쓰지 않습니다.

```bash
/opt/kdump-analyzer/bin/analyze-kdump --llm-report /opt/kdump-analyzer/logs/kdump-report-20260701-100000-12345.txt
```

기본 설정 파일은 `/opt/kdump-analyzer/analyze-kdump.conf`입니다. 저장소에는 샘플 파일인 `analyze-kdump.conf.sample`만 포함하고, 실제 설정 파일인 `analyze-kdump.conf`는 Git에 올리지 않습니다. 다른 설정 파일을 사용하려면 `-config` 옵션으로 지정합니다.

```bash
/opt/kdump-analyzer/bin/analyze-kdump -config /path/to/analyze-kdump.conf -report /path/to/vmcore
```

vmcore 파일 대신 디렉터리를 지정할 수도 있습니다. 디렉터리 안에 덤프(`vmcore`, `vmcore.flat`, `dump.<시각>` 순)가 있으면 그 파일을, 없으면 하위 디렉터리 중 가장 최근 덤프를 사용합니다. `vmcore.flat`처럼 makedumpfile flattened 형식인 덤프를 crash가 읽지 못하면 자동으로 변환합니다([중앙 분석 서버 구성](terminal-ui.md#중앙-분석-서버-구성-kdump-원격-전송)).

```bash
/opt/kdump-analyzer/bin/analyze-kdump -report /var/crash
```

conf 파일에서 `DEFAULT_VMCORE`를 지정하면 명령줄에서 vmcore 경로를 생략할 수 있습니다. `DEFAULT_VMCORE="/var/crash"`처럼 디렉터리로 지정하면 항상 최근 덤프를 분석합니다.

```bash
/opt/kdump-analyzer/bin/analyze-kdump -report
```

스크립트는 다음 순서로 동작합니다.

1. `crash --osrelease <vmcore>`로 `vmcore`의 커널 버전을 확인합니다.
2. 다음 순서로 `vmlinux`를 찾습니다.
   - `${VMLINUX_BASE}/<kernel-version>/vmlinux`
   - `/usr/lib/debug/lib/modules/<kernel-version>/vmlinux` (RHEL 계열 debuginfo 설치 경로)
   - `/usr/lib/debug/boot/vmlinux-<kernel-version>` (Debian/Ubuntu dbgsym 설치 경로)
3. 파일이 있으면 기본 모드에서는 `crash <vmlinux> <vmcore>`를 실행합니다.
4. `-report` 모드에서는 `crash` 셸에 진입하지 않고 `/opt/kdump-analyzer/logs/kdump-report-<timestamp>-<pid>.txt` 파일을 생성합니다.
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
vmlinux: /opt/kdump-analyzer/vmlinux/4.18.0-553.el8_10.x86_64/vmlinux
```

리포트 모드에서는 다음과 같이 생성된 파일 경로를 출력합니다.

```text
report:  /opt/kdump-analyzer/logs/kdump-report-20260701-100000-12345.txt
analysis: /opt/kdump-analyzer/logs/kdump-analysis-20260701-100000-12345.txt
```

리포트와 분석 파일은 같은 실행 ID(`<timestamp>-<pid>`)를 쓰므로 짝을 쉽게 찾을 수 있고, 같은 초에 여러 번 실행해도 덮어쓰지 않습니다.

리포트에는 기본 메타데이터와 함께 `sys`, `bt`, `bt -a`, `foreach UN bt`, `ps`, `log`, `kmem -i`, `mod -t`, `runq`, `dev -d`, `mount`, `files` 명령 결과가 `===== crash> <명령> =====` 섹션으로 구분되어 들어갑니다.

| 섹션 | 보는 것 |
|------|---------|
| `foreach UN bt` | D 상태(uninterruptible) 태스크의 콜스택. hung task, I/O hang |
| `mod -t` | taint된 모듈(외부, 서명 없음, 강제 로드 등). 서드파티 드라이버가 원인인지 |
| `runq` | CPU별 실행 대기열. soft lockup, 스케줄링 기아 |
| `dev -d` | 디스크별 진행 중인 I/O. 스토리지 hang |
| taint 모듈 관련 태스크 | `foreach bt` 결과 중 taint 모듈의 함수가 콜스택에 있는 태스크만 골라 붙인 섹션. 잠금을 쥐고 잠든 태스크처럼 실행 중도 D 상태도 아닌 원인을 찾는 데 씁니다(`REPORT_TAINTED_TASKS=0`으로 끔) |

마지막 `===== crash 실행 로그 =====` 섹션에는 crash 시작 메시지, 경고, 명령 오류가 남습니다.

각 명령의 출력은 crash의 `명령 > 파일` 리다이렉션으로 따로 받습니다. 따라서 `REPORT_COMMANDS`에 직접 `>` 리다이렉션을 쓴 명령은 리포트 섹션이 비어 있게 됩니다. `set scroll off`처럼 `set`으로 시작하는 명령은 섹션을 만들지 않습니다.

#### 장애 유형 판정과 추가 명령

리포트를 만들기 전에 덤프와 함께 저장된 커널 로그(`vmcore-dmesg.txt` 또는 Ubuntu의 `dmesg.<시각>`, 없으면 `makedumpfile --dump-dmesg`로 꺼냄)를 읽어 장애 유형을 고르고, 리포트 머리글의 `type:`·`evidence:` 줄에 남깁니다. 유형에 맞는 crash 명령을 기본 명령 뒤에 덧붙입니다(`REPORT_TYPE_COMMANDS=0`으로 끔).

| 유형 | 판단 근거 | 덧붙이는 명령 |
|---|---|---|
| hung task | `hung_task: blocked tasks` 패닉, `blocked for more than` | `ps -m \| grep UN` |
| soft/hard lockup, RCU stall | `soft lockup`, `hard LOCKUP`, `detected stall` | `runq -t`, `irq -s`, `ps -m \| grep RU` |
| OOM | `Out of memory` 패닉(panic_on_oom) | `kmem -V`, `kmem -z`, RSS 상위 태스크(`ps -G`) |
| oops | `Fatal exception`과 `kernel BUG at`, NULL 역참조, GPF 등 | `bt -l`(소스 줄), 문제 지점 디스어셈블(`dis -rl <RIP>`) |
| 수동 덤프 | `sysrq: Trigger a crash` | (없음) |
| MCE, NMI | `Machine check`, `NMI` | `mach` |

로그에 hung task나 lockup 경고가 함께 있으면 주 유형과 상관없이 해당 명령도 넣습니다. 이미 명령 목록에 있는 명령은 다시 넣지 않습니다.

#### 모듈 심볼, 아키텍처 확인, JSON 요약

- **모듈 심볼**(`REPORT_MODULE_SYMBOLS`): 기본값 `auto`는 커널 로그 콜스택에 나온 모듈만 디버그 심볼을 불러옵니다(`mod -s`). 모듈 안의 함수·소스 줄이 보이고, 전체를 불러오는 `all`(`mod -S`)보다 훨씬 빠릅니다. 불러온 모듈은 리포트 끝 `모듈 심볼` 섹션에 남습니다. 외부 모듈처럼 디버그 정보가 없는 모듈은 건너뜁니다.
- **아키텍처 확인**(`REPORT_ARCH_CHECK`): vmcore, vmlinux, 이 서버의 아키텍처를 먼저 비교해, 어긋나면 crash를 실행하지 않고 이유를 알려 줍니다.
- **JSON 요약**(`REPORT_JSON`): 리포트와 같은 이름의 `.json` 파일에 장애 유형과 근거, 패닉 메시지, `sys` 값, D 상태 태스크 수, taint 모듈, 섹션 목록을 남깁니다. python3가 필요합니다. 웹 UI는 리포트와 함께 이 파일을 가져와 분석 기록과 리포트 보기 화면에 보여 줍니다(유형 배지, 근거, D 상태 태스크 수, taint 모듈, 요약 상자). JSON이 없는 예전 리포트는 머리글의 `type:`·`evidence:` 줄로 유형만 보여 줍니다.

LLM 분석이 활성화된 경우 원본 crash 리포트와 별도로 `kdump-analysis-<timestamp>-<pid>.txt` 파일이 생성됩니다. API 호출이나 응답 파싱에 실패해도 원본 crash 리포트는 유지되며, 실패 이유는 분석 파일에 기록되고 종료 코드 `3`을 반환합니다. LLM 출력이 토큰 한도에서 잘린 경우 분석 파일 끝에 경고가 붙습니다.

### LLM 입력 축소와 민감정보 마스킹

리포트가 `LLM_MAX_REPORT_CHARS`보다 길면 섹션 단위로 줄입니다. 짧은 섹션(`sys`, `kmem -i` 등)은 그대로 두고, 긴 섹션끼리 남은 분량을 가중치에 따라 나눕니다. `bt`, `log`가 가장 많이 배정받고, `log`는 패닉 메시지가 있는 뒷부분을 남깁니다.

`LLM_MASK_SENSITIVE`가 켜져 있으면(기본값) LLM으로 보내는 내용에서만 호스트명(`sys`의 `NODENAME`), IPv4 주소, MAC 주소, 이메일을 `<HOSTNAME>`, `<IPV4>`, `<MAC>`, `<EMAIL>`로 바꿉니다. 로컬 리포트 파일은 원본 그대로 유지됩니다. IPv6 주소, 사용자명, 파일 경로는 마스킹하지 않으니, 외부 전송이 곤란한 환경이라면 `LLM_BASE_URL`로 사내 OpenAI 호환 서버(vLLM, Ollama 등)를 사용합니다.

```bash
LLM_PROVIDER="openai"
LLM_BASE_URL="http://llm.internal:8000/v1/chat/completions"
LLM_MODEL="<served-model-name>"
```

## vmlinux 추가 방법

분석하려는 `vmcore`의 커널 버전에 해당하는 `vmlinux`가 없다면 디버그 심볼을 설치합니다. 설치된 debuginfo 경로는 자동으로 탐색하므로, 분석 서버에 debuginfo를 설치했다면 복사하지 않아도 됩니다.

RHEL 계열 (`kernel-rt`, Oracle `kernel-uek`이면 패키지 이름을 바꿉니다):

```bash
KVER="<kernel-version>"
dnf debuginfo-install -y "kernel-$KVER"
```

- **RHEL:** 구독의 debug 저장소를 먼저 켭니다: `subscription-manager repos --enable rhel-<major>-for-$(uname -m)-baseos-debug-rpms` (RHEL 7은 `rhel-7-server-debug-rpms`).
- **Oracle Linux:** debuginfo는 `https://oss.oracle.com/ol<major>/debuginfo/` 저장소에 있습니다. UEK 커널(`*.el8uek.*`)은 `kernel-uek-$KVER`를 설치합니다.
- **RHEL·CentOS 7 (`yum`):** `yum install -y yum-utils && debuginfo-install -y "kernel-$KVER"`.

vmlinux가 없으면 `analyze-kdump`가 커널 이름과 배포판에 맞는 명령을 안내하고, 웹 UI의 서버 준비는 위 저장소 설정까지 해서 설치합니다.

Debian/Ubuntu (dbgsym 저장소 설정 필요):

```bash
KVER="<kernel-version>"
apt-get install -y "linux-image-$KVER-dbgsym"
```

여러 커널 버전의 `vmlinux`를 한 곳에 보관하려면 `/opt/kdump-analyzer/vmlinux` 아래에 복사합니다.

```bash
mkdir -p "/opt/kdump-analyzer/vmlinux/$KVER"
cp "/usr/lib/debug/lib/modules/$KVER/vmlinux" "/opt/kdump-analyzer/vmlinux/$KVER/"
```

예를 들어 커널 버전이 `4.18.0-553.el8_10.x86_64`라면 최종 파일 경로는 다음과 같아야 합니다.

```text
/opt/kdump-analyzer/vmlinux/4.18.0-553.el8_10.x86_64/vmlinux
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
