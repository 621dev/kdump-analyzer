# 개발과 검증

[README](../README.md) · [설치](install.md) · [사용법](usage.md) · [설정·LLM](configuration.md) · [웹 UI](webui.md) · [Windows](windows.md) · [터미널 메뉴](terminal-ui.md) · [개발·검증](development.md)

자동 테스트, CI, 테스트 VM에서 실제 덤프로 검증하는 방법입니다.

## 자동 테스트와 CI

실제 vmcore나 crash 없이 돌아가는 테스트입니다. GitHub에 push하거나 PR을 열면 GitHub Actions(`.github/workflows/ci.yml`)가 자동으로 실행합니다.

```bash
bash tests/run-tests.sh                      # analyze-kdump·메뉴 (Linux, bash)
python3 -m unittest discover -s tests -v     # 웹 UI·LLM 모듈 (Linux·Windows)
python3 tests/shellcheck-embedded.py         # 웹 UI 안의 원격 셸 스크립트 shellcheck
shellcheck bin/* install.sh tests/*.sh       # 셸 스크립트 정적 검사 (.shellcheckrc 적용)
```

- **`tests/run-tests.sh`**: 가짜 `crash`·`makedumpfile`과 ELF 머리만 있는 가짜 덤프를 임시 디렉터리에 만들고, 실제 `analyze-kdump`로 다음을 확인합니다.
  - 덤프 찾기(RHEL·Ubuntu 형식, 상위 디렉터리)
  - 장애 유형 판정과 근거 줄, 유형별 명령, taint 모듈 태스크 추리기, JSON 요약
  - flattened 덤프(그대로 읽기, 오래된 crash에서 변환, 변환 끔)
  - 아키텍처 불일치, vmlinux 없음 같은 오류 경로
  - 메뉴의 덤프 목록, 버전 비교, 접속 대상 검사
- **`tests/test_webui.py`**: 민감정보 마스킹, 리포트 축소, 업데이트 설정과 최신 버전 확인(네트워크는 흉내), 원격 시간 제한 래퍼, 서버 설치 묶음, 접속 대상 검사. `sh`·`setsid`가 없는 Windows에서는 해당 테스트를 건너뜁니다.
- **`tests/windows/test-windump.ps1`**: 가짜 cdb(`tests/windows/fake-cdb.ps1`)로 Windows 분석 스크립트의 버그체크 판정, 섹션, JSON 요약, 시간 초과, 오류 경로를 확인합니다. `test_webui.py`의 Windows 테스트는 웹 UI가 Windows 서버에 보내는 PowerShell 명령(설치, 분석, 삭제)을 이 PC에서 실제로 실행합니다.
- **CI 구성**: shellcheck와 pyflakes, Linux(Python 3.8·3.13)에서 두 테스트, Windows에서 웹 UI 테스트와 Windows 분석 스크립트 테스트(Windows PowerShell 5.1, PowerShell 7)를 돌립니다.

실제 crash로 하는 검증은 아래 테스트 VM 절차를 씁니다. Windows 서버는 [Windows 테스트 VM 준비](../tests/vm/windows-vm-setup.md)를 따라 Hyper-V VM에서 블루스크린을 내 확인합니다.

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

2026-11 Oracle Linux 8.10(UEK 커널 5.15.0-206, crash 9.0.2) VM에서도 SysRq-c로 만든 vmcore를 확인했습니다. 최소 설치라 `python3`가 없는 상태에서 platform-python(3.6)으로 JSON 요약과 서버 LLM 분석(가짜 LLM CLI)이 동작했고, 웹 UI 서버 준비가 Oracle debuginfo 저장소를 추가해 `kernel-uek` 디버그 커널을 설치했습니다. 이 VM은 `kdumpctl reset-crashkernel`이 없어 `kdump-vm-test.sh setup` 대신 웹 UI의 서버 준비로 kdump를 준비했습니다.
