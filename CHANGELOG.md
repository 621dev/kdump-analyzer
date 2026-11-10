# 변경 기록

버전 번호는 [유의적 버전](https://semver.org/lang/ko/)을 따릅니다. 기능이 추가되면 가운데 자리, 고친 것만 있으면 끝자리를 올립니다.
GitHub 릴리스가 있는 버전은 업데이트 기능(기본: 최신 릴리스)으로 받을 수 있습니다.
1.18.3까지는 프로젝트 이름이 `kdump-tools`였습니다. 아래 기록의 링크는 GitHub이 새 주소로 연결합니다.

## [1.24.2] - 2026-11-10

### 고침
- 웹 UI: 버전·업데이트 화면의 서버 표가 좁은 화면에서 카드 밖으로 넘치던 문제. 카드 폭이 좁으면 서버마다 한 덩어리로 쌓고 버튼은 아래 줄로 보냅니다 (#50)

### 바뀜
- 웹 UI는 노트북뿐 아니라 데스크톱이나 관리용 서버에서도 실행하므로, 화면·메시지·문서의 '노트북' 표현을 '웹 UI' 기준으로 바꿨습니다. 예: '노트북 버전 업그레이드' → '웹 UI 버전 업그레이드', '이 노트북의 kdump-analyzer' → '웹 UI의 kdump-analyzer' (#50)

## [1.24.1] - 2026-11-10

### 고침
- 서버 설정의 원격 analyze-kdump 경로가 경로가 아닌 명령 이름(`analyze-kdump`)이면, 설치돼 있어도 연결 테스트는 '없음', 분석 방식 자동 선택은 무설치 실행으로 판단하던 문제 (웹 UI, 터미널 메뉴) (#46)
- 웹 UI: 좁은 화면에서 덤프 목록의 경로가 한 글자씩 세로로 늘어서던 문제. 버튼은 두 줄로 나뉘고, 아주 좁으면 표 안에서만 옆으로 스크롤합니다 (#48)

### 바뀜
- 웹 UI: 암호(passphrase)를 건 SSH 키가 ssh-agent에 등록돼 있지 않아 접속이 거부되면, `Permission denied` 대신 `ssh-add` 명령과 ssh-agent 서비스 켜기를 안내합니다(오류 메시지, 연결 테스트, 작업 로그) (#47)
- 웹 UI: Windows에서는 Windows OpenSSH(`System32\OpenSSH`)의 `ssh`·`scp`를 먼저 씁니다. Git Bash에서 실행해도 Windows ssh-agent를 쓸 수 있습니다 (#47)

## [1.24.0] - 2026-11-10

### 추가
- 웹 UI: **새 덤프 자동 분석** (#41)
  - 서버마다 끄기 / 리포트만 만들기 / 리포트 + LLM 분석을 고르고, 설정의 확인 주기(기본 10분)마다 웹 UI가 켜져 있는 동안 덤프 목록을 확인합니다.
  - 켠 뒤 처음에는 기존 덤프를 기준으로만 기록하고, 이후 새 덤프만 분석합니다. 덮어쓴 `MEMORY.DMP`도 수정 시각이 바뀌면 새 덤프로 봅니다. 1분 이내에 쓰인 덤프는 다음 확인으로 미룹니다.
  - "자동 ·" 작업 카드, 화면 알림과 데스크톱 알림, 서버 머리글의 자동 분석 표시(마지막 확인 결과)
- 웹 UI: **보고서로 내보내기** (#43). 요약, 가장 최근 LLM 분석, 원본 리포트를 HTML 한 장으로 저장합니다(PDF로 인쇄 가능). 민감정보 가리기를 고를 수 있습니다.
- 웹 UI: **덤프 보관 관리** (#44). 덤프 디렉터리 디스크의 남은 공간, 덤프를 노트북으로 받기(Linux는 sudo로 읽어 SSH로, Windows는 scp로; 진행 표시와 취소), 덤프 삭제(서버 이름을 입력해야 실행, 덤프 디렉터리 안만)
- Windows 분석 스크립트: `-ProcessList` (#40)
- 웹 UI API 판 9

### 바뀜
- 웹 UI: Windows에서는 API 키와 Claude Code 장기 토큰을 DPAPI로 암호화해 저장합니다. 예전 평문 키는 웹 UI를 시작할 때 자동으로 암호화합니다 (#42).
- Windows 분석 스크립트: 프로세스 목록(`!process 0 0`)을 기본에서 뺐습니다. 커널 덤프 분석이 85초에서 16초로 줄었습니다(실제 VM). 필요하면 `-ProcessList`로 넣습니다 (#40).

### 고침
- Windows 분석 스크립트: 시간 초과로 cdb를 강제로 끝낸 직후 출력 파일이 잠겨 있으면, 리포트 없이 종료 코드 1로 끝나던 문제 (#44)

### 문서
- Hyper-V 기본 스위치 테스트 VM은 `<호스트 이름>.mshome.net`으로 접속하면 IP가 바뀌어도 접속됩니다 (#40).

## [1.23.1] - 2026-11-09

### 고침
- Windows: 블루스크린 뒤 재부팅 직후 Windows가 0바이트로 만들어 두는 미니덤프를 덤프 목록과 분석 대상에서 뺍니다. 빈 덤프를 직접 지정하면 "아직 쓰는 중일 수 있다"고 안내합니다(실제 VM에서 발견).

### 문서
- README에 지원 환경을 정리했습니다: 역할별(Linux RHEL 계열, Debian 계열, Windows 서버, 웹 UI 실행 PC) 지원 대상과 실제 VM에서 검증한 버전
- Windows 가이드에 실제 덤프 검증 결과를 추가했습니다: NMI 주입과 드라이버 오류(NotMyFault 0xD1) 덤프의 판정, 근거, LLM 분석
- README를 요약(소개, 5분 시작, 주요 기능, 문서 목록)으로 줄이고, 자세한 안내는 `docs/`의 가이드 문서로 나눴습니다: 설치와 업데이트, 사용법, 설정 파일과 LLM, 웹 UI, Windows 서버, 터미널 메뉴, 개발과 검증
- 서버 설치(`install.sh`, 웹 UI의 노트북 버전 설치)에 `docs/`도 함께 복사해 폐쇄망 서버에서도 가이드를 볼 수 있게 했습니다. 웹 UI의 "프로그램만" 삭제는 `docs/`와 `tests/`도 지웁니다.

## [1.23.0] - 2026-11-09

### 추가
- 웹 UI에서 서버의 분석 도구 **삭제** (Linux·Windows, 버전·업데이트 화면)
  - **프로그램만**(명령 등록·자동완성·프로그램 파일과 설치 정보. 설정·서버 목록·로그·vmlinux, Windows는 로그·심볼은 남김) 또는 **전부**(설치 디렉터리 통째로) 중에서 고르고, 서버 이름을 입력해 확인합니다.
  - 설치 정보나 분석 도구가 있는 디렉터리만 지우고, 시스템 디렉터리(`/usr`, `/etc`, 드라이브 바로 아래 등)는 지우지 않습니다. 설치된 install.sh의 판에 기대지 않고 웹 UI가 보내는 명령으로 지웁니다.
- Windows 2단계
  - 서버 준비 탭에서 **덤프 설정**(커널 메모리 덤프, 자동 재시작, 덮어쓰기), **페이지 파일**(시스템 관리 크기), **디버거 설치**를 실행합니다. 디버거는 서버가 Microsoft에서 Windows SDK 설치 관리자를 받아 Microsoft 서명을 확인한 뒤 Debugging Tools for Windows만 설치합니다.
  - Windows 서버도 **GitHub 릴리스(또는 최신) 설치/업그레이드**. 노트북이 GitHub에서 분석 스크립트를 받아 scp로 보내므로 서버에 인터넷이 없어도 됩니다.
- 웹 UI API 판 8

## [1.22.0] - 2026-11-09

### 추가
- Windows 서버의 블루스크린 메모리 덤프 분석 (1단계: 분석과 웹 UI 연결)
  - `winbin/analyze-windump.ps1`: `cdb`로 `!analyze -v` 등을 실행해 Linux와 같은 형식의 리포트·JSON 요약을 만듭니다. 버그체크 코드로 장애 유형을 판정하고 원인 후보 드라이버를 근거로 남깁니다. Windows PowerShell 5.1에서 동작하고, `-TimeoutSec`으로 cdb 시간 제한을 둡니다. `-CdbPath`로 지정한 cdb가 없으면 다른 cdb로 넘어가지 않고 오류로 끝냅니다.
  - 웹 UI: 서버 추가 양식에 **운영체제**(Linux/Windows). Windows 서버의 덤프 목록, 연결 테스트, 버전 확인, 원격 설치본·무설치 실행, 노트북 버전 설치, 서버 준비 점검(덤프 설정, 페이지 파일, cdb, 저장 공간, 관리자 권한)
  - NMI·수동 덤프에서는 `!analyze -v`가 지목한 드라이버를 원인 후보가 아닌 '처리 드라이버'로 표시 (실제 Hyper-V NMI 덤프에서 `GenuineIntel.sys`가 지목됨)
  - Windows Server 2025 평가판 VM의 실제 블루스크린 덤프(커널 메모리 덤프, 미니덤프)로 설치·설치본 실행·무설치 실행 확인
  - 분석 기록과 요약 상자에 원인 후보 드라이버, Windows 장애 유형(메모리 손상, 핵심 프로세스 종료, 디스크·부팅)
  - LLM 분석: Windows 리포트에는 Windows용 지시문, cdb 섹션별 입력 축소 비율
  - 원격 명령은 `powershell -EncodedCommand`, 분석 스크립트는 `scp`로 보내고 리포트는 base64로 가져옴
- 테스트: 가짜 cdb로 분석 스크립트 27개 항목(`tests/windows/test-windump.ps1`, CI에서 Windows PowerShell 5.1·PowerShell 7), 웹 UI의 Windows 명령을 이 PC에서 실제로 실행하는 테스트
- `tests/vm/windows-vm-setup.md`: Windows Server 테스트 VM 준비 순서
- 웹 UI API 판 7

## [1.21.0] - 2026-11-06

### 추가
- 웹 UI가 리포트의 JSON 요약을 씁니다.
  - 리포트를 가져올 때 같은 이름의 `.json`도 가져와 옆에 둡니다(무설치 실행 포함).
  - 분석 기록: 장애 유형 배지, 판정 근거, D 상태 태스크 수, taint 모듈을 보여 주고, 장애 유형으로 거를 수 있습니다. 근거와 유형도 검색합니다.
  - 리포트 보기: 맨 위에 요약 상자(장애 유형, 판정 근거, 패닉 메시지, D 상태 태스크, taint 모듈, 불러온 모듈 심볼, 시스템 값, crash 종료 코드).
  - JSON이 없는 예전 리포트도 머리글의 `type:`·`evidence:` 줄로 유형을 보여 줍니다.
- 설치 위치 옮기기: `install.sh --move-to /opt/kdump-analyzer`로 예전 위치(`/opt/kdump-tools`)의 설치를 설정·서버 목록·API 키·vmlinux·리포트까지 통째로 옮깁니다.
  - 같은 파일 시스템이면 `mv`로 바로 끝나고, 다르면 공간을 확인한 뒤 복사합니다.
  - `analyze-kdump.conf` 안의 경로를 고치고(원본은 `.before-move`), 예전 경로에는 새 위치를 가리키는 링크를 남깁니다(`--no-link`로 끔).
  - 명령, 자동완성, 설치 정보를 새 위치로 다시 등록합니다.
  - 웹 UI 버전·업데이트 화면의 **새 위치로 옮기기**(노트북 버전으로 업그레이드한 뒤 옮기고, 서버 설정의 경로도 바꿈)와 메뉴의 **업데이트 → 설치 위치 옮기기**에서도 할 수 있습니다.
- `install.sh --help`가 모든 옵션을 보여 줍니다.

## [1.20.0] - 2026-11-06

### 변경
- 새로 설치하는 서버의 기본 설치 위치가 저장소 이름을 따라 `/opt/kdump-analyzer`가 됩니다.
  - `install.sh`: `--prefix`가 없으면 이미 설치된 곳을 우선합니다. 예전 기본 위치 `/opt/kdump-tools`에만 설치돼 있으면 그 자리를 업데이트하고(설치가 둘로 갈라지지 않게), 어디에도 없으면 `/opt/kdump-analyzer`에 설치합니다.
  - 웹 UI·메뉴: 서버를 추가할 때 원격 경로 기본값이 `/opt/kdump-analyzer/bin/analyze-kdump`입니다. 그 서버에 새 경로 설치가 없고 예전 위치에만 있으면 연결 테스트, 버전 확인, 서버 준비, 분석, 업그레이드가 예전 위치의 설치본을 씁니다. 직접 지정한 경로(기존 서버의 `/opt/kdump-tools/...` 포함)는 그대로 씁니다.
  - 설치 정보가 없는 곳에서 실행(무설치 실행 등)할 때도 `/opt/kdump-analyzer` 설치를 먼저, 없으면 예전 위치를 씁니다.
- 설정 샘플(`analyze-kdump.conf.sample`)의 `VMLINUX_BASE`, `REPORT_DIR`를 주석으로 바꿨습니다. 기본값이 설치 위치를 따라가므로 지정하지 않는 것이 맞습니다.
- 이미 `/opt/kdump-tools`에 설치된 서버는 아무것도 바뀌지 않습니다. 옮기려면 새 위치에 설치하고 설정·vmlinux·로그를 직접 옮겨야 합니다.

## [1.19.0] - 2026-11-06

### 변경
- 프로젝트 이름을 `kdump-tools`에서 `kdump-analyzer`로 바꿨습니다. Debian·Ubuntu의 `kdump-tools` 패키지(덤프를 만드는 쪽)와 헷갈리지 않게 하려는 것입니다.
  - GitHub 저장소: `621dev/kdump-analyzer` (예전 주소는 GitHub이 자동으로 연결)
  - 업데이트 기본 저장소, 웹 UI·메뉴 화면의 이름, Windows 바로가기 이름(`kdump-analyzer 웹 UI`, 예전 이름 바로가기는 새로 만들 때 지움)
  - 그대로 두는 것: 기본 설치 위치 `/opt/kdump-tools`, 웹 UI 데이터 폴더 `~/.kdump-tools-web`, 설정 이름 `KDUMP_TOOLS_*`, 명령 이름 `analyze-kdump`·`analyze-kdump-ui`. 이미 설치된 서버는 그대로 업데이트됩니다.
- 기본 경로가 설치 위치를 따라갑니다. `install.sh --prefix`로 다른 곳에 설치하면 설정 파일, 서버 목록, vmlinux, 로그의 기본 위치도 그 아래가 됩니다. 설치 정보(`.install-info`)가 없는 곳(무설치 실행, 저장소에서 바로 실행)에서는 예전처럼 `/opt/kdump-tools`를 씁니다.

## [1.18.3] - 2026-11-06

### 추가
- 자동 테스트: `tests/run-tests.sh`(가짜 crash로 analyze-kdump·메뉴 59개 항목), `tests/test_webui.py`(웹 UI·LLM 모듈), `tests/shellcheck-embedded.py`(웹 UI 안의 원격 셸 스크립트 검사)
- GitHub Actions CI: shellcheck, pyflakes, Linux(Python 3.8·3.13)와 Windows 테스트
- `.shellcheckrc`: 의도한 패턴만 끄고 나머지는 가장 엄격한 수준으로 검사

### 수정
- 접속 대상(user@host)이 `-`로 시작하면 거부합니다. ssh가 옵션(`-oProxyCommand=...`)으로 읽어 웹 UI를 띄운 노트북이나 메뉴를 실행한 서버에서 명령이 실행될 수 있었습니다(웹 UI는 저장할 때와 접속할 때 모두 확인).
- 웹 UI에서 숫자 칸에 글자를 넣는 등 잘못된 값이면 연결을 끊지 않고 400 오류와 이유를 돌려줍니다.
- 구독 CLI 실행 때 작업 폴더로 옮기지 못하면 다른 위치에서 CLI를 실행하지 않고 멈춥니다.
- shellcheck 지적 정리(배열 첨자, 반환값 확인 방식 등). 동작 변화는 없습니다.

## [1.18.2] - 2026-11-06

### 수정
- flattened 형식 덤프를 crash가 바로 읽으면 변환하지 않습니다. 1.18.0은 flattened 형식이면 항상 변환해서, 로컬 저장도 이 형식인 Ubuntu·Debian에서는 덤프마다 같은 크기의 `vmcore`를 하나 더 만들었습니다. crash 9.0.1(Rocky 9.8, Ubuntu 26.04)은 flattened 형식을 바로 읽으며, 이제 crash가 읽지 못할 때만 변환합니다.

## [1.18.1] - 2026-11-06

### 추가
- MIT 라이선스(`LICENSE`)와 이 변경 기록(`CHANGELOG.md`). 설치(`install.sh`)와 웹 UI의 서버 설치에 함께 들어갑니다.
- README 맨 위에 5분 시작 가이드(서버에서 바로 / 노트북 웹 UI)와 목차를 넣고, 소개와 주요 기능을 현재 기능에 맞게 고쳤습니다.

## [1.18.0] - 2026-11-06 ([릴리스](https://github.com/621dev/kdump-tools/releases/tag/v1.18.0))

### 추가
- SSH로 받은 makedumpfile flattened 형식 덤프(`vmcore.flat`, Ubuntu·Debian SSH 전송의 `dump.<시각>`)를 `makedumpfile -R`로 자동 변환해 분석합니다. 변환본은 같은 디렉터리의 `vmcore`로 남기고, 쓸 수 없으면 임시 디렉터리에 만들어 분석 뒤 지웁니다(`FLAT_CONVERT`). (#26)
- 웹 UI·메뉴 덤프 목록에 `vmcore.flat`을 넣고, 변환본이 있으면 변환본만 보여 줍니다.

### 수정
- 덤프 디렉터리 끝에 `/`를 붙이면 경로가 `//vmcore`로 표시되던 문제
- 상위 디렉터리에 덤프가 없을 때 안내 없이 끝날 수 있던 문제

## [1.17.0] - 2026-11-06 ([릴리스](https://github.com/621dev/kdump-tools/releases/tag/v1.17.0))

### 변경
- 업데이트가 기본으로 GitHub 최신 릴리스(태그)를 받습니다. 웹 UI "업데이트 설정"이나 메뉴 설정 `KDUMP_TOOLS_CHANNEL=branch`로 브랜치 최신 커밋을 고를 수 있습니다. (#25)
- 릴리스 기준에서는 더 새 버전이 설치돼 있으면 업데이트로 표시하지 않고, 이전 버전으로 돌아갈 때 경고합니다.
- 웹 UI API 판 6

## [1.16.0] - 2026-11-06

### 추가
- 커널 로그로 장애 유형(hung task, soft/hard lockup, RCU stall, OOM, oops, MCE·NMI, 수동 덤프)을 판정해 리포트 머리글에 `type:`·`evidence:`를 남기고 유형별 crash 명령을 덧붙입니다(`REPORT_TYPE_COMMANDS`). (#24)
- 콜스택에 나온 모듈의 디버그 심볼을 불러옵니다(`REPORT_MODULE_SYMBOLS=auto|all|off`).
- vmcore, vmlinux, 서버의 아키텍처를 먼저 비교합니다(`REPORT_ARCH_CHECK`).
- 리포트 옆에 `.json` 요약을 만듭니다(`REPORT_JSON`).

## [1.15.1] - 2026-11-06 ([릴리스](https://github.com/621dev/kdump-tools/releases/tag/v1.15.1), 1차 완성판)

### 수정
- OpenSSH 10.1 이상이 RHEL 9 서버에 접속할 때 내는 post-quantum 경고가 리포트와 로그에 섞이던 문제 (#23)

## [1.15.0] - 2026-11-06

### 추가
- 웹 UI의 crash 리포트 생성에 제한 시간(기본 30분, 설정에서 변경)을 두고, 넘기면 원격의 crash까지 끝냅니다. 서버 준비·설치는 2시간으로 제한합니다. (#22)

## [1.14.0] - 2026-11-05

### 추가
- Windows에서 바탕화면·시작 메뉴 아이콘으로 웹 UI를 콘솔 창 없이 실행합니다(`windows\install-shortcut.cmd`). (#21)

## [1.13.0] - 2026-11-04

### 추가
- Ubuntu·Debian 덤프(`/var/crash/<YYYYMMDDHHMM>/dump.<시각>`)와 dbgsym vmlinux를 지원합니다. (#20)
- 웹 UI **서버 준비** 탭: kdump 서비스, crashkernel, crash, 디버그 커널, 메모리·swap, 저장 공간을 점검하고 빠진 것을 설치합니다(dnf, apt).

## [1.12.1] - 2026-11-04

### 수정
- 웹 UI 자식 프로세스가 감시 프로세스의 파이프를 물려받아 원격 서버 접속이 멈추던 문제 (#19)

## [1.12.0] - 2026-11-04

### 추가
- 웹 UI를 화면에서 다시 시작하는 버튼(감시 프로세스가 서버를 디스크의 코드로 다시 띄움) (#18)

## [1.11.2] - 2026-11-04

### 수정
- 분석 기록의 판정 한 줄을 더 정확히 뽑고, 브라우저 뒤로 가기를 지원합니다. (#17)

## [1.11.1] - 2026-11-04

### 추가
- 업데이트 뒤 웹 UI 서버를 다시 시작해야 하면 알려 줍니다. (#16)

## [1.11.0] - 2026-11-04

### 추가
- 웹 UI에서 여러 vmcore를 골라 한 번에 분석하고, 작업 대기열로 순서대로 실행합니다. (#15)

## [1.10.0] - 2026-11-04

### 추가
- 리포트에 D 상태 태스크, taint 모듈 관련 태스크, runq, 디스크 I/O 섹션을 추가했습니다. (#14)

## [1.9.0] - 2026-11-04

### 추가
- 웹 UI 버전·업데이트 화면: 노트북 업데이트, 서버별 설치·업그레이드 (#13)

## [1.8.0] - 2026-11-04

### 추가
- 웹 UI 분석 기록 화면과 자동으로 닫히는 작업 카드 (#12)

## [1.7.0] - 2026-11-04

### 추가
- 노트북에서 쓰는 로컬 웹 UI(`webui/kdump-webui.py`): 서버 관리, 리포트 생성 진행 표시, LLM 분석 보기 (#11)

## [1.6.1] - 2026-11-03

### 수정
- Claude Code 공식 설치 스크립트가 sudo 아래에서 멈추던 문제 (#10)

## [1.6.0] - 2026-11-03

### 추가
- 구독 CLI가 없으면 메뉴에서 설치까지 진행합니다. (#9)

## [1.5.0] - 2026-11-03

### 추가
- 구독 CLI(Claude Code, Codex) 인증 메뉴, CLI 경로 자동 탐색, 모델 목록 조회 (#8)

## [1.4.2] - 2026-11-03

### 수정
- 메뉴 안내 문구가 첫 줄만 보이던 문제 (#7)

## [1.4.1] - 2026-11-03

### 추가
- 메뉴 메인 화면에 현재·최신 버전을 표시합니다. (#6)

## [1.4.0] - 2026-11-03

### 추가
- 버전 정보(`analyze-kdump --version`, `.install-info`)와 업데이트 메뉴 (#5)

## 1.4.0 이전 - 2026-11-03

- `analyze-kdump` 오류 처리와 LLM 연동 개선 (#1)
- 터미널 메뉴 UI(`analyze-kdump-ui`)와 리포트 LLM 재분석 (#2)
- 설치 스크립트(명령 등록)와 상황별 원격 분석 방식 (#3)
- 분석 진행 표시와 메뉴의 이전 화면 이동 (#4)

[1.24.2]: https://github.com/621dev/kdump-analyzer/compare/v1.24.1...main
[1.24.1]: https://github.com/621dev/kdump-analyzer/compare/v1.24.0...v1.24.1
[1.24.0]: https://github.com/621dev/kdump-analyzer/compare/v1.23.1...v1.24.0
[1.23.1]: https://github.com/621dev/kdump-analyzer/compare/v1.23.0...v1.23.1
[1.23.0]: https://github.com/621dev/kdump-analyzer/compare/v1.22.0...v1.23.0
[1.22.0]: https://github.com/621dev/kdump-analyzer/compare/v1.21.0...v1.22.0
[1.21.0]: https://github.com/621dev/kdump-analyzer/compare/v1.20.0...v1.21.0
[1.20.0]: https://github.com/621dev/kdump-analyzer/compare/v1.19.0...v1.20.0
[1.19.0]: https://github.com/621dev/kdump-analyzer/compare/v1.18.3...v1.19.0
[1.18.3]: https://github.com/621dev/kdump-tools/compare/v1.18.2...v1.18.3
[1.18.2]: https://github.com/621dev/kdump-tools/compare/v1.18.0...v1.18.2
[1.18.1]: https://github.com/621dev/kdump-tools/pull/27
[1.18.0]: https://github.com/621dev/kdump-tools/compare/v1.17.0...v1.18.0
[1.17.0]: https://github.com/621dev/kdump-tools/compare/v1.15.1...v1.17.0
[1.16.0]: https://github.com/621dev/kdump-tools/pull/24
[1.15.1]: https://github.com/621dev/kdump-tools/pull/23
[1.15.0]: https://github.com/621dev/kdump-tools/pull/22
[1.14.0]: https://github.com/621dev/kdump-tools/pull/21
[1.13.0]: https://github.com/621dev/kdump-tools/pull/20
[1.12.1]: https://github.com/621dev/kdump-tools/pull/19
[1.12.0]: https://github.com/621dev/kdump-tools/pull/18
[1.11.2]: https://github.com/621dev/kdump-tools/pull/17
[1.11.1]: https://github.com/621dev/kdump-tools/pull/16
[1.11.0]: https://github.com/621dev/kdump-tools/pull/15
[1.10.0]: https://github.com/621dev/kdump-tools/pull/14
[1.9.0]: https://github.com/621dev/kdump-tools/pull/13
[1.8.0]: https://github.com/621dev/kdump-tools/pull/12
[1.7.0]: https://github.com/621dev/kdump-tools/pull/11
[1.6.1]: https://github.com/621dev/kdump-tools/pull/10
[1.6.0]: https://github.com/621dev/kdump-tools/pull/9
[1.5.0]: https://github.com/621dev/kdump-tools/pull/8
[1.4.2]: https://github.com/621dev/kdump-tools/pull/7
[1.4.1]: https://github.com/621dev/kdump-tools/pull/6
[1.4.0]: https://github.com/621dev/kdump-tools/pull/5
