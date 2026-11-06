# kdump-tools

Linux 커널 패닉 덤프(`vmcore`)를 빠르게 분석하기 위한 도구 모음입니다. 덤프의 커널 버전에 맞는 `vmlinux`를 찾아 `crash`를 실행하고, 장애 분석에 필요한 정보를 리포트 한 장으로 모은 뒤, 원하면 LLM으로 원인과 조치까지 정리합니다.

- **`analyze-kdump`**: 서버에서 실행하는 분석 명령. 리포트 생성과 LLM 분석을 합니다.
- **`analyze-kdump-ui`**: 서버 터미널에서 쓰는 메뉴 화면. 장애 현장에서 SSH로 접속해 씁니다.
- **웹 UI** (`webui/kdump-webui.py`): 노트북 브라우저에서 여러 서버를 SSH로 관리하고 분석합니다.

RHEL·Rocky·Alma 계열과 Ubuntu·Debian을 지원합니다. Debian·Ubuntu의 `kdump-tools` 패키지(덤프를 만드는 쪽)와는 별개의 프로젝트이고, 그 패키지가 만든 덤프도 분석합니다.

[변경 기록](CHANGELOG.md) · [릴리스](https://github.com/621dev/kdump-tools/releases) · [라이선스 (MIT)](LICENSE)

## 5분 시작 가이드

덤프가 이미 `/var/crash`에 있다고 가정합니다. kdump가 아직 설정되지 않았다면 웹 UI의 **서버 준비**로 점검·설치하거나 [요구 사항](#요구-사항)을 먼저 봅니다.

### A. 서버에서 바로 분석하기

장애 서버나 분석 서버에 SSH로 접속해서 실행합니다.

```bash
# 1. 설치 (/opt/kdump-tools에 복사하고 명령을 /usr/sbin에 등록)
git clone https://github.com/621dev/kdump-tools.git
sudo ./kdump-tools/install.sh

# 2. 가장 최근 덤프로 리포트 만들기
sudo analyze-kdump -r /var/crash
```

- 덤프 커널의 `vmlinux`(디버그 커널)가 없으면 설치 명령을 알려 주고 멈춥니다. 안내대로 설치(RHEL 계열 `dnf debuginfo-install -y kernel-<커널 버전>`, Ubuntu `apt-get install -y linux-image-<커널 버전>-dbgsym`)한 뒤 다시 실행합니다.
- 끝나면 `report:` 줄에 리포트 경로(`/opt/kdump-tools/logs/kdump-report-*.txt`)가 나옵니다. 리포트 맨 위의 `type:`·`evidence:` 줄에서 장애 유형과 근거를 먼저 봅니다.
- 메뉴로 하려면 `sudo analyze-kdump-ui`를 실행해 **vmcore 분석**을 고릅니다.
- LLM 분석까지 하려면 [LLM 분석](#설정-파일) 설정 뒤 `-llm`을 붙입니다.

### B. 노트북에서 웹 UI로 분석하기

여러 서버를 노트북 한 곳에서 관리할 때 씁니다. 서버에 kdump-tools를 설치하지 않아도 노트북에서 스크립트를 보내 분석합니다(무설치 실행). 서버에는 crash와 디버그 커널만 있으면 되고, 이것도 웹 UI가 설치해 줍니다.

1. 준비: 노트북에 Python 3.8 이상과 `ssh`, 서버에는 SSH 키로 접속하는 계정과 비밀번호 없는 sudo가 필요합니다.
2. 실행:
   ```bash
   git clone https://github.com/621dev/kdump-tools.git
   python kdump-tools/webui/kdump-webui.py
   ```
   브라우저가 열립니다. Windows에서는 `kdump-tools\windows\install-shortcut.cmd`를 한 번 실행하면 바탕화면 아이콘으로 띄울 수 있습니다.
3. 왼쪽 서버 목록의 **+ 추가**에 이름, `user@host`, SSH 키 파일을 넣고 저장한 뒤 **연결 테스트**를 누릅니다.
4. 서버 화면의 **서버 준비** 탭에서 빠진 항목(crash, 디버그 커널, kdump 설정 등)을 확인하고 설치합니다.
5. vmcore 목록에서 **리포트** 또는 **리포트 + LLM 분석**을 누릅니다. 진행 바가 끝나면 결과가 열립니다. LLM은 **설정**에서 API 키나 Claude Code·Codex 구독을 연결합니다.

여러 운영 서버의 덤프를 한 곳에 모으려면 [중앙 분석 서버 구성](#중앙-분석-서버-구성-kdump-원격-전송)을 봅니다.

## 목차

- [주요 기능](#주요-기능)
- [디렉터리 구조](#디렉터리-구조) · [요구 사항](#요구-사항) · [설치](#설치) · [버전 확인과 업데이트](#버전-확인과-업데이트)
- [사용법](#사용법) (리포트, 종료 코드, 장애 유형 판정, LLM 입력 축소와 마스킹)
- [설정 파일](#설정-파일) (LLM provider, 구독 계정 사용)
- [vmlinux 추가 방법](#vmlinux-추가-방법)
- [웹 UI](#웹-ui) · [터미널 메뉴 UI](#터미널-메뉴-ui) (상황별 사용 방식, 중앙 분석 서버 구성)
- [테스트 VM에서 검증하기](#테스트-vm에서-검증하기) · [로그 디렉터리](#로그-디렉터리) · [라이선스](#라이선스)

## 주요 기능

**리포트 (`analyze-kdump`)**
- 덤프의 커널 버전을 읽어 맞는 `vmlinux`를 찾고(`VMLINUX_BASE`, debuginfo·dbgsym 경로 순), 없으면 설치 명령을 안내합니다.
- `/var/crash` 같은 디렉터리를 주면 가장 최근 덤프를 고릅니다. RHEL 계열 `<디렉터리>/vmcore`, Ubuntu·Debian `<YYYYMMDDHHMM>/dump.<시각>`, SSH로 받은 `vmcore.flat`을 모두 인식합니다.
- `-report`는 crash 셸에 들어가지 않고 명령별 섹션으로 나눈 리포트를 만듭니다: sys, bt, `bt -a`, D 상태 태스크, ps, 커널 로그, 메모리, 모듈, runq, 디스크, 마운트, 열린 파일, taint 모듈 관련 태스크.
- 커널 로그로 장애 유형(hung task, lockup, OOM, oops 등)을 판정하고 유형에 맞는 crash 명령을 덧붙입니다. 콜스택에 나온 모듈의 심볼을 불러오고, 아키텍처를 확인하고, JSON 요약도 남깁니다.
- LLM(OpenAI 호환 API, Gemini, Claude, Claude Code·Codex 구독)으로 원인, 근거, 영향, 조치를 정리합니다. 보내기 전에 민감정보를 마스킹하고 섹션 단위로 줄입니다.
- 자동화에서 결과를 판별할 수 있는 종료 코드를 돌려줍니다.

**화면**
- 터미널 메뉴(`analyze-kdump-ui`): vmcore 선택, 분석, 결과 보기, 원격 서버 관리, 설정, 업데이트를 메뉴로 합니다.
- 웹 UI: 노트북(Windows·macOS·Linux) 브라우저에서 서버 관리, 서버 준비(kdump 환경 점검·설치), 여러 덤프 일괄 분석과 작업 대기열, 진행 바, 분석 기록과 판정 요약, 리포트 검색, 서버별 설치·업그레이드를 합니다.
- 업데이트는 기본으로 GitHub 최신 릴리스를 받습니다(브랜치 최신 커밋 선택 가능).

## 디렉터리 구조

권장 설치 위치는 `/opt/kdump-tools`입니다.

```text
/opt/kdump-tools/
├── README.md
├── CHANGELOG.md               # 버전별 변경 기록
├── LICENSE                    # MIT 라이선스
├── VERSION                    # 버전 번호
├── .install-info              # 설치한 버전·커밋·시각 (install.sh가 기록)
├── install.sh                 # 설치·업데이트·명령 등록 (/usr/sbin)
├── analyze-kdump.conf.sample
├── servers.conf.sample
├── bin/
│   ├── analyze-kdump
│   └── analyze-kdump-ui
├── webui/                     # 노트북에서 실행하는 웹 UI (서버에는 필요 없음)
│   ├── kdump-webui.py
│   ├── kdump_llm.py           # LLM 분석 (Python, Windows에서도 동작)
│   └── static/
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

Ubuntu·Debian에서는 `crash`와 `kdump-tools`를 설치합니다. vmlinux는 dbgsym(ddebs) 저장소의 `linux-image-<커널 버전>-dbgsym` 패키지에 들어 있습니다. 설치하면 `/usr/lib/debug/boot/vmlinux-<커널 버전>`을 자동으로 찾습니다.

```bash
apt-get install -y crash kdump-tools
```

| 배포판 | 덤프 저장 위치 | 커널 로그 |
|--------|----------------|-----------|
| RHEL·Rocky·Alma·SUSE | `/var/crash/<IP>-<날짜-시각>/vmcore` | `vmcore-dmesg.txt` |
| Ubuntu·Debian (`kdump-tools`) | `/var/crash/<YYYYMMDDHHMM>/dump.<YYYYMMDDHHMM>` | `dmesg.<YYYYMMDDHHMM>` |

Ubuntu 26.04 Server는 `kdump-tools`, `crash`, crashkernel 예약을 기본으로 설치하지만 `/etc/default/kdump-tools`의 `USE_KDUMP=0`으로 꺼 둡니다. 웹 UI의 **서버 준비**가 이를 찾아 켜고(서비스 재시작), dbgsym 디버그 커널도 설치합니다. 26.04 커널의 dbgsym은 약 2.1GB이므로 디스크 여유를 확인하세요(설치 뒤 내려받은 패키지 파일은 지웁니다).

Hyper-V VM에서는 **동적 메모리를 끄세요.** Ubuntu 26.04 커널(7.0)에서 동적 메모리로 추가된 메모리가 CMA로 집계되어(`CmaTotal: 0`인데 `CmaFree`가 큼), kdump 커널을 올리는 kexec가 메모리가 남아 있는데도 OOM으로 실패했습니다(`kdump-tools.service: Failed with result 'oom-kill'`).

Ubuntu가 `/var/crash`에 함께 저장하는 사용자 프로그램 크래시 보고서(apport의 `*.crash`)와, 저장이 끝나지 않은 `dump-incomplete`는 목록에 넣지 않습니다.

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

메뉴(`sudo analyze-kdump-ui`)의 메인 화면에 현재 버전과 최신 버전이 바로 표시됩니다.

```text
현재 서버: 이 서버 (db01)
버전: v1.4.0 (974414a)
▲ 업데이트 가능: v1.4.1 (최신 릴리스 v1.4.1, abc1234) - 메뉴의 "업데이트"에서 설치
```

- **업데이트 기준:** 기본값은 GitHub의 **최신 릴리스**(태그)입니다. 검증을 마치고 릴리스로 낸 버전만 받으므로, main에 막 들어간 변경은 다음 릴리스 때 받습니다. 릴리스 전 변경까지 바로 받으려면 설정 메뉴의 `KDUMP_TOOLS_CHANNEL`을 `branch`로 바꿉니다(이때 `KDUMP_TOOLS_BRANCH`의 최신 커밋을 받음). 릴리스 기준에서는 main 등으로 이미 더 새 버전을 설치했으면 업데이트로 표시하지 않습니다.

- **최신 버전 확인:** 메뉴를 시작할 때 GitHub에서 한 번 확인합니다(최대 약 5초). 최신이면 `최신 버전 사용 중`, 접속에 실패하면 마지막으로 확인한 결과와 함께 `지금은 GitHub 접속 실패`가 표시됩니다.
- **폐쇄망:** 인터넷이 막힌 서버에서 시작할 때마다 기다리지 않으려면 설정 메뉴에서 `KDUMP_TOOLS_UPDATE_CHECK`를 끕니다.
- **업데이트 메뉴:** 메인 메뉴의 **업데이트**에서 설치합니다. 업데이트가 있으면 **변경 내역**(그 사이 커밋 목록)을 볼 수 있고, **최신 버전 다시 확인**도 할 수 있습니다.
- **GitHub에서 업데이트:** 최신 릴리스(또는 브랜치) 코드를 받아(`git`, 없으면 `curl`+`tar`) 같은 위치에 다시 설치합니다. 이미 최신이거나 더 새 버전이면 **GitHub에서 다시 설치**로 표시되고, 이전 버전으로 돌아가게 되면 확인 창에서 알려 줍니다. 끝나면 새 버전으로 메뉴를 다시 시작할 수 있습니다.
- **서버의 디렉터리에서 업데이트 (폐쇄망):** 인터넷이 막힌 서버라면 다른 곳에서 받은 저장소를 서버에 복사한 뒤 그 경로를 지정합니다.
- **유지되는 것:** 설정, 접속 서버 목록, 로그, vmlinux는 그대로 유지됩니다. 업데이트는 root로 실행해야 하고, `install.sh`로 설치한 경우에만 메뉴에서 할 수 있습니다.
- **저장소 변경:** 업데이트할 저장소와 브랜치는 설정 메뉴의 `KDUMP_TOOLS_REPO`(기본 `621dev/kdump-tools`)와 `KDUMP_TOOLS_BRANCH`(기본 `main`)로 바꿀 수 있습니다.

명령으로 업데이트하려면 저장소에서 원하는 버전을 받은 뒤 `install.sh`를 다시 실행합니다.

```bash
# 최신 릴리스 (태그 이름은 GitHub Releases에서 확인)
cd kdump-tools && git fetch --tags && git checkout v1.17.0 && sudo ./install.sh
# main 최신 커밋
cd kdump-tools && git checkout main && git pull && sudo ./install.sh
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

vmcore 파일 대신 디렉터리를 지정할 수도 있습니다. 디렉터리 안에 덤프(`vmcore`, `vmcore.flat`, `dump.<시각>` 순)가 있으면 그 파일을, 없으면 하위 디렉터리 중 가장 최근 덤프를 사용합니다. `vmcore.flat`처럼 makedumpfile flattened 형식인 덤프를 crash가 읽지 못하면 자동으로 변환합니다([중앙 분석 서버 구성](#중앙-분석-서버-구성-kdump-원격-전송)).

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
- **JSON 요약**(`REPORT_JSON`): 리포트와 같은 이름의 `.json` 파일에 장애 유형과 근거, 패닉 메시지, `sys` 값, D 상태 태스크 수, taint 모듈, 섹션 목록을 남깁니다. python3가 필요합니다. 웹 UI는 아직 이 파일을 가져오지 않습니다.

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
- **토큰 저장:** 장기 토큰은 `/opt/kdump-tools/secrets/claude-oauth-token`(폴더 700, 파일 600)에 저장하고, 설정에는 경로만 `LLM_CLI_TOKEN_FILE`로 남깁니다. 분석할 때는 이 토큰을 `CLAUDE_CODE_OAUTH_TOKEN` 환경변수로만 넘기므로 `ps` 같은 명령줄 목록에 보이지 않습니다.
- **CLI 경로 자동 탐색 (`LLM_CLI_PATH`):** PATH, `/usr/local/bin`, `/usr/bin`, `~/.local/bin`, `~/.npm-global/bin`, nvm 경로(`~/.nvm/versions/node/*/bin`)에서 CLI를 찾아 버전과 함께 보여줍니다.
  - RHEL 계열은 sudo 실행 경로에 `/usr/local/bin`이 없어서, `npm install -g`로 설치한 `claude`를 이름만으로는 못 찾습니다. 이때 전체 경로를 고르면 됩니다.
  - nvm으로 설치한 CLI는 같은 폴더의 `node`가 필요하므로, 실행할 때 CLI가 있는 폴더를 PATH 앞에 붙입니다.
- **실행 계정:** 메뉴를 `sudo`로 실행하면 CLI도 root로 실행되므로, 로그인도 root 계정 기준입니다.

로그인 정보는 CLI가 저장하고 자동으로 갱신하므로, 한 번 로그인하면 보통 다시 로그인할 필요가 없습니다. 오래 쓰지 않았거나, 다른 곳에서 로그아웃했거나, 비밀번호를 바꿔 세션이 만료되면 CLI 오류(`OAuth session expired` 등)가 분석 파일에 남습니다. 그때 메뉴의 구독 CLI 인증에서 다시 로그인합니다.

설정 파일로 직접 지정할 때는 다음과 같이 씁니다.

```bash
LLM_PROVIDER="claude-code"
LLM_CLI_PATH="/usr/local/bin/claude"
LLM_CLI_TOKEN_FILE="/opt/kdump-tools/secrets/claude-oauth-token"   # root만 읽을 수 있게 600
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

## 웹 UI

노트북(Windows·macOS·Linux)에서 실행해 브라우저로 쓰는 화면입니다. 서버 현장에서는 터미널 메뉴를, 평소 분석과 결과 확인은 웹 UI를 쓰는 식으로 함께 씁니다.

```text
[노트북: 웹 UI + 브라우저] ──SSH──▶ [분석 서버: analyze-kdump -r] ── crash 리포트 생성 (진행 바 실시간 표시)
          ◀────────────── 리포트 가져오기 ──────────────┘
          └─▶ LLM 분석 (노트북의 API 키 또는 Claude Code·Codex 구독)
```

```bash
python webui/kdump-webui.py
```

- **요구 사항:** Python 3.8 이상(표준 라이브러리만 사용, 추가 설치 없음), `ssh` 명령(Windows 10/11 기본 OpenSSH 포함). 저장소를 받아 그대로 실행합니다.
- **접속:** 실행하면 브라우저가 열리고, 콘솔에 `http://127.0.0.1:8730/?t=<토큰>` 주소가 출력됩니다.
  - `127.0.0.1`에만 열리고, 이 토큰 주소로 들어온 브라우저만 쓸 수 있습니다. 토큰은 실행할 때마다 바뀝니다.
  - 다른 Host 이름이나 다른 사이트에서 온 요청은 거부합니다(DNS 리바인딩, CSRF 방지).
- **옵션:** `--port`(기본 8730), `--data-dir`(기본 `~/.kdump-tools-web`), `--no-browser`, `--no-supervisor`
- **Windows에서 아이콘으로 실행:** 콘솔을 열지 않고 바탕화면 아이콘을 더블클릭해서 쓸 수 있습니다.
  - 한 번만 `windows\install-shortcut.cmd`를 더블클릭하거나 `python webui\kdump-webui.py --install-shortcut`을 실행하면 바탕화면과 시작 메뉴에 **kdump-tools 웹 UI** 아이콘이 생깁니다(`--shortcut-dir <폴더>`로 위치 지정, `--remove-shortcut`으로 삭제).
  - 아이콘은 `pythonw.exe`로 서버를 콘솔 창 없이 띄우고 브라우저를 엽니다. 이미 실행 중이면 새로 띄우지 않고 그 서버의 화면을 엽니다.
  - 종료는 **버전·업데이트** 화면의 **웹 UI 종료** 버튼으로 합니다. 진행 중이거나 대기 중인 작업이 있으면 종료하지 않습니다.
  - 출력은 데이터 폴더의 `webui.log`에 남고(1MB가 넘으면 `webui.log.old`로 넘김), 시작에 실패하면 대화 상자로 알립니다. 실행 중인 서버의 주소와 토큰은 `run.json`에 있습니다.
  - Python이 설치된 PC가 필요합니다. 저장소 폴더를 옮기면 바로가기를 다시 만드세요. 업데이트(`git pull`)와 다시 시작은 그대로 동작합니다.
- **다시 시작:** 실행한 프로세스는 콘솔을 맡는 감시 프로세스이고, 실제 서버는 그 아래에서 돕니다. 화면의 **웹 UI 다시 시작** 버튼(버전·업데이트 화면, 업데이트 직후 안내, 재시작 필요 안내)을 누르면 서버만 디스크에 있는 코드로 다시 뜹니다.
  - 토큰과 포트가 그대로라 다시 로그인할 필요가 없고, 페이지는 자동으로 새로 열립니다.
  - 진행 중이거나 대기 중인 작업이 있으면 다시 시작하지 않습니다.
  - `--no-supervisor`로 실행하면 감시 프로세스 없이 예전처럼 한 프로세스로 돌며, 화면에서 다시 시작할 수 없습니다.
- **저장 위치:** 서버 목록·설정·가져온 리포트와 분석은 데이터 디렉터리에 저장됩니다. API 키와 Claude Code 장기 토큰은 `secrets/`에 저장하고, 화면과 API 응답에는 내용을 보여주지 않습니다.

화면 구성:

| 영역 | 내용 |
|------|------|
| 서버 목록 (왼쪽) | 서버 추가·수정·삭제. 입력은 한 장의 양식(이름, user@host, 포트, SSH 키 파일, 원격 analyze-kdump 경로, crash 디렉터리, 분석 방식, sudo) |
| 서버 화면 | 연결 테스트(호스트, 원격 analyze-kdump 버전, crash 버전, vmcore 개수). vmcore 목록에서 **리포트** 또는 **리포트 + LLM 분석** 실행. 기록 칸에는 vmcore마다 만들어 둔 리포트와 분석 개수가 보이고, 누르면 최근 결과가 열림 |
| 서버 준비 (서버 화면의 탭) | 서버의 kdump 분석 환경을 점검합니다: kdump 서비스, crashkernel 예약, kdump 동작 준비, crash, 실행 중인 커널의 디버그 커널(vmlinux), 메모리·swap, 덤프 저장 공간, analyze-kdump. 점검은 서버를 바꾸지 않습니다. 빠진 항목은 골라서 설치할 수 있습니다(RHEL 계열은 dnf, Ubuntu·Debian은 apt). crashkernel 설정은 재부팅해야 적용되며, 재부팅은 직접 합니다 |
| 여러 vmcore 한 번에 | 체크박스로 고른 뒤 **리포트**, **리포트 + LLM 분석**, **LLM 분석만(기존 리포트)** 중 하나로 실행. "LLM 분석만"은 crash를 다시 돌리지 않고 vmcore마다 가장 최근 리포트로 분석합니다(리포트가 없는 vmcore는 건너뜀) |
| 작업 대기열 | 같은 서버의 crash 작업(리포트 생성, 설치)은 한 번에 하나씩, LLM 분석은 전체에서 한 번에 하나씩 요청한 순서대로 실행합니다. 앞 작업이 LLM 단계로 넘어가면 다음 작업의 리포트 생성이 바로 시작됩니다. 메모리가 작은 서버에서 crash 여러 개가 동시에 돌다 OOM으로 죽는 것을 막기 위한 것입니다. 대기 중인 작업은 카드에서 취소할 수 있습니다. crash 리포트 생성은 설정의 제한 시간(기본 30분)을 넘기면 원격의 crash까지 끝내고 실패로 처리해, 멈춘 crash 하나가 그 서버의 대기열을 막지 않게 합니다. 서버 준비·설치는 2시간으로 제한합니다 |
| 작업 카드 (오른쪽 아래) | crash 리포트 생성 진행 바(`3/12 bt -a`), vmlinux 읽는 중 표시, LLM 분석 단계, 경과 시간, 로그. 성공한 카드는 8초 뒤 자동으로 닫힘(마우스를 올려 두거나 로그를 펼치면 유지). 실패한 카드는 직접 닫을 때까지 남음 |
| 분석 기록 (왼쪽 위) | 모든 서버의 기록을 리포트 단위로 묶어 최신 순으로 표시: 판정 요약, panic 문자열, vmcore, 커널, LLM provider·모델. 서버·종류(LLM 분석 있음/리포트만) 필터와 검색, 이전 분석 열기, 다시 분석. 삭제한 서버의 기록도 볼 수 있음. 서버 화면의 "분석 결과" 탭은 같은 목록을 해당 서버만 보여줌 |
| 버전·업데이트 (왼쪽 위, 상단 버전 배지) | 노트북 kdump-tools의 현재 버전·커밋과 GitHub 최신 릴리스(또는 브랜치) 비교, 새 커밋 목록, **업데이트**. 서버마다 설치된 analyze-kdump 버전·설치 위치·설치 원본을 확인하고 **노트북 버전 설치/업그레이드** 또는 **GitHub 최신 설치/업그레이드** 실행 |
| 분석 결과 | LLM 분석을 제목·표·코드가 갖춰진 보고서로 표시, 원본 리포트로 이동 |
| 리포트 보기 | 섹션별 접기·펼치기, 검색(해당 섹션만 남기고 강조), 리포트를 LLM으로 (다시) 분석 |
| 설정 | provider·모델(API 모델 목록 불러오기), API 키 저장, 사내 호환 서버 주소, 구독 CLI 경로·장기 토큰, CLI 상태 확인, 연결 테스트, 마스킹·입력 크기·출력 토큰·제한 시간, crash 리포트 제한 시간(분) |

화면을 옮길 때마다 주소 끝에 위치(`#/history`, `#/server/<서버>/results` 등)가 남습니다. 그래서 브라우저의 뒤로·앞으로 가기로 이전 화면을 오갈 수 있고, 새로고침해도 보던 화면이 유지됩니다.

분석 기록의 "판정" 한 줄은 분석 파일에서 찾습니다. `판정:` 줄, 요약 표의 판정·근본 원인 행, `추정 근본 원인:` 항목, "근본 원인" 제목 아래 첫 문장 순으로 찾습니다. 기본 프롬프트는 LLM에게 보고서 첫 줄을 `판정: <한 문장>`으로 쓰도록 요청합니다.

원격 서버 분석 방식은 **원격 설치본 실행**과 **무설치 실행**(스크립트를 원격 임시 디렉터리로 보내 실행한 뒤 지움), 그리고 둘 중 하나를 고르는 **자동 선택**을 지원합니다. SSH 키 인증으로 비밀번호 없이 접속할 수 있어야 하고, sudo를 쓰면 원격 서버에 비밀번호 없는 sudo(NOPASSWD)가 필요합니다. 처음 접속하는 서버의 호스트 키는 자동으로 등록합니다(`StrictHostKeyChecking=accept-new`).

LLM 분석은 `webui/kdump_llm.py`에서 합니다. analyze-kdump와 같은 방식(마스킹, 섹션 단위 축소, provider 호출, 구독 CLI)을 Python으로 옮긴 것이라 Windows에서도 동작하고, 분석 파일 형식도 같습니다.
- Claude Code는 시스템 프롬프트를 파일(`--system-prompt-file`)로 넘깁니다.
- Windows에서는 npm 실행기(`claude.cmd`) 대신 안의 실제 `claude.exe`를 실행합니다. `.cmd`를 거치면 cmd.exe가 인자를 다시 해석하기 때문입니다.

버전·업데이트 화면:
- **업데이트 기준:** 기본은 GitHub의 **최신 릴리스**(태그)입니다. 같은 화면의 "업데이트 설정"에서 **브랜치 최신 커밋**으로 바꾸면 릴리스 전 변경까지 받습니다. 노트북이 최신 릴리스보다 앞선 커밋(예: main)이면 `최신보다 앞선 버전`으로 표시하고 업데이트하지 않습니다.
- **노트북 업데이트:** 릴리스 기준이면 최신 릴리스 태그를 받아 현재 브랜치를 그 태그까지 fast-forward(`git merge --ff-only`)하고, 브랜치 기준이면 `git pull --ff-only`를 실행합니다.
  - git으로 받은 저장소여야 하고, 커밋하지 않은 변경이 없고, 현재 브랜치가 업데이트 브랜치와 같아야 합니다. 조건이 맞지 않으면 업데이트하지 않고 이유를 보여줍니다.
  - 화면 파일만 바뀌었으면 새로고침하면 적용됩니다. 웹 UI의 Python 코드가 바뀌었으면 웹 UI를 다시 실행하라고 안내합니다.
- **서버 설치·업그레이드:** 서버 설정의 원격 analyze-kdump 경로(기본 `/opt/kdump-tools/bin/analyze-kdump`)에서 설치 위치를 정하고, 서버에서 `install.sh`를 실행합니다. 설정, 접속 서버 목록, 로그, vmlinux는 install.sh가 유지합니다.
  - **노트북 버전:** 노트북에 있는 파일을 SSH로 보냅니다. 서버에 인터넷이 없어도 되고, 서버에 `tar`가 없어도 됩니다(`base64`만 사용).
  - **GitHub 릴리스(또는 최신):** 서버가 GitHub에서 업데이트 기준에 맞는 태그나 브랜치를 직접 받습니다. 서버에 인터넷과 `git`(또는 `curl`과 `tar`)이 필요합니다.
  - 두 방식 모두 root 권한이 필요하므로, 서버 설정에서 sudo를 켜야 합니다(비밀번호 없는 sudo).
- 업데이트 기준, 저장소, 브랜치(기본 최신 릴리스, `621dev/kdump-tools`, `main`)는 같은 화면의 "업데이트 설정"에서 바꿀 수 있습니다.

웹 UI에 없는 기능: crash 셸 직접 입력, vmcore를 가져와 로컬에서 crash로 분석하는 기능(Windows에서는 crash가 동작하지 않음), 구독 CLI 설치와 로그인(노트북에서 `claude auth login`이나 `codex login`으로 직접 로그인하거나, 설정에서 장기 토큰을 붙여넣음).

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

진행 표시: crash 리포트 생성은 진행 바와 현재 명령(`[####....] 3/12 bt -a (12초)`)으로, 처음 vmlinux를 읽는 동안은 `crash 시작 중`과 경과 시간으로 보여줍니다. LLM 분석은 회전 표시와 경과 시간, vmcore 가져오기는 진행 바와 받은 크기로 보여줍니다. 원격 서버 확인 중에는 안내 화면이 뜹니다.

| 메뉴 | 내용 |
|------|------|
| vmcore 분석 | 선택한 서버의 crash 디렉터리에서 vmcore를 최근 순으로 보여주고, 리포트 생성 / 리포트 + LLM 분석 / crash 셸 진입 중 하나를 실행합니다. 끝나면 결과(종료 코드 의미 포함)와 리포트·분석 보기를 제공합니다 |
| 분석 결과 보기 | 선택한 서버의 리포트와 분석 파일을 최근 순으로 보여줍니다. 리포트를 골라 LLM으로 (다시) 분석할 수 있습니다 |
| 접속 서버 선택 | 분석할 서버를 고릅니다. "이 서버"는 메뉴를 실행한 서버입니다 |
| 접속 서버 관리 | 원격 서버를 추가·수정·삭제하고, 기본 분석 방식을 정하고, 연결 테스트(SSH, analyze-kdump, crash, vmcore 개수, 자동 선택될 분석 방식)를 합니다 |
| 설정 | `analyze-kdump.conf`의 주요 항목(경로, LLM provider·모델·키 파일·CLI·마스킹·한도)을 바꿉니다. API 키 자체는 저장하지 않고 키 파일 경로만 지정합니다 |
| kdump 원격 전송 안내 | 운영 서버의 vmcore를 이 서버로 자동 전송하는 `/etc/kdump.conf` 설정을 이 서버 주소로 채워 보여줍니다(중앙 분석 서버 구성) |
| 업데이트 | 변경 내역을 보여주고, GitHub나 서버의 디렉터리에서 업데이트합니다. 현재·최신 버전은 메인 화면에 표시됩니다([버전 확인과 업데이트](#버전-확인과-업데이트)) |

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
- **flattened 형식:** SSH 전송은 makedumpfile의 flattened 형식으로 저장됩니다(RHEL 계열은 `vmcore.flat`, Ubuntu·Debian은 이름은 `dump.<시각>`이지만 내용이 flattened이고, Ubuntu·Debian은 로컬 저장도 이 형식입니다).
  - crash 9.0.1(Rocky 9.8, Ubuntu 26.04)은 이 형식을 바로 읽으므로 변환하지 않고 그대로 분석합니다.
  - crash가 읽지 못하면(오래된 crash) `analyze-kdump`가 파일 앞부분의 서명으로 알아보고 `makedumpfile -R`로 변환한 뒤 분석합니다. 변환본은 같은 디렉터리의 `vmcore`로 남겨 다음 분석부터 바로 쓰고, 덤프 목록(메뉴, 웹 UI)에도 변환본만 보입니다. 원본은 지우지 않으므로 공간이 덤프 크기만큼 더 필요합니다.
  - 덤프 디렉터리에 쓸 수 없거나 공간이 모자라면 임시 디렉터리(`TMPDIR`, 기본 `/tmp`)에 변환하고 분석이 끝나면 지웁니다. 이때 리포트의 `vmcore:` 줄에는 원본 경로가 남습니다.
  - `FLAT_CONVERT=0`이면 변환하지 않고 변환 명령을 안내한 뒤 멈춥니다.
  - 1.18.0보다 오래된 버전은 덤프 목록에 `vmcore.flat`을 보여 주지 않습니다. 분석 서버의 설치본을 업그레이드하세요.
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

### 장애 유형별 검증

`tests/vm/fault-module/`의 테스트 커널 모듈(`kdump_fault`)로 여러 장애를 재현할 수 있습니다.
- **테스트 VM 전용입니다.** 모듈을 올리는 즉시 커널이 패닉합니다.
- 서명하지 않은 모듈이므로 VM의 Secure Boot를 꺼야 합니다(Hyper-V: `Set-VMFirmware -VMName <VM> -EnableSecureBoot Off`).
- 빌드에는 `kernel-devel-$(uname -r)`, `gcc`, `make`가 필요합니다.

```bash
cd tests/vm/fault-module && make
sudo sysctl -w kernel.softlockup_panic=1 kernel.hung_task_panic=1 kernel.hung_task_timeout_secs=30
sync; sudo insmod kdump_fault.ko type=hungtask quiet=1
```

| type | 재현하는 장애 | 커널 메시지 |
|------|---------------|-------------|
| `null` | NULL 포인터 역참조 | `BUG: kernel NULL pointer dereference` |
| `bug` | `BUG()` 호출 | `kernel BUG at ...` |
| `gpf` | non-canonical 주소 쓰기 | `general protection fault` |
| `listcorrupt` | 연결 리스트 손상 | `list_add corruption` |
| `softlockup` | 선점을 끈 무한 루프 | `soft lockup - CPU#N stuck` |
| `hungtask` | mutex를 쥔 채 잠드는 스레드와 그 mutex를 기다리는 스레드 | `blocked for more than N seconds` |

`quiet=1`을 주면 모듈이 로그 메시지를 남기지 않습니다. 실제 장애처럼 리포트만으로 원인을 찾을 수 있는지 볼 때 씁니다.

모듈 없이 만들 수 있는 장애도 있습니다.
- **OOM 패닉:** `vm.panic_on_oom=1`을 켠 뒤 메모리를 고갈시킵니다.
- **I/O hang:** 루프 장치 파일시스템을 `fsfreeze -f`로 멈춘 뒤 그 파일시스템에 씁니다.

2026-11 Ubuntu 26.04.1 LTS(커널 7.0.0-42, crash 9.0.1) VM에서도 SysRq-c로 만든 `dump.<시각>`을 리포트와 LLM으로 분석해 원인을 맞게 판정했습니다. crash가 이 커널의 패닉 시각은 읽지 못해(`DATE: 1970`) 리포트의 시각은 부팅 후 경과 시간으로 봐야 합니다.

2026-11 Rocky Linux 9.8(커널 5.14.0-687) VM에서 위 8가지와 SysRq-c로 만든 vmcore 9건을 리포트와 LLM(Claude Code)으로 분석했습니다. 9건 모두 원인을 맞게 판정했습니다. `quiet=1`로 만든 hung task도 `foreach UN bt`와 "taint 모듈 관련 태스크" 섹션으로 잠금을 쥔 스레드까지 찾았습니다.

## 로그 디렉터리

`logs/`는 분석 결과나 작업 기록을 남기기 위한 디렉터리입니다. `-report` 옵션으로 생성되는 요약 리포트가 이 디렉터리에 저장됩니다.

## 라이선스

[MIT 라이선스](LICENSE)로 배포합니다. 버전별 변경 내용은 [CHANGELOG.md](CHANGELOG.md)에 있습니다.
