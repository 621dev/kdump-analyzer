# 필요한 패키지와 네트워크

[README](../README.md) · [설치](install.md) · [요구 사항·네트워크](requirements.md) · [사용법](usage.md) · [설정·LLM](configuration.md) · [웹 UI](webui.md) · [Windows](windows.md) · [터미널 메뉴](terminal-ui.md) · [개발·검증](development.md)

이 문서는 kdump-analyzer를 쓰려면 컴퓨터마다 설치해야 할 패키지와, 방화벽·프록시에서 허용해야 할 접속을 한곳에 모은 것입니다. 기능별로 필요한 것만 허용하면 됩니다. 인터넷이 없는 환경에서 쓰는 방법은 [인터넷이 없는 환경](#인터넷이-없는-환경)에 있습니다.

```text
웹 UI 컴퓨터 ──SSH(22)──▶ Linux·Windows 분석 서버
     │                         │
     ├─ HTTPS ─▶ LLM API        ├─ 패키지 저장소 (서버 준비: crash, kdump, 디버그 커널)
     └─ HTTPS ─▶ GitHub         ├─ HTTPS ─▶ GitHub (GitHub에서 설치·업데이트를 고른 경우)
        (업데이트)              ├─ HTTPS ─▶ LLM API (서버에서 직접 LLM 분석할 때)
                                └─ HTTPS ─▶ Microsoft 심볼 서버 (Windows)
```

## 패키지

### Linux 분석 서버

| 용도 | 명령 | RHEL 계열 패키지 | Ubuntu·Debian 패키지 |
|---|---|---|---|
| 기본 실행 | `bash`, `crash` | `crash` | `crash` |
| 덤프 커널에 맞는 `vmlinux` | 디버그 커널 패키지 | `kernel-debuginfo-<버전>` (UEK는 `kernel-uek-debuginfo`, 실시간 커널은 `kernel-rt-debuginfo`) | `linux-image-<버전>-dbgsym` 또는 `linux-image-unsigned-<버전>-dbgsym` (Debian은 `linux-image-<버전>-dbg`) |
| 디버그 커널 설치 명령 | `debuginfo-install` | `dnf-plugins-core` (RHEL·CentOS 7은 `yum-utils`) | (Ubuntu) `ubuntu-dbgsym-keyring` |
| 덤프 만들기 (kdump) | `kdumpctl` 또는 `kdump-config` | `kexec-tools` | `kdump-tools`, `kexec-tools`, `makedumpfile` |
| LLM 분석, JSON 요약 | `python3` 3.6 이상, `curl` | `python3`, `curl` (RHEL 8은 `python3`가 없어도 `/usr/libexec/platform-python`을 씀) | `python3`, `curl` |
| 터미널 메뉴 (`analyze-kdump-ui`) | `whiptail` | `newt` | `whiptail` |
| 구독 CLI를 서버에서 쓸 때 (선택) | `claude` 또는 `codex` | Node.js 22와 `npm`(`nodejs`, `npm`), 또는 Claude Code 설치 스크립트 | 같음 |
| GitHub에서 설치·업데이트할 때 (선택) | `git`, 또는 `curl`과 `tar` | `git` | `git` |
| 웹 UI의 무설치 실행·웹 UI 버전 설치 | `base64` | `coreutils` (기본 설치) | `coreutils` (기본 설치) |

- **권한:** 웹 UI가 SSH로 접속하는 계정은 덤프를 읽고 패키지를 설치하려면 비밀번호 없는 `sudo`가 필요합니다.
- **디스크와 메모리:** 디버그 커널 패키지는 수백 MB에서 약 2.1GB(Ubuntu 26.04)입니다. `crash`는 커널 디버그 정보를 읽을 때 약 1.5GB의 메모리를 씁니다(RHEL 9 커널 기준). 자세한 내용은 [설치와 업데이트](install.md#요구-사항)에 있습니다.
- **서버 준비:** 웹 UI의 **서버 준비** 탭은 위 패키지 중 `crash`, kdump, 디버그 커널을 `dnf`·`yum`·`apt-get`으로 설치합니다.

### Windows 서버

| 용도 | 필요한 것 |
|---|---|
| 웹 UI 접속 | OpenSSH 서버, 관리자 계정의 SSH 키 접속(`administrators_authorized_keys`) |
| 분석 스크립트 실행 | Windows PowerShell 5.1 (Windows Server 2019 이상에 기본 포함) |
| 덤프 분석 | Debugging Tools for Windows(x64)의 `cdb.exe`. Windows SDK 설치 관리자에서 이 기능만 설치합니다 |
| 덤프 만들기 | 덤프 설정(커널 메모리 덤프 등)과 페이지 파일 |

자세한 내용은 [Windows 서버](windows.md)에 있습니다.

### 웹 UI 컴퓨터

| 필요한 것 | 비고 |
|---|---|
| Python 3.8 이상 | 표준 라이브러리만 씁니다. `pip`으로 따로 설치할 라이브러리는 없습니다 |
| OpenSSH 클라이언트(`ssh`) | Windows 10/11에는 기본으로 들어 있습니다 |
| `git` (선택) | 화면의 **업데이트**를 쓰려면 웹 UI를 `git clone`으로 받아야 합니다 |
| Claude Code·Codex CLI (선택) | 구독 계정으로 LLM 분석을 할 때만 필요합니다. [구독 계정으로 사용하기](configuration.md#구독-계정으로-사용하기-claude-code--codex-cli)를 봅니다 |
| 브라우저 | 웹 UI는 `127.0.0.1`에서만 듣습니다. 다른 컴퓨터에서는 SSH 터널로 접속합니다 |

## 네트워크

### 연결 방향과 포트

| 출발 | 도착 | 포트 | 용도 |
|---|---|---|---|
| 웹 UI 컴퓨터 | Linux·Windows 분석 서버 | TCP 22 (서버 설정에서 바꿀 수 있음) | SSH. 분석, 서버 준비, 덤프 받기, 설치를 모두 이 연결로 합니다 |
| 브라우저 | 웹 UI | TCP 8730 (`127.0.0.1`만) | 웹 UI 화면. 바깥에 열 필요가 없습니다. 다른 컴퓨터에서는 `ssh -L 8730:127.0.0.1:8730 <사용자>@<웹 UI 서버>`로 접속합니다 |
| 운영 서버 (선택) | 중앙 분석 서버 | TCP 22 | kdump가 덤프를 SSH로 보낼 때. [중앙 분석 서버 구성](terminal-ui.md#중앙-분석-서버-구성-kdump-원격-전송)을 봅니다 |

들어오는 연결은 분석 서버의 SSH 하나뿐입니다. 아래 인터넷 접속은 모두 나가는 HTTPS(TCP 443)입니다. 예외는 Ubuntu 디버그 저장소로, `http://`(TCP 80)를 씁니다.

### 응답 트래픽 (들어오는 쪽을 모두 막은 경우)

이 문서의 허용 목록은 나가는 연결만 적었습니다. 그 연결의 응답이 들어오는지는 방화벽 종류에 따라 다릅니다.

| 방화벽 종류 | 예 | 응답 트래픽 |
|---|---|---|
| 상태 기반(stateful) | Linux firewalld·iptables·nftables, Windows Defender 방화벽, AWS 보안 그룹, 대부분의 사내 방화벽 장비 | 안에서 시작한 연결을 기억해 응답을 자동으로 통과시킵니다(iptables의 `ESTABLISHED,RELATED`). 들어오는 쪽이 모두 막혀 있어도 따로 열 것이 없습니다 |
| 비상태(stateless) | AWS 네트워크 ACL(NACL), 라우터·L3 스위치 ACL, 일부 오래된 장비 | 패킷을 하나씩 따로 검사하므로 응답이 들어오는 규칙도 있어야 합니다 |

- **비상태 방화벽에서 열 것:** 응답은 보낸 쪽 OS가 고른 임시 포트로 돌아옵니다. 출발 포트 443(Ubuntu 디버그 저장소는 80, SSH는 22)에서 도착 포트 1024–65535로 들어오는 TCP를 허용합니다. 임시 포트의 기본 범위는 Linux가 32768–60999(`sysctl net.ipv4.ip_local_port_range`), Windows가 49152–65535(`netsh int ipv4 show dynamicport tcp`)입니다.
- **SSH도 같습니다:** 웹 UI 컴퓨터는 SSH 연결을 시작하는 쪽이라, 상태 기반 방화벽이면 들어오는 쪽을 열 필요가 없습니다. 비상태 ACL이면 웹 UI 컴퓨터 쪽에는 분석 서버의 22번 포트에서 들어오는 응답을, 분석 서버 쪽에는 22번 포트에서 웹 UI 컴퓨터의 임시 포트로 나가는 응답을 허용합니다.
- **나가는 쪽도 모두 막은 경우:** 요청부터 막히므로 응답도 없습니다. 아래 주소를 나가는 허용 규칙으로 엽니다.
- **프록시를 쓰는 경우:** 방화벽에는 프록시 주소와 포트만 열고, 아래 주소는 프록시의 허용 목록에 넣습니다. 프록시를 쓰려면 다음 설정이 필요합니다.
  - 패키지 관리자: `dnf.conf`의 `proxy=`, apt의 `Acquire::http::Proxy`
  - `git`, `curl`, 웹 UI: `https_proxy` 환경변수(웹 UI는 Python 표준 라이브러리라 이 변수를 따릅니다)
  - Windows 심볼 서버: `cdb`의 심볼 다운로드는 시스템 프록시 설정을 따릅니다. 따로 지정하려면 `_NT_SYMBOL_PROXY` 환경변수(`<프록시>:<포트>`)를 씁니다

### 웹 UI 컴퓨터에서 나가는 접속

| 주소 | 용도 | 필요할 때 |
|---|---|---|
| `api.openai.com` | OpenAI API | LLM provider가 `openai`일 때. OpenAI 호환 API는 설정한 기본 URL로 접속합니다 |
| `generativelanguage.googleapis.com` | Gemini API | LLM provider가 `gemini`일 때 |
| `api.anthropic.com` | Claude API | LLM provider가 `claude`일 때 |
| Claude Code·Codex CLI가 쓰는 주소 | 구독 계정 LLM 분석 | `claude-code`·`codex`일 때. 웹 UI는 CLI를 실행할 뿐이라 CLI가 직접 접속합니다. Claude Code는 `api.anthropic.com`, 로그인에 `claude.ai`를 쓰고, Codex는 `chatgpt.com`, 로그인에 `auth.openai.com`을 씁니다. 정확한 목록은 각 CLI의 문서를 확인합니다 |
| `api.github.com`, `raw.githubusercontent.com` | 최신 릴리스와 새 커밋 확인, Windows 분석 스크립트 받기 | 버전·업데이트 화면, Windows 서버에 GitHub 버전 설치 |
| `github.com` | 웹 UI 업데이트(`git fetch`) | 화면의 **업데이트** |

### Linux 분석 서버에서 나가는 접속

| 주소 | 용도 | 필요할 때 |
|---|---|---|
| 배포판 패키지 저장소 (서버에 설정된 미러) | `crash`, `kexec-tools`·`kdump-tools`, `python3`, `nodejs` 등 설치 | 서버 준비, 패키지를 직접 설치할 때 |
| 배포판 debuginfo 저장소 | 디버그 커널(`vmlinux`) 설치 | 서버 준비의 디버그 커널 설치. 아래 표를 봅니다 |
| `api.github.com`, `github.com`, `codeload.github.com`, `raw.githubusercontent.com` | analyze-kdump 설치·업데이트 | 웹 UI의 **GitHub 최신 설치/업그레이드**, 터미널 메뉴의 업데이트 |
| `api.openai.com`, `generativelanguage.googleapis.com`, `api.anthropic.com` (또는 설정한 `LLM_BASE_URL`) | LLM 분석 | 서버에서 `analyze-kdump -llm`이나 터미널 메뉴로 LLM 분석을 할 때 |
| `claude.ai`, `registry.npmjs.org` | Claude Code·Codex CLI 설치 | 터미널 메뉴에서 구독 CLI를 설치할 때 |

배포판별 debuginfo 저장소:

| 배포판 | 주소 | 비고 |
|---|---|---|
| Rocky·Alma | 서버의 `/etc/yum.repos.d`에 있는 debuginfo 저장소 주소 | 저장소 파일은 기본으로 들어 있고, `dnf debuginfo-install`이 켜서 씁니다 |
| RHEL | Red Hat CDN(`cdn.redhat.com`) | 구독이 필요합니다. 서버 준비가 `subscription-manager`로 debug 저장소를 켭니다 |
| Oracle Linux | `oss.oracle.com` | 서버 준비가 `/etc/yum.repos.d/oracle-debuginfo.repo`를 추가합니다 |
| Ubuntu | `ddebs.ubuntu.com` (`http://`, TCP 80) | 서버 준비가 `/etc/apt/sources.list.d/ddebs.list`를 추가합니다 |
| Debian | `deb.debian.org` (`debian-debug`) | 서버 준비가 `/etc/apt/sources.list.d/debian-debug.list`를 추가합니다 |

### Windows 서버에서 나가는 접속

| 주소 | 용도 | 필요할 때 |
|---|---|---|
| `msdl.microsoft.com` | Microsoft 심볼 서버. 받은 심볼은 `C:\ProgramData\kdump-analyzer\symbols`에 캐시합니다 | 분석할 때(처음 한 번은 1~2분 동안 받음) |
| `go.microsoft.com`과 이 주소가 넘겨 주는 Microsoft 다운로드 서버 | Windows SDK 설치 관리자 받기 | 서버 준비의 디버거 설치 |

## 인터넷이 없는 환경

- **analyze-kdump 설치:** 웹 UI의 **웹 UI 버전 설치/업그레이드**는 웹 UI 컴퓨터의 파일을 SSH로 보내므로 서버에 인터넷이 필요 없습니다. 서버에서 직접 설치할 때는 저장소를 복사해 `install.sh`를 실행합니다.
- **무설치 실행:** 웹 UI가 분석 스크립트를 SSH로 보내 실행하므로 서버에 인터넷이 필요 없습니다.
- **패키지와 디버그 커널:** 사내 미러나 Satellite처럼 서버가 이미 쓰는 저장소에 `crash`와 debuginfo 패키지가 있으면 그것을 씁니다. 없으면 인터넷이 되는 같은 버전의 서버에서 패키지나 `vmlinux`를 받아 옮깁니다. [vmlinux 추가 방법](usage.md#vmlinux-추가-방법)을 봅니다.
- **LLM 분석:** 사내 OpenAI 호환 API가 있으면 기본 URL을 그 주소로 바꿉니다([설정 파일과 LLM](configuration.md)). LLM 분석을 쓰지 않으면 LLM 주소는 허용하지 않아도 됩니다.
- **Windows 심볼:** 사내 심볼 저장소를 `KDUMP_SYMBOL_PATH` 환경변수나 `-SymbolPath`로 지정합니다.
- **업데이트:** GitHub 접속이 막혀 있으면 화면의 업데이트 확인이 실패로 표시될 뿐 분석에는 영향이 없습니다. 새 버전은 저장소를 복사해 바꿉니다.
