# kdump-analyzer

Linux 커널 패닉 덤프(`vmcore`)와 Windows 블루스크린 덤프를 분석하는 도구입니다. 덤프에 맞는 디버그 커널로 `crash`(Windows는 `cdb`)를 실행해 리포트 한 장을 만들고, 원하면 LLM으로 원인과 조치까지 정리합니다.

[![CI](https://github.com/621dev/kdump-analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/621dev/kdump-analyzer/actions/workflows/ci.yml)

[변경 기록](CHANGELOG.md) · [릴리스](https://github.com/621dev/kdump-analyzer/releases) · [라이선스 (MIT)](LICENSE)

## 구성

| 구성 | 실행 위치 | 하는 일 |
|---|---|---|
| `analyze-kdump` | 분석 서버 | 리포트와 LLM 분석을 만드는 명령 |
| `analyze-kdump-ui` | 분석 서버 터미널 | SSH로 접속해 쓰는 메뉴 화면 |
| 웹 UI | PC나 관리 서버 | 여러 서버를 SSH로 관리하고 브라우저에서 분석 |
| `analyze-windump.ps1` | Windows 서버 | 블루스크린 덤프 분석 (웹 UI가 사용) |

## 지원 환경

| 역할 | 지원 대상 |
|---|---|
| Linux 분석 서버 | • RHEL·Rocky·Alma·Oracle Linux 8 이상<br>• Ubuntu·Debian<br>• RHEL·CentOS 7은 로그 형식과 설치 안내만 지원 |
| Windows 서버 | Windows Server 2019 이상 |
| 웹 UI 컴퓨터 | Windows·Linux·macOS, Python 3.8 이상과 `ssh` |

검증한 버전, 필요한 패키지, 방화벽에서 허용할 주소는 [필요한 패키지와 네트워크](docs/requirements.md)에 있습니다.

## 빠른 시작

### 서버에서 바로 분석

```bash
git clone https://github.com/621dev/kdump-analyzer.git
sudo ./kdump-analyzer/install.sh        # /opt/kdump-analyzer에 설치
sudo analyze-kdump -r /var/crash        # 가장 최근 덤프로 리포트 만들기
```

- 디버그 커널(`vmlinux`)이 없으면 설치 명령을 알려 주고 멈춥니다.
- 리포트 맨 위의 `type:`·`evidence:` 줄에 장애 유형과 근거가 있습니다.
- 메뉴 화면은 `sudo analyze-kdump-ui`로 엽니다. LLM 분석은 [LLM을 설정](docs/configuration.md)한 뒤 `-llm`을 붙입니다.

### 웹 UI로 분석

```bash
git clone https://github.com/621dev/kdump-analyzer.git
python kdump-analyzer/webui/kdump-webui.py
```

1. 브라우저가 열리면 **+ 추가**로 서버(`user@host`, SSH 키 파일)를 넣고 **연결 테스트**를 누릅니다.
2. **서버 준비** 탭에서 빠진 항목(crash, 디버그 커널, kdump 설정)을 설치합니다.
3. 덤프 목록에서 **리포트** 또는 **리포트 + LLM 분석**을 누릅니다.

분석할 서버에는 아무것도 설치하지 않아도 됩니다. 서버에는 SSH 키로 접속하는 계정과 비밀번호 없는 sudo가 필요합니다.

## 문서

| 문서 | 내용 |
|---|---|
| [설치와 업데이트](docs/install.md) | 설치, 업데이트, 설치 위치 옮기기, 삭제 |
| [필요한 패키지와 네트워크](docs/requirements.md) | 지원 환경, 패키지, 방화벽·프록시 허용 목록 |
| [analyze-kdump 사용법](docs/usage.md) | 명령 옵션, 리포트 구성, 장애 유형 판정, vmlinux 준비 |
| [설정 파일과 LLM](docs/configuration.md) | 설정 항목, LLM 연결, API 키, 구독 계정 |
| [웹 UI](docs/webui.md) | 실행, 화면별 기능, 자동 분석, 서버에서 상시 실행 |
| [Windows 서버](docs/windows.md) | 서버 준비, 분석 스크립트, 버그체크 유형 |
| [터미널 메뉴](docs/terminal-ui.md) | 메뉴 조작, 원격 분석, 중앙 분석 서버 |
| [개발과 검증](docs/development.md) | 자동 테스트, CI, 테스트 VM 검증 |

1.18.3까지는 이름이 `kdump-tools`였습니다. Debian·Ubuntu의 `kdump-tools` 패키지(덤프를 만드는 쪽)와 헷갈리지 않도록 v1.19.0에서 바꿨습니다.

[MIT 라이선스](LICENSE)로 배포합니다.
