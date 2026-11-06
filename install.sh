#!/bin/bash
# kdump-tools 설치 스크립트
#
# 파일을 설치 디렉터리(기본 /opt/kdump-tools)에 복사하고, bin/의 명령을 PATH에 등록합니다.
#   sudo ./install.sh                # 설치 또는 업데이트
#   sudo ./install.sh --uninstall    # 등록한 명령 해제 (설치 디렉터리의 설정·로그·vmlinux는 남김)
#
# 옵션:
#   --prefix DIR    설치 디렉터리 (기본 /opt/kdump-tools)
#   --bin-dir DIR   명령을 등록할 디렉터리 (기본 /usr/sbin)
#                   RHEL 계열 sudo의 secure_path에는 /usr/local/* 가 없어서 기본값을 /usr/sbin으로 둡니다.
#   --commit SHA    설치 정보에 기록할 커밋 (git 저장소가 아닌 원본에서 설치할 때, 메뉴 업데이트가 사용)
#   --source TEXT   설치 정보에 기록할 원본 설명
set -e

SRC_DIR=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
PREFIX="/opt/kdump-tools"
BIN_DIR="/usr/sbin"
COMPLETION_DIR="/etc/bash_completion.d"
COMPLETION_NAME="kdump-tools"
ACTION="install"
SKIPPED=0
COMMIT=""
SOURCE_LABEL=""

usage() {
    sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
}

die() {
    echo "오류: $*" >&2
    exit 1
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix)
            [ -n "${2:-}" ] || die "--prefix에는 디렉터리가 필요합니다."
            PREFIX="$2"
            shift 2
            ;;
        --bin-dir)
            [ -n "${2:-}" ] || die "--bin-dir에는 디렉터리가 필요합니다."
            BIN_DIR="$2"
            shift 2
            ;;
        --commit)
            [ -n "${2:-}" ] || die "--commit에는 커밋 값이 필요합니다."
            COMMIT="$2"
            shift 2
            ;;
        --source)
            [ -n "${2:-}" ] || die "--source에는 설명이 필요합니다."
            SOURCE_LABEL="$2"
            shift 2
            ;;
        --uninstall)
            ACTION="uninstall"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage
            die "알 수 없는 옵션입니다: $1"
            ;;
    esac
done

[ "$(id -u)" -eq 0 ] || die "root로 실행해 주세요. (sudo $0)"

install_files() {
    local f

    if [ "$(readlink -f "$SRC_DIR")" = "$(readlink -f "$PREFIX" 2>/dev/null)" ]; then
        echo "설치 디렉터리에서 실행 중이므로 파일 복사는 건너뜁니다: $PREFIX"
    else
        echo "파일 복사: $SRC_DIR -> $PREFIX"
        mkdir -p "$PREFIX/bin"
        install -m 755 "$SRC_DIR"/bin/* "$PREFIX/bin/"
        for f in README.md CHANGELOG.md LICENSE VERSION analyze-kdump.conf.sample servers.conf.sample; do
            if [ -f "$SRC_DIR/$f" ]; then
                install -m 644 "$SRC_DIR/$f" "$PREFIX/$f"
            fi
        done
        # 저장소 폴더를 지워도 업데이트·해제를 할 수 있도록 설치 스크립트도 함께 둡니다.
        install -m 755 "$SRC_DIR/install.sh" "$PREFIX/install.sh"
        for f in tests completion; do
            if [ -d "$SRC_DIR/$f" ]; then
                mkdir -p "$PREFIX/$f"
                cp -R "$SRC_DIR/$f/." "$PREFIX/$f/"
            fi
        done
    fi

    # 설정(analyze-kdump.conf, servers.conf)과 로그는 저장소에 없으므로 덮어쓰지 않습니다.
    mkdir -p "$PREFIX/logs" "$PREFIX/vmlinux"
    install -d -m 700 "$PREFIX/secrets"
}

link_commands() {
    local path name link

    mkdir -p "$BIN_DIR"
    for path in "$PREFIX"/bin/*; do
        [ -f "$path" ] || continue
        name=$(basename "$path")
        link="$BIN_DIR/$name"
        if [ -e "$link" ] && [ ! -L "$link" ]; then
            echo "건너뜀: $link 이(가) 일반 파일로 이미 있어 덮어쓰지 않습니다." >&2
            SKIPPED=1
            continue
        fi
        ln -sfn "$path" "$link"
        echo "명령 등록: $name -> $path"
    done
}

install_completion() {
    if [ ! -f "$PREFIX/completion/kdump-tools.bash" ]; then
        return
    fi
    if [ -d "$COMPLETION_DIR" ]; then
        install -m 644 "$PREFIX/completion/kdump-tools.bash" "$COMPLETION_DIR/$COMPLETION_NAME"
        echo "자동완성 등록: $COMPLETION_DIR/$COMPLETION_NAME (새 셸부터 적용)"
    else
        echo "자동완성은 건너뜁니다: $COMPLETION_DIR 가 없습니다. (bash-completion 패키지 설치 후 다시 실행)"
    fi
}

check_dependencies() {
    local cmd purpose

    echo
    echo "필요한 도구 점검:"
    while IFS='|' read -r cmd purpose; do
        if command -v "$cmd" >/dev/null 2>&1; then
            printf '  [OK]   %-9s %s\n' "$cmd" "$purpose"
        else
            printf '  [없음] %-9s %s\n' "$cmd" "$purpose"
        fi
    done <<'EOF'
crash|vmcore 분석 (필수)
whiptail|터미널 메뉴 UI (analyze-kdump-ui)
less|메뉴에서 리포트 보기
python3|LLM 분석
curl|LLM API 호출
ssh|원격 서버 분석
EOF
}

# 설치한 버전과 원본을 기록합니다. analyze-kdump --version과 메뉴의 업데이트 화면이 읽습니다.
write_install_info() {
    local info="$PREFIX/.install-info" version commit="$COMMIT"

    version=$(head -n 1 "$PREFIX/VERSION" 2>/dev/null | tr -d '[:space:]')
    if [ -z "$commit" ] && command -v git >/dev/null 2>&1; then
        commit=$(git -c safe.directory="$SRC_DIR" -C "$SRC_DIR" rev-parse HEAD 2>/dev/null || true)
    fi
    # 설치 디렉터리에서 다시 실행한 경우(파일이 바뀌지 않음)에만 이전 커밋 기록을 유지합니다.
    if [ -z "$commit" ] && [ -f "$info" ] && [ "$(readlink -f "$SRC_DIR")" = "$(readlink -f "$PREFIX")" ]; then
        commit=$(sed -n 's/^COMMIT=//p' "$info" | head -n 1)
    fi

    {
        echo "VERSION=${version:-unknown}"
        echo "COMMIT=$commit"
        echo "INSTALLED_AT=$(date '+%Y-%m-%d %H:%M')"
        echo "SOURCE=${SOURCE_LABEL:-$SRC_DIR}"
        echo "BIN_DIR=$BIN_DIR"
    } > "$info"
    chmod 644 "$info"
    echo "설치 정보: v${version:-unknown}${commit:+ (${commit:0:7})}"
}

do_install() {
    install_files
    write_install_info
    link_commands
    install_completion
    check_dependencies

    echo
    echo "설치 완료. 사용 예:"
    echo "  sudo analyze-kdump-ui"
    echo "  sudo analyze-kdump -r /var/crash"
    if [ ! -f "$PREFIX/analyze-kdump.conf" ]; then
        echo "설정 파일이 없으면 기본값으로 동작합니다. 메뉴의 '설정'에서 만들거나 $PREFIX/analyze-kdump.conf.sample을 참고하세요."
    fi
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) echo "참고: $BIN_DIR 가 현재 PATH에 없습니다. 전체 경로로 실행하거나 PATH에 추가해 주세요." ;;
    esac
    if [ "$SKIPPED" -eq 1 ]; then
        echo "일부 명령은 등록하지 못했습니다. 위의 '건너뜀' 메시지를 확인해 주세요." >&2
        exit 2
    fi
}

do_uninstall() {
    local link target removed=0

    for link in "$BIN_DIR"/*; do
        [ -L "$link" ] || continue
        target=$(readlink "$link")
        case "$target" in
            "$PREFIX/bin/"*)
                rm -f "$link"
                echo "명령 해제: $link"
                removed=1
                ;;
        esac
    done
    if [ -f "$COMPLETION_DIR/$COMPLETION_NAME" ]; then
        rm -f "$COMPLETION_DIR/$COMPLETION_NAME"
        echo "자동완성 해제: $COMPLETION_DIR/$COMPLETION_NAME"
    fi
    [ "$removed" -eq 1 ] || echo "해제할 명령이 없습니다. ($BIN_DIR 에서 $PREFIX/bin 을 가리키는 링크 없음)"

    echo
    echo "설치 디렉터리 $PREFIX (설정, 서버 목록, 로그, vmlinux 포함)는 남겨 두었습니다. 필요 없으면 직접 삭제하세요."
}

if [ "$ACTION" = "uninstall" ]; then
    do_uninstall
else
    do_install
fi
