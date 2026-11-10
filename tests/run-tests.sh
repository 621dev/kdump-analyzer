#!/bin/bash
# kdump-analyzer 자동 테스트 (실제 vmcore·crash 없이 실행)
#
#   ./tests/run-tests.sh
#
# 가짜 crash·makedumpfile과 ELF 머리만 있는 가짜 덤프를 임시 디렉터리에 만들고,
# 실제 analyze-kdump로 덤프 찾기, 장애 유형 판정, 리포트 섹션, JSON 요약,
# flattened 덤프 처리, 아키텍처 확인을 검사합니다. analyze-kdump-ui의 덤프 목록과 버전 비교도 봅니다.
# 실제 crash로 하는 검증은 tests/vm/kdump-vm-test.sh(테스트 VM 전용)를 씁니다.

set -u

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
AK="$ROOT/bin/analyze-kdump"
KVER="5.14.0-test.el9.x86_64"
PASS=0
FAIL=0
FAILED=()

T=$(mktemp -d "${TMPDIR:-/tmp}/kdump-tools-test.XXXXXX")
trap 'rm -rf "$T"' EXIT

# ---------------------------------------------------------------- 검사 도우미

ok() { PASS=$((PASS + 1)); printf '  ok    %s\n' "$1"; }
ng() { FAIL=$((FAIL + 1)); FAILED+=("$1"); printf '  FAIL  %s\n' "$1"; [ -n "${2:-}" ] && printf '        %s\n' "$2"; }

check() {  # check <설명> <명령...>
    local desc="$1"
    shift
    if "$@"; then ok "$desc"; else ng "$desc"; fi
}

has() { grep -qF -- "$2" "$1"; }          # has <파일> <문자열>
lacks() { ! grep -qF -- "$2" "$1"; }      # lacks <파일> <문자열>

# ---------------------------------------------------------------- 가짜 도구와 덤프

mkdir -p "$T/fakebin" "$T/vmlinux/$KVER" "$T/reports"

cat > "$T/fakebin/crash" <<'EOF'
#!/bin/bash
# 테스트용 가짜 crash
sig() { head -c "$2" "$1" 2>/dev/null | tr -d '\000'; }
if [ "${1:-}" = "--osrelease" ]; then
    f="$2"
    if [ "$(sig "$f" 12)" = makedumpfile ]; then
        # 오래된 crash 흉내: flattened 형식을 읽지 못함
        [ "${FAKE_CRASH_NO_FLAT:-0}" = 1 ] && { echo "crash: $f: not a supported file format" >&2; exit 1; }
    elif [ "$(head -c 4 "$f" 2>/dev/null | od -An -tx1 | tr -d ' \n')" != 7f454c46 ]; then
        echo "crash: $f: not a supported file format" >&2
        exit 1
    fi
    echo "$FAKE_KVER"
    exit 0
fi
# 리포트 모드: 표준 입력의 "<명령> > <파일>" 줄마다 가짜 출력을 씁니다.
echo "crash fake 1.0"
while IFS= read -r line; do
    [ "$line" = quit ] && break
    if [[ "$line" == *" >> "* ]]; then cmd=${line% >> *}; out=${line##* >> }; mode=a
    elif [[ "$line" == *" > "* ]]; then cmd=${line% > *}; out=${line##* > }; mode=w
    else continue
    fi
    case "$cmd" in
        "mod -t") text=$'NAME         TAINTS\nkdump_fault  OE' ;;
        "foreach bt") text=$'PID: 100  TASK: ffff  CPU: 0  COMMAND: "kf_worker"\n #0 [ffff] kf_fn at ffffffffc0000000 [kdump_fault]\n\nPID: 1  TASK: ffff  CPU: 1  COMMAND: "systemd"\n #0 [ffff] schedule at ffffffff81000000' ;;
        *) text="fake output: $cmd" ;;
    esac
    if [ "$mode" = a ]; then printf '%s\n' "$text" >> "$out"; else printf '%s\n' "$text" > "$out"; fi
done
exit 0
EOF

cat > "$T/fakebin/makedumpfile" <<'EOF'
#!/bin/bash
# 테스트용 가짜 makedumpfile
#   --dump-dmesg <덤프> <출력>: FAKE_DMESG 파일을 복사
#   -R <출력> < flattened: 앞 16바이트(서명)를 버리고 나머지를 출력에 씀
case "${1:-}" in
    --dump-dmesg) [ -n "${FAKE_DMESG:-}" ] && cp "$FAKE_DMESG" "$3" ;;
    -R) tail -c +17 > "$2" ;;
    *) exit 1 ;;
esac
EOF
chmod +x "$T/fakebin/crash" "$T/fakebin/makedumpfile"

# make_elf <파일> <e_machine 2바이트(printf 8진수)>: e_machine만 맞춘 ELF 머리
make_elf() { { printf '\177ELF'; head -c 14 /dev/zero; printf '%b' "$2"; head -c 200 /dev/zero; } > "$1"; }
X86='\076\000'      # 62 = x86_64
ARM='\267\000'      # 183 = aarch64

make_elf "$T/vmlinux/$KVER/vmlinux" "$X86"

# make_flat <출력> <안에 넣을 덤프>: makedumpfile flattened 서명(16바이트) + 덤프
make_flat() { { printf 'makedumpfile'; head -c 4 /dev/zero; cat "$2"; } > "$1"; }

# 커널 로그 예시 (장애 유형별)
dmesg_hung() {
    cat <<'EOF'
[  100.000000] INFO: task kf_lock_waiter:2082 blocked for more than 30 seconds.
[  100.000100] Call Trace:
[  100.000200]  kf_wait+0x10/0x20 [kdump_fault]
[  100.000300]  mutex_lock+0x1a/0x40
[  130.000000] Kernel panic - not syncing: hung_task: blocked tasks
EOF
}
dmesg_oom() {
    cat <<'EOF'
[   10.000000] old_job invoked oom-killer: gfp_mask=0x0, order=0, oom_score_adj=0
[  500.000000] python3 invoked oom-killer: gfp_mask=0x140dca(GFP_HIGHUSER_MOVABLE), order=0, oom_score_adj=0
[  500.100000] Kernel panic - not syncing: System is deadlocked on memory
EOF
}
dmesg_oops() {
    cat <<'EOF'
[  200.000000] BUG: kernel NULL pointer dereference, address: 0000000000000000
[  200.000100] RIP: 0010:kf_null_fn+0x15/0x30 [kdump_fault]
[  200.000200] Kernel panic - not syncing: Fatal exception
EOF
}
dmesg_softlockup() {
    cat <<'EOF'
[      C0] watchdog: BUG: soft lockup - CPU#0 stuck for 26s! [kf_spin:6406]
[      C0] Kernel panic - not syncing: softlockup: hung tasks
EOF
}
dmesg_sysrq() {
    cat <<'EOF'
[  300.000000] sysrq: Trigger a crash
[  300.000100] Kernel panic - not syncing: sysrq triggered crash
EOF
}

# run_ak <출력 접두사> [환경변수=값...] -- <analyze-kdump 인자...>
# 결과: $T/<접두사>.out(표준 출력+오류), $T/<접두사>.rc, $T/<접두사>.report(리포트 파일 경로)
run_ak() {
    local name="$1" rc
    shift
    local -a envs=()
    while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do envs+=("$1"); shift; done
    shift
    env -i PATH="$T/fakebin:/usr/bin:/bin:/usr/sbin:/sbin" HOME="$T" TMPDIR="$T" LANG=C.UTF-8 \
        ANALYZE_KDUMP_CONF=/nonexistent VMLINUX_BASE="$T/vmlinux" REPORT_DIR="$T/reports" \
        FAKE_KVER="$KVER" "${envs[@]}" bash "$AK" "$@" > "$T/$name.out" 2>&1
    rc=$?
    echo "$rc" > "$T/$name.rc"
    sed -n 's/^report:  //p' "$T/$name.out" | tail -n 1 > "$T/$name.report"
    return 0
}
rc_of() { cat "$T/$1.rc"; }
report_of() { cat "$T/$1.report"; }

# ---------------------------------------------------------------- analyze-kdump

echo "analyze-kdump"

check "--version 출력" bash -c "bash '$AK' --version | grep -q '^analyze-kdump '"

# RHEL 형식: <디렉터리>/vmcore + vmcore-dmesg.txt
mkdir -p "$T/crash/127.0.0.1-2026-11-06-10:00:00"
D="$T/crash/127.0.0.1-2026-11-06-10:00:00"
make_elf "$D/vmcore" "$X86"
dmesg_hung > "$D/vmcore-dmesg.txt"
run_ak hung -- -r "$D/"
R=$(report_of hung)
check "hung task: 종료 코드 0" [ "$(rc_of hung)" = 0 ]
check "hung task: 리포트 생성" [ -s "$R" ]
check "hung task: 유형 판정" has "$R" "[hung_task]"
check "hung task: 근거 로그" has "$R" "evidence:  INFO: task kf_lock_waiter:2082 blocked for more than 30 seconds."
check "hung task: 덤프 경로에 // 없음" has "$R" "vmcore:    $D/vmcore"
check "hung task: 유형별 명령(ps -m | grep UN)" has "$R" "===== crash> ps -m | grep UN ====="
check "hung task: 기본 섹션(bt -a)" has "$R" "===== crash> bt -a ====="
check "hung task: 가짜 crash 출력이 섹션에 들어감" has "$R" "fake output: sys"
check "hung task: taint 모듈 태스크만 추림" has "$R" 'COMMAND: "kf_worker"'

# 서버의 LLM 분석(--llm-report): 가짜 Claude Code CLI가 받은 입력을 확인하고 분석을 돌려줍니다.
# 1.18.3~1.24.3에서는 python3 인자에 공백이 빠져(python3 -"<리포트>") 이 경로가 항상 실패했습니다.
cat > "$T/fakebin/claude" <<'EOF'
#!/bin/bash
input=$(cat)
case "$input" in
    *"NODENAME"*|*"hung_task"*|*"fake output"*) echo "판정: 가짜 LLM 분석 (입력 ${#input}자)" ;;
    *) echo "입력이 비어 있음"; exit 3 ;;
esac
EOF
chmod +x "$T/fakebin/claude"
run_ak llm LLM_PROVIDER=claude-code LLM_CLI_PATH="$T/fakebin/claude" LLM_TIMEOUT=30 -- --llm-report "$R"
A=$(sed -n 's/^analysis: //p' "$T/llm.out" | tail -n 1)
check "LLM 분석(--llm-report): 종료 코드 0" [ "$(rc_of llm)" = 0 ]
check "LLM 분석: 분석 파일에 CLI 응답" has "${A:-/nonexistent}" "판정: 가짜 LLM 분석"
check "LLM 분석: 건너뜀 안내 없음" lacks "${A:-/nonexistent}" "LLM 분석을 건너뜁니다"
check "hung task: taint와 무관한 태스크는 뺌" lacks "$R" 'COMMAND: "systemd"'
check "hung task: 모듈 심볼 섹션" has "$R" "===== 모듈 심볼 ====="
J="${R%.txt}.json"
check "JSON 요약 생성" [ -s "$J" ]
if command -v python3 >/dev/null 2>&1; then
    check "JSON: 올바른 형식과 유형" python3 -c "
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
assert d['crash_type']['type'] == 'hung_task', d['crash_type']
assert d['kernel'] == sys.argv[2]
assert any(s['title'] == 'crash> bt -a' and s['lines'] > 0 for s in d['sections']), d['sections']
" "$J" "$KVER"
fi

# OOM: 여러 OOM 중 마지막 줄을 근거로
mkdir -p "$T/crash/oom"
make_elf "$T/crash/oom/vmcore" "$X86"
dmesg_oom > "$T/crash/oom/vmcore-dmesg.txt"
run_ak oom -- -r "$T/crash/oom"
R=$(report_of oom)
check "OOM: 유형 판정" has "$R" "[oom]"
check "OOM: 마지막 oom-killer 줄을 근거로" has "$R" "evidence:  python3 invoked oom-killer"
check "OOM: 유형별 명령(kmem -V)" has "$R" "===== crash> kmem -V ====="

# oops: RIP으로 문제 지점 디스어셈블
mkdir -p "$T/crash/oops"
make_elf "$T/crash/oops/vmcore" "$X86"
dmesg_oops > "$T/crash/oops/vmcore-dmesg.txt"
run_ak oops -- -r "$T/crash/oops"
R=$(report_of oops)
check "oops: 유형 판정" has "$R" "[oops]"
check "oops: 첫 오류 줄을 근거로" has "$R" "evidence:  BUG: kernel NULL pointer dereference"
check "oops: 문제 지점 디스어셈블" has "$R" "===== crash> dis -rl kf_null_fn+0x15 ====="
check "oops: 소스 줄 bt -l" has "$R" "===== crash> bt -l ====="

# Ubuntu·Debian 형식: <시각>/dump.<시각> + dmesg.<시각>, makedumpfile로 꺼낸 로그의 [ C0] 접두사
mkdir -p "$T/crash/202611060456"
make_elf "$T/crash/202611060456/dump.202611060456" "$X86"
dmesg_softlockup > "$T/crash/202611060456/dmesg.202611060456"
run_ak ubuntu -- -r "$T/crash/202611060456"
R=$(report_of ubuntu)
check "Ubuntu 덤프: 종료 코드 0" [ "$(rc_of ubuntu)" = 0 ]
check "Ubuntu 덤프: dump.<시각> 사용" has "$R" "vmcore:    $T/crash/202611060456/dump.202611060456"
check "Ubuntu 덤프: dmesg.<시각> 사용" has "$R" "dmesg:     $T/crash/202611060456/dmesg.202611060456"
check "soft lockup: 유형 판정" has "$R" "[soft_lockup]"
check "soft lockup: [ C0] 접두사 제거" has "$R" "evidence:  watchdog: BUG: soft lockup - CPU#0 stuck for 26s!"
check "soft lockup: 유형별 명령(runq -t)" has "$R" "===== crash> runq -t ====="

# 커널 로그 파일이 없으면 makedumpfile --dump-dmesg로 꺼냄
mkdir -p "$T/crash/nodmesg"
make_elf "$T/crash/nodmesg/vmcore" "$X86"
dmesg_sysrq > "$T/sysrq.txt"
run_ak nodmesg FAKE_DMESG="$T/sysrq.txt" -- -r "$T/crash/nodmesg"
R=$(report_of nodmesg)
check "로그 파일 없음: makedumpfile로 꺼내 판정" has "$R" "[sysrq]"
check "로그 파일 없음: 임시 경로를 남기지 않음" has "$R" "(vmcore에서 makedumpfile로 추출)"

# 커널 로그를 아예 못 구함
mkdir -p "$T/crash/unknown"
make_elf "$T/crash/unknown/vmcore" "$X86"
run_ak unknown -- -r "$T/crash/unknown"
check "로그 없음: 판단 불가로 계속 진행" has "$(report_of unknown)" "판단 불가 (커널 로그를 찾지 못함)"

# 오래된 커널(RHEL 7의 3.10 등) 로그 형식
# old_case <이름> <기대 유형>: 표준 입력의 로그로 덤프를 만들어 분석하고 유형을 확인
old_case() {
    mkdir -p "$T/old/$1"
    make_elf "$T/old/$1/vmcore" "$X86"
    cat > "$T/old/$1/vmcore-dmesg.txt"
    run_ak "old-$1" -- -r "$T/old/$1"
    check "오래된 커널 $1: 유형 판정" has "$(report_of "old-$1")" "[$2]"
}
old_case sysrq sysrq <<'EOF'
[  300.000000] SysRq : Trigger a crash
[  300.000100] BUG: unable to handle kernel NULL pointer dereference at           (null)
[  300.000200] IP: [<ffffffff813f3b06>] sysrq_handle_crash+0x16/0x20
[  300.000300] RIP: 0010:[<ffffffff813f3b06>]  [<ffffffff813f3b06>] sysrq_handle_crash+0x16/0x20
[  300.000400] Kernel panic - not syncing: Fatal exception
EOF
old_case oops oops <<'EOF'
[  200.000000] BUG: unable to handle kernel NULL pointer dereference at 0000000000000008
[  200.000100] IP: [<ffffffffc05a1015>] kf_null_fn+0x15/0x30 [kdump_fault]
[  200.000200] RIP: 0010:[<ffffffffc05a1015>]  [<ffffffffc05a1015>] kf_null_fn+0x15/0x30 [kdump_fault]
[  200.000300] Kernel panic - not syncing: Fatal exception
EOF
check "오래된 커널 oops: 첫 오류 줄을 근거로" has "$(report_of old-oops)" "evidence:  BUG: unable to handle kernel NULL pointer dereference"
check "오래된 커널 oops: RIP 형식에서 디스어셈블 위치" has "$(report_of old-oops)" "===== crash> dis -rl kf_null_fn+0x15 ====="
old_case softlockup soft_lockup <<'EOF'
[  400.000000] BUG: soft lockup - CPU#1 stuck for 22s! [kf_spin:1234]
[  400.000100] Kernel panic - not syncing: softlockup: hung tasks
EOF
old_case hardlockup hard_lockup <<'EOF'
[  500.000000] NMI watchdog: Watchdog detected hard LOCKUP on cpu 2
[  500.000100] Kernel panic - not syncing: Hard LOCKUP
EOF
old_case hung hung_task <<'EOF'
[  600.000000] INFO: task kf_lock_waiter:2082 blocked for more than 120 seconds.
[  600.000100] "echo 0 > /proc/sys/kernel/hung_task_timeout_secs" disables this message.
[  720.000000] Kernel panic - not syncing: hung_task: blocked tasks
EOF
old_case oom oom <<'EOF'
[  700.000000] java invoked oom-killer: gfp_mask=0x280da, order=0, oom_score_adj=0
[  700.000100] Kernel panic - not syncing: Out of memory: system-wide panic_on_oom is enabled
EOF

# 벤더 커널(Oracle UEK): vmlinux가 없으면 kernel-uek debuginfo 설치를 안내
run_ak uek FAKE_KVER=5.15.0-200.131.27.el8uek.x86_64 VMLINUX_BASE="$T/none" -- -r "$T/old/oops"
check "UEK: vmlinux 없음 종료 코드 1" [ "$(rc_of uek)" = 1 ]
check "UEK: kernel-uek debuginfo 안내" has "$T/uek.out" "kernel-uek-5.15.0-200.131.27.el8uek.x86_64"

# 기능 끄기
run_ak off REPORT_TYPE_COMMANDS=0 REPORT_JSON=0 REPORT_MODULE_SYMBOLS=off -- -r "$D"
R=$(report_of off)
check "끄기: 유형별 명령 없음" lacks "$R" "ps -m | grep UN"
check "끄기: JSON 없음" [ ! -e "${R%.txt}.json" ]
check "끄기: 모듈 심볼 끔 표시" has "$R" "끔 (REPORT_MODULE_SYMBOLS=off)"

# 상위 디렉터리를 주면 가장 최근 덤프
touch -d '2020-01-01' "$T/crash"/*/vmcore "$T/crash"/*/dump.* 2>/dev/null
touch "$T/crash/oops/vmcore"
run_ak parent -- -r "$T/crash/"
check "상위 디렉터리: 가장 최근 덤프 선택" has "$T/parent.out" "vmcore:  $T/crash/oops/vmcore"

# 아키텍처가 다른 vmlinux
mkdir -p "$T/vmlinux-arm/$KVER"
make_elf "$T/vmlinux-arm/$KVER/vmlinux" "$ARM"
run_ak arch VMLINUX_BASE="$T/vmlinux-arm" -- -r "$D"
check "아키텍처 불일치: 종료 코드 1" [ "$(rc_of arch)" = 1 ]
check "아키텍처 불일치: 이유 안내" has "$T/arch.out" "vmcore x86_64, vmlinux aarch64"

# vmlinux 없음
run_ak novmlinux VMLINUX_BASE="$T/none" -- -r "$D"
check "vmlinux 없음: 종료 코드 1" [ "$(rc_of novmlinux)" = 1 ]
check "vmlinux 없음: 찾아본 경로 안내" has "$T/novmlinux.out" "$T/none/$KVER/vmlinux"

# 덤프 없음, 덤프가 아닌 파일
mkdir -p "$T/empty/sub"
run_ak empty -- -r "$T/empty"
check "덤프 없음: 안내 문구" has "$T/empty.out" "덤프 파일(vmcore, vmcore.flat 또는 dump.<시각>)을 찾을 수 없습니다"
echo hello > "$T/notdump"
run_ak notdump -- -r "$T/notdump"
check "덤프가 아닌 파일: 종료 코드 1" [ "$(rc_of notdump)" = 1 ]
check "덤프가 아닌 파일: 커널 버전 오류" has "$T/notdump.out" "vmcore 커널 버전을 확인할 수 없습니다."

# flattened 형식: crash가 바로 읽으면 변환하지 않음
mkdir -p "$T/flat1"
make_elf "$T/inner" "$X86"
make_flat "$T/flat1/vmcore.flat" "$T/inner"
dmesg_sysrq > "$T/flat1/vmcore-dmesg.txt"
run_ak flat1 -- -r "$T/flat1"
check "flattened: crash가 읽으면 그대로 분석" [ "$(rc_of flat1)" = 0 ]
check "flattened: 변환본을 만들지 않음" [ ! -e "$T/flat1/vmcore" ]
check "flattened: 리포트에 원본 경로" has "$(report_of flat1)" "vmcore:    $T/flat1/vmcore.flat"

# 오래된 crash: 같은 디렉터리의 vmcore로 변환
mkdir -p "$T/flat2"
make_flat "$T/flat2/vmcore.flat" "$T/inner"
dmesg_sysrq > "$T/flat2/vmcore-dmesg.txt"
run_ak flat2 FAKE_CRASH_NO_FLAT=1 -- -r "$T/flat2"
check "오래된 crash: 변환 후 분석" [ "$(rc_of flat2)" = 0 ]
check "오래된 crash: 변환본 vmcore 생성" cmp -s "$T/flat2/vmcore" "$T/inner"
check "오래된 crash: 리포트에 변환 원본" has "$(report_of flat2)" "converted: $T/flat2/vmcore.flat"
check "오래된 crash: 원본 커널 로그 사용" has "$(report_of flat2)" "dmesg:     $T/flat2/vmcore-dmesg.txt"
check "오래된 crash: 임시 파일 정리" bash -c "! ls '$T/flat2'/*.converting.* >/dev/null 2>&1"

# 오래된 crash + 변환 끔
mkdir -p "$T/flat3"
make_flat "$T/flat3/vmcore.flat" "$T/inner"
run_ak flat3 FAKE_CRASH_NO_FLAT=1 FLAT_CONVERT=0 -- -r "$T/flat3"
check "변환 끔: 종료 코드 1" [ "$(rc_of flat3)" = 1 ]
check "변환 끔: 변환 명령 안내" has "$T/flat3.out" "makedumpfile -R $T/flat3/vmcore < $T/flat3/vmcore.flat"

# 기본 경로는 install.sh로 설치한 위치(.install-info)를 따라감
INST="$T/inst/kdump-analyzer"
mkdir -p "$INST/bin" "$INST/vmlinux/$KVER"
cp "$AK" "$INST/bin/analyze-kdump"
echo "VERSION=test" > "$INST/.install-info"
make_elf "$INST/vmlinux/$KVER/vmlinux" "$X86"
env -i PATH="$T/fakebin:/usr/bin:/bin" HOME="$T" TMPDIR="$T" LANG=C.UTF-8 FAKE_KVER="$KVER" \
    bash "$INST/bin/analyze-kdump" -r "$D" > "$T/inst.out" 2>&1
check "설치 위치 기준: vmlinux를 설치 위치에서 찾음" has "$T/inst.out" "vmlinux: $INST/vmlinux/$KVER/vmlinux"
check "설치 위치 기준: 리포트를 설치 위치 logs에 저장" has "$T/inst.out" "report:  $INST/logs/kdump-report-"
rm -f "$INST/.install-info"
env -i PATH="$T/fakebin:/usr/bin:/bin" HOME="$T" TMPDIR="$T" LANG=C.UTF-8 FAKE_KVER="$KVER" \
    bash "$INST/bin/analyze-kdump" -r "$D" > "$T/inst2.out" 2>&1
# 설치 정보가 없으면 기본 설치 위치(/opt/kdump-analyzer), 거기 없고 예전 위치에만 설치돼 있으면 예전 위치
if [ ! -f /opt/kdump-analyzer/.install-info ] && [ -f /opt/kdump-tools/.install-info ]; then
    WANT_BASE=/opt/kdump-tools
else
    WANT_BASE=/opt/kdump-analyzer
fi
check "설치 정보 없으면 기본 설치 위치 기준 ($WANT_BASE)" has "$T/inst2.out" "$WANT_BASE/vmlinux/$KVER/vmlinux"

# 작업이 끝나면 임시 디렉터리를 남기지 않음
check "임시 작업 디렉터리 정리" bash -c "! ls -d '$T'/analyze-kdump.* >/dev/null 2>&1"

# ---------------------------------------------------------------- analyze-kdump-ui

echo "analyze-kdump-ui"

# 메뉴 스크립트는 main 없이 함수만 읽어 오도록 되어 있습니다. 테스트 도우미와 섞이지 않게 하위 셸에서 읽습니다.
ui() { bash -c 'source "$1"; shift; "$@"' ui "$ROOT/bin/analyze-kdump-ui" "$@"; }

check "version_gt 1.10.0 > 1.9.0" ui version_gt 1.10.0 1.9.0
check "version_gt 1.9.0 > 1.10.0 아님" bash -c "! (source '$ROOT/bin/analyze-kdump-ui'; version_gt 1.9.0 1.10.0)"
check "version_gt 같은 버전은 아님" bash -c "! (source '$ROOT/bin/analyze-kdump-ui'; version_gt 1.18.2 1.18.2)"
check "접속 대상 user@host 허용" ui valid_ssh_target "tester@10.0.0.1"
check "접속 대상 '-'로 시작하면 거부" bash -c "! (source '$ROOT/bin/analyze-kdump-ui'; valid_ssh_target '-oProxyCommand=id')"
check "접속 대상 공백 있으면 거부" bash -c "! (source '$ROOT/bin/analyze-kdump-ui'; valid_ssh_target 'a b')"
DUMP_LIST_SH=$(bash -c 'source "$1"; printf "%s" "$DUMP_LIST_SH"' ui "$ROOT/bin/analyze-kdump-ui")

# 덤프 목록: 변환본이 있으면 원본은 숨기고, 저장 중인 파일과 apport 보고서는 넣지 않음
L="$T/list"
mkdir -p "$L/a" "$L/b" "$L/c" "$L/d" "$L/e"
: > "$L/a/vmcore"
: > "$L/b/vmcore.flat"
: > "$L/c/vmcore.flat"; : > "$L/c/vmcore"
: > "$L/d/dump.202611060456"
: > "$L/e/dump-incomplete"
: > "$L/linux-image-7.0.0-42-generic-202611060456.crash"
LIST=$(sh -c "$DUMP_LIST_SH" sh "$L" | awk '{print $3}' | sed "s#^$L/##" | sort | tr '\n' ' ')
check "덤프 목록: vmcore, vmcore.flat, dump.<시각>" [ "$LIST" = "a/vmcore b/vmcore.flat c/vmcore d/dump.202611060456 " ]

# ---------------------------------------------------------------- 결과

echo
echo "통과 $PASS, 실패 $FAIL"
if [ "$FAIL" -gt 0 ]; then
    printf '  실패: %s\n' "${FAILED[@]}"
    exit 1
fi
