#!/bin/bash
# 테스트용 RHEL 계열 VM에서 실제 vmcore를 만들어 analyze-kdump를 검증합니다.
# 운영 서버에서 실행하지 마세요. panic 단계는 커널을 즉시 패닉시킵니다.
#
# 사용 순서 (root):
#   1) ./kdump-vm-test.sh setup          # kdump 설치/설정. crashkernel이 새로 잡히면 재부팅
#   2) ./kdump-vm-test.sh panic          # sysrq로 패닉 -> 재부팅 후 /var/crash에 vmcore 생성
#      ./kdump-vm-test.sh panic oom      # (선택) OOM 패닉 덤프
#   3) ./kdump-vm-test.sh verify         # debuginfo 설치 후 analyze-kdump -r 결과 점검
#      LLM_API_KEY=... LLM_PROVIDER=... LLM_MODEL=... ./kdump-vm-test.sh verify --llm
#      LLM_PROVIDER=claude-code ./kdump-vm-test.sh verify --llm   # 구독 CLI (root로 로그인 필요)
#
# 환경변수:
#   TOOL_DIR    analyze-kdump 저장소 위치 (기본 /opt/kdump-tools-test, 없으면 clone)
#   TOOL_REPO   clone할 저장소 (기본 https://github.com/621dev/kdump-analyzer.git)
#   TOOL_BRANCH clone할 브랜치 (기본 fix/robustness-and-llm)
set -e

TOOL_DIR="${TOOL_DIR:-/opt/kdump-tools-test}"
TOOL_REPO="${TOOL_REPO:-https://github.com/621dev/kdump-analyzer.git}"
TOOL_BRANCH="${TOOL_BRANCH:-fix/robustness-and-llm}"

die() {
    echo "오류: $*" >&2
    exit 1
}

require_root() {
    [ "$(id -u)" -eq 0 ] || die "root로 실행해 주세요."
}

crashkernel_reserved() {
    [ -r /sys/kernel/kexec_crash_size ] && [ "$(cat /sys/kernel/kexec_crash_size)" -gt 0 ]
}

# crash는 RHEL 9 커널 디버그 정보를 읽을 때 약 1.5GB를 사용하므로 메모리가 작은 VM에는 swap을 추가합니다.
ensure_swap() {
    local mem_mb

    mem_mb=$(awk '/^MemTotal:/ { print int($2 / 1024) }' /proc/meminfo)
    if [ "$mem_mb" -ge 3072 ] || [ -n "$(swapon --noheadings)" ]; then
        return
    fi

    echo "메모리가 ${mem_mb}MB라 crash 분석용 4GB swap 파일(/swapfile)을 만듭니다."
    if [ ! -f /swapfile ]; then
        fallocate -l 4G /swapfile
        chmod 600 /swapfile
        mkswap /swapfile > /dev/null
    fi
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap defaults 0 0' >> /etc/fstab
}

cmd_setup() {
    require_root
    dnf install -y kexec-tools crash git python3 curl dnf-plugins-core
    ensure_swap

    if ! crashkernel_reserved; then
        kdumpctl reset-crashkernel
        systemctl enable kdump
        echo
        echo "crashkernel 메모리를 새로 설정했습니다. 재부팅한 뒤 다시 'setup'을 실행해 주세요."
        return
    fi

    systemctl enable kdump
    systemctl restart kdump
    kdumpctl status
    echo
    echo "kdump 준비 완료. 다음 단계: $0 panic"
}

cmd_panic() {
    local mode="${1:-sysrq}" answer

    require_root
    crashkernel_reserved || die "crashkernel이 예약되지 않았습니다. 먼저 'setup'을 실행하고 재부팅해 주세요."
    kdumpctl status 2>&1 | grep -qi operational || die "kdump가 동작 중이 아닙니다. 'kdumpctl status'를 확인해 주세요."

    echo "이 시스템을 지금 패닉시킵니다(mode=$mode). 테스트 VM이 맞습니까? [yes/N]"
    read -r answer
    [ "$answer" = "yes" ] || die "취소했습니다."

    sync
    case "$mode" in
        sysrq)
            echo 1 > /proc/sys/kernel/sysrq
            echo c > /proc/sysrq-trigger
            ;;
        oom)
            swapoff -a || true
            sysctl -w vm.panic_on_oom=1
            python3 -c 'chunks = []
while True:
    chunks.append(bytearray(64 * 1024 * 1024))'
            ;;
        *)
            die "알 수 없는 mode입니다: $mode (sysrq|oom)"
            ;;
    esac
}

ensure_tool() {
    if [ ! -x "$TOOL_DIR/bin/analyze-kdump" ]; then
        git clone --branch "$TOOL_BRANCH" "$TOOL_REPO" "$TOOL_DIR"
    fi
    echo "tool:    $TOOL_DIR ($(git -C "$TOOL_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null) $(git -C "$TOOL_DIR" rev-parse --short HEAD 2>/dev/null))"
}

# 리포트의 "===== crash> <명령> =====" 섹션마다 내용이 있는지 확인합니다.
check_sections() {
    awk '
        /^===== crash> .* =====$/ { flush(); name = $0; sub(/^===== crash> /, "", name); sub(/ =====$/, "", name); lines = 0; in_section = 1; next }
        /^===== / { flush(); in_section = 0; next }
        in_section && NF > 0 { lines++ }
        END { flush(); if (total == 0) { print "FAIL  섹션이 하나도 없습니다"; exit 1 } exit failed }
        function flush() {
            if (!in_section) return
            total++
            if (lines > 0) { printf "OK    %-12s %6d lines\n", name, lines }
            else { printf "FAIL  %-12s (비어 있음)\n", name; failed = 1 }
        }
    ' "$1"
}

cmd_verify() {
    local use_llm=0 vmcore kver out status report analysis result=0

    require_root
    [ "${1:-}" = "--llm" ] && use_llm=1

    vmcore=$(ls -1td /var/crash/*/vmcore 2>/dev/null | head -n 1)
    [ -n "$vmcore" ] || die "/var/crash에서 vmcore를 찾지 못했습니다. 'panic' 단계를 먼저 실행해 주세요."
    kver=$(crash --osrelease "$vmcore" | tail -1)
    echo "vmcore:  $vmcore"
    echo "kernel:  $kver"

    if [ ! -f "/usr/lib/debug/lib/modules/$kver/vmlinux" ]; then
        dnf debuginfo-install -y "kernel-$kver"
    fi
    ensure_tool

    out=$(mktemp -d /var/tmp/kdump-verify.XXXXXX)
    echo
    echo "===== analyze-kdump -r 실행 ====="
    # VMLINUX_BASE를 비워 두어 debuginfo 설치 경로 자동 탐색도 함께 검증합니다.
    status=0
    ANALYZE_KDUMP_CONF=/nonexistent VMLINUX_BASE=/nonexistent REPORT_DIR="$out" \
        "$TOOL_DIR/bin/analyze-kdump" -r "$vmcore" || status=$?

    echo
    echo "===== 점검 결과 ====="
    if [ "$status" -eq 0 ]; then
        echo "OK    종료 코드 0"
    else
        echo "FAIL  종료 코드 $status"
        result=1
    fi

    report=$(ls -1t "$out"/kdump-report-*.txt 2>/dev/null | head -n 1)
    if [ -z "$report" ]; then
        echo "FAIL  리포트 파일이 없습니다"
        exit 1
    fi
    check_sections "$report" || result=1

    if grep -q "do not match" "$report"; then
        echo "FAIL  vmlinux와 vmcore가 맞지 않습니다"
        result=1
    fi

    echo
    echo "----- 패닉 정보 (sys) -----"
    grep -E '^\s*(PANIC|RELEASE|NODENAME):' "$report" || true
    echo "----- crash 실행 로그의 경고/오류 (참고) -----"
    sed -n '/^===== crash 실행 로그/,$p' "$report" | grep -iE 'warning|error|invalid|crash:' | head -20 || true

    if [ "$use_llm" -eq 1 ]; then
        echo
        echo "===== analyze-kdump -llm 실행 ====="
        case "${LLM_PROVIDER:-}" in
            claude-code|codex)
                # 구독 CLI는 실행 사용자(root)로 로그인되어 있어야 합니다.
                ;;
            *)
                [ -n "${LLM_API_KEY:-}${LLM_API_KEY_FILE:-}" ] || die "LLM_API_KEY 또는 LLM_API_KEY_FILE을 설정해 주세요."
                ;;
        esac
        status=0
        ANALYZE_KDUMP_CONF=/nonexistent VMLINUX_BASE=/nonexistent REPORT_DIR="$out" \
            "$TOOL_DIR/bin/analyze-kdump" -llm "$vmcore" || status=$?
        analysis=$(ls -1t "$out"/kdump-analysis-*.txt 2>/dev/null | head -n 1)
        if [ "$status" -eq 0 ] && [ -n "$analysis" ] && [ "$(sed '1,/^$/d' "$analysis" | grep -c .)" -gt 0 ]; then
            echo "OK    LLM 분석 생성: $analysis"
        else
            echo "FAIL  LLM 분석 실패(종료 코드 $status): ${analysis:-분석 파일 없음}"
            result=1
        fi
    fi

    echo
    echo "결과 파일: $out"
    if [ "$result" -eq 0 ]; then
        echo "PASS"
    else
        echo "FAIL"
    fi
    return "$result"
}

case "${1:-}" in
    setup)
        cmd_setup
        ;;
    panic)
        shift
        cmd_panic "$@"
        ;;
    verify)
        shift
        cmd_verify "$@"
        ;;
    *)
        sed -n '2,16p' "$0"
        exit 1
        ;;
esac
