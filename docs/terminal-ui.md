# 터미널 메뉴 UI

[README](../README.md) · [설치](install.md) · [요구 사항·네트워크](requirements.md) · [사용법](usage.md) · [설정·LLM](configuration.md) · [웹 UI](webui.md) · [Windows](windows.md) · [터미널 메뉴](terminal-ui.md) · [개발·검증](development.md)

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
| 업데이트 | 변경 내역을 보여주고, GitHub나 서버의 디렉터리에서 업데이트합니다. 예전 위치(`/opt/kdump-tools`)에 설치돼 있으면 **설치 위치 옮기기**로 `/opt/kdump-analyzer`로 옮깁니다. 현재·최신 버전은 메인 화면에 표시됩니다([버전 확인과 업데이트](install.md#버전-확인과-업데이트)) |

## 상황별 사용 방식

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

접속 서버 목록은 `/opt/kdump-analyzer/servers.conf`에 저장됩니다(`ANALYZE_KDUMP_SERVERS`로 변경 가능). 메뉴에서 관리하면 되고, 직접 편집할 때는 `servers.conf.sample` 형식을 따릅니다. 7번째 칸(분석 방식)을 생략하면 `auto`로 동작합니다.

```text
# 이름|접속대상(user@host)|포트|sudo 사용(yes/no)|원격 analyze-kdump 경로|crash 디렉터리|분석 방식
db01|ops@10.0.0.11|22|yes|/opt/kdump-analyzer/bin/analyze-kdump|/var/crash|auto
```

## 중앙 분석 서버 구성 (kdump 원격 전송)

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
- 분석 서버의 `VMLINUX_BASE`(`/opt/kdump-analyzer/vmlinux/<커널 버전>/vmlinux`)에 운영 서버 커널 버전별 vmlinux를 모아 둡니다.
