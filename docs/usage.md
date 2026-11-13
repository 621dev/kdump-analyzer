# analyze-kdump 사용법

[README](../README.md) · [설치](install.md) · [요구 사항·네트워크](requirements.md) · [사용법](usage.md) · [설정·LLM](configuration.md) · [웹 UI](webui.md) · [Windows](windows.md) · [터미널 메뉴](terminal-ui.md) · [개발·검증](development.md)

명령으로 리포트와 LLM 분석을 만드는 방법, 리포트 구성, vmlinux 준비를 설명합니다.

## 기본 사용

```bash
analyze-kdump /path/to/vmcore
```

`install.sh`로 설치하지 않았다면 `/opt/kdump-analyzer/bin/analyze-kdump`처럼 전체 경로로 실행합니다.

리포트만 만들려면 `-report`(또는 `-r`)를 붙입니다.

```bash
/opt/kdump-analyzer/bin/analyze-kdump -report /path/to/vmcore
/opt/kdump-analyzer/bin/analyze-kdump -r /path/to/vmcore
```

리포트를 LLM으로 분석해 원인 분석까지 받으려면 `-llm`을 붙입니다. `-llm`을 쓰면 리포트 모드도 함께 켜집니다.

```bash
LLM_API_KEY="<api-key>" /opt/kdump-analyzer/bin/analyze-kdump -llm /path/to/vmcore
```

이미 만든 리포트를 LLM으로만 분석하려면 `--llm-report`를 씁니다.
- crash와 vmcore가 없어도 됩니다. 다른 서버에서 가져온 리포트를 분석하거나, 같은 리포트를 다른 모델로 다시 분석할 때 씁니다.
- 분석 파일은 리포트와 같은 디렉터리에 저장합니다. 분석 파일이 이미 있으면 `-2`, `-3`처럼 번호를 붙여 덮어쓰지 않습니다.

```bash
/opt/kdump-analyzer/bin/analyze-kdump --llm-report /opt/kdump-analyzer/logs/kdump-report-20260701-100000-12345.txt
```

기본 설정 파일은 `/opt/kdump-analyzer/analyze-kdump.conf`입니다. 저장소에는 샘플(`analyze-kdump.conf.sample`)만 있고, 실제 설정 파일은 Git에 올리지 않습니다. 다른 설정 파일은 `-config`로 지정합니다.

```bash
/opt/kdump-analyzer/bin/analyze-kdump -config /path/to/analyze-kdump.conf -report /path/to/vmcore
```

vmcore 대신 디렉터리를 줄 수도 있습니다.
- 디렉터리 안에 덤프가 있으면 `vmcore`, `vmcore.flat`, `dump.<시각>` 순서로 찾아 씁니다.
- 없으면 하위 디렉터리에서 가장 최근 덤프를 씁니다.
- `vmcore.flat` 같은 makedumpfile flattened 덤프는 crash가 읽지 못하면 자동으로 변환합니다([중앙 분석 서버 구성](terminal-ui.md#중앙-분석-서버-구성-kdump-원격-전송)).

```bash
/opt/kdump-analyzer/bin/analyze-kdump -report /var/crash
```

설정 파일에 `DEFAULT_VMCORE`를 지정하면 명령에서 vmcore 경로를 빼도 됩니다. `DEFAULT_VMCORE="/var/crash"`처럼 디렉터리를 지정하면 늘 최근 덤프를 분석합니다.

```bash
/opt/kdump-analyzer/bin/analyze-kdump -report
```

동작 순서는 다음과 같습니다.

1. `crash --osrelease <vmcore>`로 vmcore의 커널 버전을 확인합니다.
2. 다음 순서로 `vmlinux`를 찾습니다.
   - `${VMLINUX_BASE}/<kernel-version>/vmlinux`
   - `/usr/lib/debug/lib/modules/<kernel-version>/vmlinux` (RHEL 계열 debuginfo 설치 경로)
   - `/usr/lib/debug/boot/vmlinux-<kernel-version>` (Debian·Ubuntu dbgsym 설치 경로)
3. vmlinux가 없으면 준비 명령을 안내하고 끝냅니다.
4. 기본 모드에서는 `crash <vmlinux> <vmcore>`를 실행합니다.
5. `-report` 모드에서는 crash 셸에 들어가지 않고 `/opt/kdump-analyzer/logs/kdump-report-<timestamp>-<pid>.txt`를 만듭니다.
6. LLM 분석을 켰으면 리포트를 API로 보내, 원인, 근거, 영향 범위, 권고 조치를 별도 분석 파일로 저장합니다.

### 진행 표시

터미널에서 실행하면 진행 상황을 stderr에 보여 줍니다. crash 리포트 생성은 진행 바와 현재 명령으로, LLM 분석은 경과 시간으로 표시합니다.
- 출력을 파일이나 파이프로 받으면 진행 표시를 하지 않습니다.
- 파이프로 받으면서 진행 표시를 보려면 `ANALYZE_KDUMP_PROGRESS=1`을 지정합니다. 메뉴는 이 변수를 켜고 실행합니다.

### 종료 코드

| 코드 | 의미 |
|------|------|
| `0` | 정상 |
| `1` | 사용법, 환경, 입력 오류 (vmcore·vmlinux 없음, 설정 파일 권한 문제 등) |
| `2` | `crash` 실행 실패<br>• 리포트 끝 `crash 실행 로그` 섹션에 오류가 남습니다<br>• LLM 분석은 건너뜁니다 |
| `3` | 리포트는 만들었지만 LLM 분석 실패. 이유는 분석 파일에 남습니다 |

실행하면 다음처럼 출력합니다.

```text
vmcore:  /var/crash/127.0.0.1-2026-07-01-10:00:00/vmcore
kernel:  4.18.0-553.el8_10.x86_64
vmlinux: /opt/kdump-analyzer/vmlinux/4.18.0-553.el8_10.x86_64/vmlinux
```

리포트 모드에서는 만든 파일의 경로를 출력합니다.

```text
report:  /opt/kdump-analyzer/logs/kdump-report-20260701-100000-12345.txt
analysis: /opt/kdump-analyzer/logs/kdump-analysis-20260701-100000-12345.txt
```

리포트와 분석 파일은 같은 실행 ID(`<timestamp>-<pid>`)를 써서 짝을 찾기 쉽고, 같은 초에 여러 번 실행해도 덮어쓰지 않습니다.

## 리포트 구성

리포트에는 기본 정보와 다음 crash 명령의 결과가 `===== crash> <명령> =====` 섹션으로 나뉘어 들어갑니다.
- `sys`, `bt`, `bt -a`, `foreach UN bt`, `ps`, `log`
- `kmem -i`, `mod -t`, `runq`, `dev -d`, `mount`, `files`

| 섹션 | 보는 것 |
|------|---------|
| `foreach UN bt` | D 상태(uninterruptible) 태스크의 콜스택<br>• hung task<br>• I/O hang |
| `mod -t` | taint된 모듈(외부 모듈, 서명 없음, 강제 로드 등). 서드파티 드라이버가 원인인지 봅니다 |
| `runq` | CPU별 실행 대기열<br>• soft lockup<br>• 스케줄링 기아 |
| `dev -d` | 디스크별 진행 중인 I/O. 스토리지 hang을 봅니다 |
| taint 모듈 관련 태스크 | • `foreach bt` 결과에서 taint 모듈의 함수가 콜스택에 있는 태스크만 모은 섹션<br>• 잠금을 쥔 채 잠든 태스크처럼, 실행 중도 D 상태도 아닌 원인을 찾을 때 씁니다<br>• `REPORT_TAINTED_TASKS=0`으로 끕니다 |

- 마지막 `===== crash 실행 로그 =====` 섹션에는 crash 시작 메시지, 경고, 명령 오류가 남습니다.
- 명령마다 crash의 `명령 > 파일` 리다이렉션으로 출력을 받습니다. 그래서 `REPORT_COMMANDS`에 직접 `>`를 쓴 명령은 섹션이 비어 있습니다.
- `set scroll off`처럼 `set`으로 시작하는 명령은 섹션을 만들지 않습니다.

### 장애 유형 판정과 추가 명령

리포트를 만들기 전에 덤프와 함께 저장된 커널 로그로 장애 유형을 고릅니다.
- 커널 로그는 `vmcore-dmesg.txt`나 Ubuntu의 `dmesg.<시각>`을 읽고, 없으면 `makedumpfile --dump-dmesg`로 꺼냅니다.
- 판정 결과는 리포트 머리글의 `type:`·`evidence:` 줄에 남깁니다.
- 유형에 맞는 crash 명령을 기본 명령 뒤에 덧붙입니다(`REPORT_TYPE_COMMANDS=0`으로 끔).

| 유형 | 판단 근거 | 덧붙이는 명령 |
|---|---|---|
| hung task | • `hung_task: blocked tasks` 패닉<br>• `blocked for more than` | `ps -m \| grep UN` |
| soft/hard lockup, RCU stall | • `soft lockup`<br>• `hard LOCKUP`<br>• `detected stall` | • `runq -t`<br>• `irq -s`<br>• `ps -m \| grep RU` |
| OOM | `Out of memory` 패닉(panic_on_oom) | • `kmem -V`<br>• `kmem -z`<br>• RSS 상위 태스크(`ps -G`) |
| oops | • `Fatal exception`<br>• `kernel BUG at`<br>• NULL 역참조, GPF 등 | • `bt -l`(소스 줄)<br>• 문제 지점 디스어셈블(`dis -rl <RIP>`) |
| 수동 덤프 | `sysrq: Trigger a crash` | (없음) |
| MCE, NMI | `Machine check`, `NMI` | `mach` |

로그에 hung task나 lockup 경고가 함께 있으면 주 유형과 상관없이 그 명령도 넣습니다. 명령 목록에 이미 있는 명령은 다시 넣지 않습니다.

### 모듈 심볼, 아키텍처 확인, JSON 요약

- **모듈 심볼**(`REPORT_MODULE_SYMBOLS`): 기본값 `auto`는 커널 로그 콜스택에 나온 모듈의 디버그 심볼만 불러옵니다(`mod -s`).
  - 모듈 안의 함수와 소스 줄이 보이고, 전체를 불러오는 `all`(`mod -S`)보다 훨씬 빠릅니다.
  - 불러온 모듈은 리포트 끝 `모듈 심볼` 섹션에 남습니다.
  - 외부 모듈처럼 디버그 정보가 없는 모듈은 건너뜁니다.
- **아키텍처 확인**(`REPORT_ARCH_CHECK`): vmcore, vmlinux, 이 서버의 아키텍처를 먼저 비교합니다. 다르면 crash를 실행하지 않고 이유를 알려 줍니다.
- **JSON 요약**(`REPORT_JSON`): 리포트와 같은 이름의 `.json` 파일을 만듭니다. python3가 필요합니다.
  - 담는 것: 장애 유형과 근거, 패닉 메시지, `sys` 값, D 상태 태스크 수, taint 모듈, 섹션 목록
  - 웹 UI는 리포트와 함께 이 파일을 가져와 분석 기록과 리포트 화면에 보여 줍니다(유형 배지, 근거, 요약 상자 등).
  - JSON이 없는 예전 리포트는 머리글의 `type:`·`evidence:` 줄로 유형만 보여 줍니다.

LLM 분석을 켜면 리포트와 별도로 `kdump-analysis-<timestamp>-<pid>.txt`를 만듭니다.
- API 호출이나 응답 처리에 실패해도 리포트는 그대로 남습니다. 실패 이유는 분석 파일에 남기고 종료 코드 `3`으로 끝납니다.
- LLM 출력이 토큰 한도에서 잘리면 분석 파일 끝에 경고를 붙입니다.

### LLM 입력 축소와 민감정보 마스킹

리포트가 `LLM_MAX_REPORT_CHARS`보다 길면 섹션 단위로 줄입니다.
- 짧은 섹션(`sys`, `kmem -i` 등)은 그대로 둡니다.
- 긴 섹션들이 남은 분량을 가중치대로 나눕니다. `bt`와 `log`가 가장 많이 받습니다.
- `log`는 패닉 메시지가 있는 뒷부분을 남깁니다.

`LLM_MASK_SENSITIVE`를 켜면(기본값) LLM에 보내는 내용에서만 다음을 바꿉니다. 로컬 리포트 파일은 원본 그대로입니다.

| 원래 값 | 바꾼 값 |
|---|---|
| 호스트명(`sys`의 `NODENAME`) | `<HOSTNAME>` |
| IPv4 주소 | `<IPV4>` |
| MAC 주소 | `<MAC>` |
| 이메일 | `<EMAIL>` |

IPv6 주소, 사용자 이름, 파일 경로는 가리지 않습니다. 외부로 보내기 어려운 환경이면 `LLM_BASE_URL`로 사내 OpenAI 호환 서버(vLLM, Ollama 등)를 씁니다.

```bash
LLM_PROVIDER="openai"
LLM_BASE_URL="http://llm.internal:8000/v1/chat/completions"
LLM_MODEL="<served-model-name>"
```

## vmlinux 추가 방법

분석할 vmcore의 커널 버전에 맞는 `vmlinux`가 없으면 디버그 심볼을 설치합니다. 설치된 debuginfo 경로는 자동으로 찾으므로 따로 복사하지 않아도 됩니다.

RHEL 계열 (`kernel-rt`, Oracle `kernel-uek`이면 패키지 이름을 바꿉니다):

```bash
KVER="<kernel-version>"
dnf debuginfo-install -y "kernel-$KVER"
```

- **RHEL:** 구독의 debug 저장소를 먼저 켭니다: `subscription-manager repos --enable rhel-<major>-for-$(uname -m)-baseos-debug-rpms` (RHEL 7은 `rhel-7-server-debug-rpms`)
- **Oracle Linux:** debuginfo는 `https://oss.oracle.com/ol<major>/debuginfo/` 저장소에 있습니다. UEK 커널(`*.el8uek.*`)은 `kernel-uek-$KVER`를 설치합니다.
- **RHEL·CentOS 7 (`yum`):** `yum install -y yum-utils && debuginfo-install -y "kernel-$KVER"`

vmlinux가 없으면 `analyze-kdump`가 커널 이름과 배포판에 맞는 설치 명령을 알려 줍니다. 웹 UI의 서버 준비는 위 저장소 설정까지 해서 설치합니다.

Debian·Ubuntu (dbgsym 저장소 설정 필요):

```bash
KVER="<kernel-version>"
apt-get install -y "linux-image-$KVER-dbgsym"
```

여러 커널 버전의 `vmlinux`를 한곳에 두려면 `/opt/kdump-analyzer/vmlinux` 아래에 복사합니다.

```bash
mkdir -p "/opt/kdump-analyzer/vmlinux/$KVER"
cp "/usr/lib/debug/lib/modules/$KVER/vmlinux" "/opt/kdump-analyzer/vmlinux/$KVER/"
```

커널 버전이 `4.18.0-553.el8_10.x86_64`라면 파일 경로는 다음과 같습니다.

```text
/opt/kdump-analyzer/vmlinux/4.18.0-553.el8_10.x86_64/vmlinux
```

### 커널 모듈 심볼

패닉이 커널 모듈(서드파티 드라이버 등) 안에서 났다면 모듈 debuginfo를 불러와야 `bt`에 심볼이 제대로 나옵니다. `REPORT_COMMANDS` 맨 앞에 `mod -S`를 넣습니다. 모듈 debuginfo가 기본 경로에 없으면 `mod -S <디렉터리>`로 지정합니다.

```bash
REPORT_COMMANDS="
mod -S
sys
bt
bt -a
log
"
```

hung task 패닉은 D 상태 프로세스의 스택이 핵심이라 `foreach UN bt`를 넣는 것이 좋습니다.

## 로그 디렉터리

`-report`로 만든 리포트와 분석 파일은 `logs/`에 저장합니다.
