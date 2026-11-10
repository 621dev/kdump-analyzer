# 설치와 업데이트

[README](../README.md) · [설치](install.md) · [사용법](usage.md) · [설정·LLM](configuration.md) · [웹 UI](webui.md) · [Windows](windows.md) · [터미널 메뉴](terminal-ui.md) · [개발·검증](development.md)

서버에 analyze-kdump를 설치하고 업데이트하는 방법입니다.

## 요구 사항

- `bash`
- `crash`
- 분석 대상 `vmcore`
- `vmcore`의 커널 버전과 일치하는 `vmlinux`
- LLM 분석과 JSON 요약을 쓸 경우 `curl`과 Python 3.6 이상. `python3`가 없으면 RHEL 8 최소 설치에도 있는 `/usr/libexec/platform-python`을 씁니다.
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

저장소를 받은 뒤 `install.sh`를 root로 실행합니다. 파일을 `/opt/kdump-analyzer`에 복사하고 모든 명령(`analyze-kdump`, `analyze-kdump-ui`)을 `/usr/sbin`에 등록하므로, 이후에는 어디서나 명령 이름만으로 실행할 수 있습니다.

```bash
git clone https://github.com/621dev/kdump-analyzer.git
sudo ./kdump-analyzer/install.sh
```

```bash
sudo analyze-kdump-ui
sudo analyze-kdump -r /var/crash
```

- **설정과 데이터:** 이미 있는 `analyze-kdump.conf`, `servers.conf`, `logs/`, `vmlinux/`는 덮어쓰지 않습니다. 새 버전을 받은 뒤 다시 실행하면 업데이트됩니다.
- **등록 위치:** `/usr/sbin`에 심볼릭 링크로 등록합니다. RHEL 계열은 sudo의 `secure_path`에 `/usr/local/*`가 없어서, `/usr/local/bin`에 두면 `sudo analyze-kdump-ui`가 명령을 찾지 못합니다. 같은 이름의 일반 파일이 이미 있으면 덮어쓰지 않고 건너뜁니다.
- **자동완성:** `/etc/bash_completion.d`가 있으면 `analyze-kdump` 옵션과 경로의 Tab 자동완성도 등록합니다. 새 셸부터 적용됩니다.
- **도구 점검:** 설치가 끝나면 crash, whiptail, python3, curl, ssh가 있는지 보여줍니다.
- **설치 옵션:** 설치 위치와 등록 위치는 `--prefix`, `--bin-dir`로 바꿀 수 있습니다. 다른 위치에 설치하면 설정 파일(`analyze-kdump.conf`), 서버 목록(`servers.conf`), vmlinux, 로그의 기본 위치도 그 아래로 따라갑니다.
- **예전 설치 위치:** 1.19.0까지의 기본 설치 위치는 `/opt/kdump-tools`였습니다. 이미 그곳에 설치된 서버는 `--prefix` 없이 다시 실행해도 그 자리를 업데이트하고(설치가 둘로 갈라지지 않게), 웹 UI·메뉴도 새 기본 경로에 설치가 없으면 예전 위치의 설치본을 씁니다. 새로 설치하는 서버만 `/opt/kdump-analyzer`에 설치됩니다. 웹 UI 데이터 폴더(`~/.kdump-tools-web`)와 설정 이름(`KDUMP_TOOLS_*`)은 예전 이름 그대로입니다.
- **설치 위치 옮기기:** 예전 위치의 설치를 새 기본 위치로 옮기려면 다음을 실행합니다. 웹 UI의 **버전·업데이트** 화면(서버 줄의 **새 위치로 옮기기**)이나 메뉴의 **업데이트 → 설치 위치 옮기기**도 같은 일을 합니다.

  ```bash
  sudo /opt/kdump-tools/install.sh --move-to /opt/kdump-analyzer
  ```

  - 설정(`analyze-kdump.conf`), 접속 서버 목록(`servers.conf`), API 키(`secrets/`), vmlinux, 리포트를 통째로 옮깁니다. 같은 파일 시스템이면 바로 끝나고 공간도 더 들지 않습니다. 다른 파일 시스템이면 복사하므로 공간을 먼저 확인합니다.
  - `analyze-kdump.conf` 안의 예전 경로를 새 위치로 고치고, 원래 내용은 `analyze-kdump.conf.before-move`로 남깁니다. `servers.conf`의 경로는 다른 서버의 경로라 고치지 않습니다.
  - 예전 경로(`/opt/kdump-tools`)에는 새 위치를 가리키는 링크를 남겨, 다른 곳에 저장된 예전 경로(웹 UI의 서버 설정, 스크립트 등)도 계속 동작하게 합니다. 링크가 필요 없으면 `--no-link`를 붙입니다.
  - 명령(`/usr/sbin`), 자동완성, 설치 정보를 새 위치로 다시 등록합니다.
  - 웹 UI에서 옮기면 먼저 웹 UI 버전으로 업그레이드하고(옮기기 기능이 필요), 끝나면 그 서버 설정의 원격 analyze-kdump 경로도 새 위치로 바꿉니다.
- **설치 정보:** 설치한 버전, 커밋, 시각, 원본, 등록 위치를 `/opt/kdump-analyzer/.install-info`에 기록하고, `install.sh` 자신도 `/opt/kdump-analyzer`에 복사합니다. 저장소 폴더를 지워도 업데이트와 해제를 할 수 있습니다.

등록을 해제하려면 다음을 실행합니다. 등록한 명령과 자동완성만 지우고, `/opt/kdump-analyzer`(설정, 서버 목록, 로그, vmlinux)는 남깁니다.

```bash
sudo /opt/kdump-analyzer/install.sh --uninstall
```

웹 UI의 버전·업데이트 화면에서도 서버마다 **삭제**로 지울 수 있습니다. 이때는 범위를 고릅니다.
- **프로그램만:** 명령 등록, 자동완성, 프로그램 파일(`bin`, `install.sh` 등)과 설치 정보를 지웁니다. 설정, 서버 목록, API 키, 로그, vmlinux는 남깁니다.
- **전부:** 설치 디렉터리를 통째로 지웁니다. 설치 위치를 옮긴 뒤 남긴 예전 경로 링크도 지웁니다. 되돌릴 수 없습니다.

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
- **저장소 변경:** 업데이트할 저장소와 브랜치는 설정 메뉴의 `KDUMP_TOOLS_REPO`(기본 `621dev/kdump-analyzer`)와 `KDUMP_TOOLS_BRANCH`(기본 `main`)로 바꿀 수 있습니다.

명령으로 업데이트하려면 저장소에서 원하는 버전을 받은 뒤 `install.sh`를 다시 실행합니다.

```bash
# 최신 릴리스 (태그 이름은 GitHub Releases에서 확인)
cd kdump-analyzer && git fetch --tags && git checkout v1.17.0 && sudo ./install.sh
# main 최신 커밋
cd kdump-analyzer && git checkout main && git pull && sudo ./install.sh
```

원격 서버는 분석 방식에 따라 다릅니다. **원격 설치본 실행** 방식으로 쓰는 서버는 그 서버에서도 업데이트해야 합니다. 연결 테스트 화면에서 원격 서버의 버전을 확인할 수 있습니다. **무설치 실행**은 매번 메뉴를 실행한 서버의 최신 버전을 보내서 쓰고, **vmcore 가져오기**는 원격에 설치할 것이 없습니다.

## 디렉터리 구조

권장 설치 위치는 `/opt/kdump-analyzer`입니다.

```text
/opt/kdump-analyzer/
├── README.md                  # 요약과 문서 목록
├── docs/                      # 가이드 문서 (설치, 사용법, 설정, 웹 UI, Windows, 메뉴, 개발)
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
├── winbin/
│   └── analyze-windump.ps1    # Windows 서버용 분석 스크립트 (웹 UI가 Windows 서버에 보냄)
├── webui/                     # 웹 UI (분석할 서버에는 필요 없음)
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
