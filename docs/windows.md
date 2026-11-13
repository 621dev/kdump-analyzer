# Windows 서버 (메모리 덤프)

[README](../README.md) · [설치](install.md) · [요구 사항·네트워크](requirements.md) · [사용법](usage.md) · [설정·LLM](configuration.md) · [웹 UI](webui.md) · [Windows](windows.md) · [터미널 메뉴](terminal-ui.md) · [개발·검증](development.md)

웹 UI에서 서버를 추가할 때 **운영체제**를 **Windows**로 고르면, 블루스크린 메모리 덤프(`MEMORY.DMP`, `Minidump\*.dmp`)를 Linux 서버와 같은 화면에서 분석합니다. 리포트와 JSON 요약이 Linux와 같은 형식이라 분석 기록, 요약 상자, LLM 분석을 그대로 씁니다.

## 서버에 필요한 것

자세한 준비 순서는 [Windows 테스트 VM 준비](../tests/vm/windows-vm-setup.md)에 있습니다.

- OpenSSH 서버와 관리자 계정의 SSH 키 접속(`administrators_authorized_keys`)
- Debugging Tools for Windows(`cdb.exe`). Windows SDK 설치 관리자에서 이 기능만 설치합니다.
- 덤프 설정(커널 메모리 덤프 등)과 페이지 파일
- **심볼:** 기본은 Microsoft 심볼 서버에서 받아 `C:\ProgramData\kdump-analyzer\symbols`에 캐시합니다. 인터넷이 막혀 있으면 사내 심볼 저장소를 `KDUMP_SYMBOL_PATH` 환경변수나 `-SymbolPath`로 지정합니다.

## 분석 스크립트

`winbin/analyze-windump.ps1`은 Windows PowerShell 5.1에서 동작합니다.

```powershell
C:\ProgramData\kdump-analyzer\bin\analyze-windump.ps1                 # 가장 최근 덤프
C:\ProgramData\kdump-analyzer\bin\analyze-windump.ps1 -Dump C:\Windows\MEMORY.DMP -TimeoutSec 1800
```

- **리포트:** `cdb`로 다음 명령을 실행해, 명령별 섹션으로 나눈 리포트(`kdump-report-*.txt`)와 JSON 요약을 `C:\ProgramData\kdump-analyzer\logs`에 만듭니다.
  - `!analyze -v`, `.bugcheck`, `vertarget`
  - `!thread`, `kv`, `!running -it`
  - `lm t n`, `!vm`, `!locks`
  - 프로세스 목록(`!process 0 0`)은 커널 메모리 덤프에서 1~2분이 걸려 기본에서 뺐습니다. `-ProcessList`를 주면 넣습니다.
- **판정:** 버그체크 코드로 장애 유형을 고르고, `!analyze -v`가 지목한 원인 후보 드라이버(`IMAGE_NAME`)를 근거로 남깁니다. NMI·수동 덤프는 일부러 낸 것이라, 지목된 드라이버(예: `GenuineIntel.sys`)를 원인 후보가 아닌 '처리 드라이버'로만 표시합니다.
- **종료 코드:**
  - `0`: 정상
  - `1`: 사용법·환경 오류(덤프나 cdb 없음)
  - `2`: cdb 실패, 시간 초과, 버그체크를 읽지 못함(리포트는 남김)

| 유형 | 버그체크 코드 |
|---|---|
| 커널 예외 (oops) | 0x0A, 0xD1, 0x50, 0x1E, 0x3B, 0x7E, 0x7F, 0x8E, 0x139 |
| 메모리 손상 | 0x19, 0xC2, 0xC5, 0x1A, 0x4E |
| CPU 지연 (soft/hard lockup) | • 0x133 DPC_WATCHDOG_VIOLATION<br>• 0x101 CLOCK_WATCHDOG_TIMEOUT |
| 응답 없음 (hung task) | • 0x9F DRIVER_POWER_STATE_FAILURE<br>• 0x9E USER_MODE_HEALTH_MONITOR |
| 핵심 프로세스 종료 | 0xEF, 0xF4 |
| 하드웨어 (MCE), NMI | • MCE: 0x124, 0x9C<br>• NMI: 0x80 |
| 수동 덤프 | 0xE2, 0xDEADDEAD, 0x1C8 |
| 디스크·부팅 | 0x7B, 0xED, 0x77, 0x7A |

### 실제 덤프로 확인한 결과

Windows Server 2025 평가판 VM에서 확인했습니다.

| 덤프 | 판정 | 근거 줄 | LLM 분석 (Codex) |
|---|---|---|---|
| NMI 주입 (`Debug-VM -InjectNonMaskableInterrupt`) | NMI `[nmi]` | `NMI_HARDWARE_FAILURE 0x80, 처리 드라이버: GenuineIntel.sys (NMI·수동 덤프라 원인이 아님)` | • 외부 NMI로 판정<br>• `GenuineIntel.sys`는 원인이 아니라고 설명 |
| 드라이버 오류 (Sysinternals NotMyFault `crash 0x01`) | 커널 예외 `[oops]` | `DRIVER_IRQL_NOT_LESS_OR_EQUAL 0xd1, 원인 후보: myfault.sys (myfault!nmf_fault_irql+35)` | `myfault.sys`가 IRQL 2에서 페이지 가능 메모리를 읽은 것으로 판정 |

분석 시간(커널 메모리 덤프):
- 심볼을 받아 둔 뒤 약 16초(드라이버 오류 덤프 384MB 기준). 처음에는 심볼을 받느라 1~2분이 더 걸립니다.
- 1.23.1까지는 프로세스 목록(`!process 0 0`) 때문에 약 1.5분이 걸렸습니다.
- 미니덤프는 약 20초입니다.

## 웹 UI에서

- **덤프 목록:** 서버 설정의 덤프 디렉터리(기본 `C:\Windows`)에서 `*.dmp`와 `Minidump\*.dmp`를 찾습니다. 블루스크린 뒤 재부팅 직후 Windows는 미니덤프를 0바이트로 만들어 두고 나중에 채우므로, 빈 파일은 목록과 분석 대상에서 뺍니다.
- **분석 방식:** Linux와 같습니다.
  - 원격 설치본 실행(`C:\ProgramData\kdump-analyzer\bin\analyze-windump.ps1`)
  - 무설치 실행(스크립트를 보내 임시로 실행하고 지움)
  - 자동 선택
- **설치·업그레이드·삭제:** 버전·업데이트 화면에서 합니다.
  - **웹 UI 버전:** 웹 UI 저장소의 `winbin/analyze-windump.ps1`을 보냅니다.
  - **GitHub 릴리스(또는 최신):** 웹 UI가 GitHub에서 업데이트 기준에 맞는 분석 스크립트를 받아 서버로 보냅니다. Linux와 달리 서버에 인터넷이 없어도 됩니다. 1.22.0보다 오래된 릴리스에는 Windows 스크립트가 없어 설치하지 않습니다.
  - **삭제:** **프로그램만**은 `bin`과 설치 정보를 지우고 로그(리포트)와 심볼 캐시는 남깁니다. **전부**는 `C:\ProgramData\kdump-analyzer`를 통째로 지웁니다.
- **서버 준비 탭:** 덤프 설정, 페이지 파일, cdb, 저장 공간, 관리자 권한을 점검하고, 빠진 항목을 골라 설치합니다.
  - **덤프 설정:** 덤프를 만들지 않게 돼 있으면 커널 메모리 덤프(`CrashDumpEnabled=2`)로 바꾸고 `AutoReboot=1`, `Overwrite=1`로 둡니다. 덤프 종류가 이미 정해져 있으면 그대로 둡니다. 재부팅해야 적용됩니다.
  - **페이지 파일:** '시스템이 관리하는 크기'로 바꿉니다. 재부팅해야 적용됩니다.
  - **디버거:** 서버가 Microsoft에서 Windows SDK 설치 관리자(`winsdksetup.exe`)를 받아, **Microsoft 서명을 확인한 뒤에만** 실행해 Debugging Tools for Windows만 설치합니다. 서버에 인터넷이 필요하고 몇 분 걸립니다. 인터넷이 막힌 서버는 [Windows 테스트 VM 준비](../tests/vm/windows-vm-setup.md)의 4단계처럼 설치 파일을 따로 옮겨 설치합니다.
  - **분석 스크립트:** 웹 UI 버전을 설치합니다.
- **LLM 분석:** Windows용 지시문(버그체크, 원인 드라이버, Driver Verifier 등)을 씁니다.
- **원격 명령 전달:**
  - 명령은 `powershell -EncodedCommand`로 보내 Windows `cmd.exe`의 따옴표 문제를 피합니다.
  - 분석 스크립트는 `scp`로 접속 계정의 홈 폴더에 보낸 뒤 옮기거나 실행하고 지웁니다. Windows OpenSSH를 거친 PowerShell은 큰 표준 입력에서 멈출 수 있기 때문입니다.
  - 리포트는 base64로 가져와 인코딩이 깨지지 않게 합니다.

## 아직 안 되는 것

- 터미널 메뉴(`analyze-kdump-ui`)에서 Windows 서버 분석
- 설치 위치 옮기기
