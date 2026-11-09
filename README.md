# kdump-analyzer

Linux 커널 패닉 덤프(`vmcore`)와 Windows 블루스크린 메모리 덤프를 빠르게 분석하는 도구 모음입니다. 덤프에 맞는 디버그 커널을 찾아 `crash`(Windows는 `cdb`)를 실행하고, 장애 분석에 필요한 정보를 리포트 한 장으로 모은 뒤, 원하면 LLM으로 원인과 조치까지 정리합니다.

[![CI](https://github.com/621dev/kdump-analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/621dev/kdump-analyzer/actions/workflows/ci.yml)

[변경 기록](CHANGELOG.md) · [릴리스](https://github.com/621dev/kdump-analyzer/releases) · [라이선스 (MIT)](LICENSE)

| 구성 | 어디서 | 하는 일 |
|---|---|---|
| **`analyze-kdump`** | 분석 서버 | 리포트 생성과 LLM 분석 명령 |
| **`analyze-kdump-ui`** | 분석 서버 터미널 | 장애 현장에서 SSH로 쓰는 메뉴 화면 |
| **웹 UI** (`webui/kdump-webui.py`) | 노트북 브라우저 | 여러 서버를 SSH로 관리하고 분석 |
| **Windows 분석 스크립트** (`winbin/analyze-windump.ps1`) | Windows 서버 | 블루스크린 덤프를 `cdb`로 분석 (웹 UI에서 사용) |

지원: RHEL·Rocky·Alma 계열, Ubuntu·Debian, Windows Server(웹 UI). 예전 이름은 `kdump-tools`였고, Debian·Ubuntu의 `kdump-tools` 패키지(덤프를 만드는 쪽)와 헷갈리지 않도록 v1.19.0에서 바꿨습니다.

## 5분 시작 가이드

덤프가 이미 `/var/crash`에 있다고 가정합니다. kdump가 아직 설정되지 않았다면 웹 UI의 **서버 준비**로 점검·설치하거나 [요구 사항](docs/install.md#요구-사항)을 먼저 봅니다.

### A. 서버에서 바로 분석하기

```bash
git clone https://github.com/621dev/kdump-analyzer.git
sudo ./kdump-analyzer/install.sh        # /opt/kdump-analyzer에 설치, 명령은 /usr/sbin에 등록
sudo analyze-kdump -r /var/crash        # 가장 최근 덤프로 리포트 만들기
```

- 디버그 커널(`vmlinux`)이 없으면 설치 명령을 알려 주고 멈춥니다. 안내대로 설치한 뒤 다시 실행합니다.
- 끝나면 `report:` 줄에 리포트 경로가 나옵니다. 리포트 맨 위의 `type:`·`evidence:` 줄에서 장애 유형과 근거를 먼저 봅니다.
- 메뉴로 하려면 `sudo analyze-kdump-ui`, LLM 분석까지 하려면 [LLM 설정](docs/configuration.md) 뒤 `-llm`을 붙입니다.

### B. 노트북에서 웹 UI로 분석하기

서버에 설치하지 않아도 노트북에서 스크립트를 보내 분석합니다(무설치 실행).

```bash
git clone https://github.com/621dev/kdump-analyzer.git
python kdump-analyzer/webui/kdump-webui.py
```

1. 노트북에 Python 3.8 이상과 `ssh`, 서버에는 SSH 키로 접속하는 계정과 비밀번호 없는 sudo가 필요합니다.
2. 브라우저가 열리면 **+ 추가**로 서버(`user@host`, SSH 키 파일)를 넣고 **연결 테스트**를 누릅니다. Windows 서버는 **운영체제**를 Windows로 고릅니다.
3. **서버 준비** 탭에서 빠진 항목(crash, 디버그 커널, kdump 설정, Windows는 디버거와 덤프 설정)을 설치합니다.
4. 덤프 목록에서 **리포트** 또는 **리포트 + LLM 분석**을 누릅니다. LLM은 **설정**에서 API 키나 Claude Code·Codex 구독을 연결합니다.

Windows에서는 `kdump-analyzer\windows\install-shortcut.cmd`를 한 번 실행하면 바탕화면 아이콘으로 띄울 수 있습니다. 여러 운영 서버의 덤프를 한 곳에 모으려면 [중앙 분석 서버 구성](docs/terminal-ui.md#중앙-분석-서버-구성-kdump-원격-전송)을 봅니다.

## 주요 기능

- **덤프 찾기:** 디렉터리를 주면 가장 최근 덤프를 고르고, 커널 버전에 맞는 `vmlinux`를 찾습니다. RHEL·Ubuntu 형식과 SSH로 받은 flattened 덤프를 모두 인식합니다.
- **리포트:** crash 명령별 섹션(sys, bt, `bt -a`, D 상태 태스크, 커널 로그, 메모리, 모듈, 디스크 등)으로 나눈 리포트와 JSON 요약을 만듭니다.
- **장애 유형 판정:** 커널 로그로 hung task, lockup, OOM, oops 등을 판정하고 유형에 맞는 명령을 덧붙입니다. Windows는 버그체크 코드로 판정하고 원인 후보 드라이버를 보여 줍니다.
- **LLM 분석:** OpenAI 호환 API, Gemini, Claude, Claude Code·Codex 구독으로 원인, 근거, 영향, 조치를 정리합니다. 보내기 전에 민감정보를 마스킹하고 섹션 단위로 줄입니다.
- **웹 UI:** 서버 관리, 서버 준비(환경 점검·설치), 여러 덤프 일괄 분석과 작업 대기열, 분석 기록과 판정 요약, 리포트 검색, 서버별 설치·업그레이드·삭제
- **업데이트:** 기본으로 GitHub 최신 릴리스를 받습니다(브랜치 최신 커밋 선택 가능).

## 문서

| 문서 | 내용 |
|---|---|
| [설치와 업데이트](docs/install.md) | 요구 사항, 설치(`install.sh`), 설치 위치 옮기기, 삭제, 버전 확인과 업데이트, 디렉터리 구조 |
| [analyze-kdump 사용법](docs/usage.md) | 명령 옵션, 동작 순서, 종료 코드, 리포트 섹션, 장애 유형 판정, LLM 입력 축소와 마스킹, vmlinux 준비 |
| [설정 파일과 LLM](docs/configuration.md) | `analyze-kdump.conf` 항목, LLM provider별 설정, API 키 관리, 구독 계정(Claude Code·Codex) 사용 |
| [웹 UI](docs/webui.md) | 실행과 접속, Windows 아이콘, 화면별 기능, 원격 분석 방식, 서버 설치·업그레이드·삭제 |
| [Windows 서버](docs/windows.md) | 서버에 필요한 것, 분석 스크립트, 버그체크 유형, 웹 UI에서의 설치·서버 준비 |
| [터미널 메뉴 UI](docs/terminal-ui.md) | `analyze-kdump-ui` 조작, 상황별 사용 방식, 원격 분석 방식, 중앙 분석 서버(kdump 원격 전송) |
| [개발과 검증](docs/development.md) | 자동 테스트, CI, 테스트 VM에서 실제 덤프로 검증하기 |
| [Windows 테스트 VM 준비](tests/vm/windows-vm-setup.md) | Hyper-V로 Windows Server 테스트 VM을 만들고 블루스크린을 내는 순서 |

## 라이선스

[MIT 라이선스](LICENSE)로 배포합니다. 버전별 변경 내용은 [CHANGELOG.md](CHANGELOG.md)에 있습니다.
