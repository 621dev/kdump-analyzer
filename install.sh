#!/bin/bash
# kdump-analyzer 설치 스크립트
#
# 파일을 설치 디렉터리(기본 /opt/kdump-analyzer)에 복사하고, bin/의 명령을 PATH에 등록합니다.
#   sudo ./install.sh                # 설치 또는 업데이트
#   sudo ./install.sh --uninstall    # 등록한 명령 해제 (설치 디렉터리의 설정·로그·vmlinux는 남김)
#
# 옵션:
#   --prefix DIR    설치 디렉터리 (기본 /opt/kdump-analyzer, 예전 위치 /opt/kdump-tools에 설치돼 있으면 그곳)
#   --bin-dir DIR   명령을 등록할 디렉터리 (기본 /usr/sbin)
#                   RHEL 계열 sudo의 secure_path에는 /usr/local/* 가 없어서 기본값을 /usr/sbin으로 둡니다.
#   --commit SHA    설치 정보에 기록할 커밋 (git 저장소가 아닌 원본에서 설치할 때, 메뉴 업데이트가 사용)
#   --source TEXT   설치 정보에 기록할 원본 설명
#   --move-to DIR   기존 설치(설정·서버 목록·vmlinux·로그 포함)를 DIR로 옮김 (예전 경로에는 링크를 남김, --no-link로 끔)
set -e

SRC_DIR=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
DEFAULT_PREFIX="/opt/kdump-analyzer"
# 1.19.0까지의 기본 설치 위치. 이미 여기 설치된 서버는 옵션 없이 다시 실행해도 이 자리를 업데이트합니다.
LEGACY_PREFIX="/opt/kdump-tools"
PREFIX=""
BIN_DIR="/usr/sbin"
BIN_DIR_SET=0
MOVE_TO=""
MOVE_LINK=1
COMPLETION_DIR="/etc/bash_completion.d"
COMPLETION_NAME="kdump-tools"
ACTION="install"
SKIPPED=0
COMMIT=""
SOURCE_LABEL=""

usage() {
    # 맨 위 주석(set -e 전까지)을 그대로 보여줍니다.
    sed -n '2,/^set -e$/p' "$0" | sed -e '/^set -e$/d' -e 's/^# \{0,1\}//'
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
            BIN_DIR_SET=1
            shift 2
            ;;
        --move-to)
            [ -n "${2:-}" ] || die "--move-to에는 옮길 디렉터리가 필요합니다."
            MOVE_TO="$2"
            ACTION="move"
            shift 2
            ;;
        --no-link)
            MOVE_LINK=0
            shift
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

installed_at() {
    [ -f "$1/.install-info" ] || [ -x "$1/bin/analyze-kdump" ]
}

# --prefix가 없으면 설치 위치를 고릅니다. 설치가 둘로 갈라지지 않도록 이미 설치된 곳을 우선합니다.
#   1. 설치 디렉터리 안의 install.sh로 실행했으면 그 디렉터리
#   2. 새 기본 위치(/opt/kdump-analyzer)에 설치돼 있으면 그곳
#   3. 예전 기본 위치(/opt/kdump-tools)에만 설치돼 있으면 그곳
#   4. 어디에도 없으면 새 기본 위치
if [ -z "$PREFIX" ]; then
    if [ -f "$SRC_DIR/.install-info" ]; then
        PREFIX="$SRC_DIR"
    elif installed_at "$DEFAULT_PREFIX" || ! installed_at "$LEGACY_PREFIX"; then
        PREFIX="$DEFAULT_PREFIX"
    else
        PREFIX="$LEGACY_PREFIX"
        echo "예전 기본 위치에 설치된 것을 그대로 업데이트합니다: $PREFIX (다른 위치로 옮기려면 --prefix)"
    fi
fi

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

# 기존 설치를 통째로 다른 위치로 옮깁니다. 같은 파일 시스템이면 mv라 바로 끝나고 공간도 더 들지 않습니다.
# 설정 파일 안의 예전 경로를 고치고, 예전 경로에는 새 위치를 가리키는 링크를 남겨(--no-link로 끔)
# 다른 곳에 저장된 예전 경로(웹 UI의 서버 설정 등)도 계속 동작하게 합니다.
# 마지막으로 새 위치의 install.sh로 명령·자동완성·설치 정보를 다시 등록합니다.
do_move() {
    local dest="$MOVE_TO" parent bin_dir source size free conf pattern
    local -a args

    case "$dest" in
        /*) ;;
        *) die "--move-to에는 절대 경로가 필요합니다: $dest" ;;
    esac
    while [ "${#dest}" -gt 1 ] && [ "${dest%/}" != "$dest" ]; do
        dest="${dest%/}"
    done
    if [ -L "$PREFIX" ]; then
        die "$PREFIX 는 이미 옮긴 뒤 남긴 링크입니다 (실제 위치: $(readlink -f "$PREFIX"))."
    fi
    installed_at "$PREFIX" || die "옮길 설치가 없습니다: $PREFIX"
    if [ "$(readlink -f "$PREFIX")" = "$(readlink -m "$dest")" ]; then
        die "이미 $dest 에 설치돼 있습니다."
    fi
    case "$(readlink -m "$dest")/" in
        "$(readlink -f "$PREFIX")"/*) die "설치 디렉터리 안으로는 옮길 수 없습니다: $dest" ;;
    esac
    if [ -e "$dest" ] && { [ ! -d "$dest" ] || [ -n "$(ls -A "$dest" 2>/dev/null)" ]; }; then
        die "옮길 위치가 비어 있지 않습니다: $dest"
    fi
    parent=$(dirname "$dest")
    mkdir -p "$parent"
    if [ "$(stat -c %d "$PREFIX")" != "$(stat -c %d "$parent")" ]; then
        size=$(du -sk "$PREFIX" | awk '{ print $1 }')
        free=$(df -Pk "$parent" | awk 'NR == 2 { print $4 }')
        if [ -z "$free" ] || [ "$free" -le $((size + 65536)) ]; then
            die "공간이 모자랍니다: 필요 $((size / 1024))MB, $parent 남은 공간 $((${free:-0} / 1024))MB"
        fi
        echo "다른 파일 시스템으로 옮기므로 복사합니다 ($((size / 1024))MB)."
    fi

    bin_dir=$(sed -n 's/^BIN_DIR=//p' "$PREFIX/.install-info" 2>/dev/null | head -n 1)
    [ "$BIN_DIR_SET" -eq 1 ] && bin_dir="$BIN_DIR"
    source=$(sed -n 's/^SOURCE=//p' "$PREFIX/.install-info" 2>/dev/null | head -n 1)

    [ -d "$dest" ] && rmdir "$dest"
    echo "옮기는 중: $PREFIX -> $dest"
    mv "$PREFIX" "$dest"

    conf="$dest/analyze-kdump.conf"
    if [ -f "$conf" ] && grep -qF "$PREFIX" "$conf"; then
        cp -p "$conf" "$conf.before-move"
        # sed 정규식에서 특별한 문자를 이스케이프합니다(경로 구분자는 '#').
        pattern=$(printf '%s' "$PREFIX" | sed 's/[][\.*^$#]/\\&/g')
        sed -i -e "s#${pattern}/#${dest}/#g" -e "s#${pattern}\"#${dest}\"#g" "$conf"
        echo "설정 파일의 경로를 새 위치로 바꿨습니다: $conf (이전 내용: $conf.before-move)"
    fi
    if [ "$MOVE_LINK" -eq 1 ]; then
        ln -s "$dest" "$PREFIX"
        echo "예전 경로에 링크를 남깁니다: $PREFIX -> $dest"
    fi
    echo

    args=(--prefix "$dest" --bin-dir "${bin_dir:-$BIN_DIR}")
    [ -n "$source" ] && args+=(--source "$source")
    exec bash "$dest/install.sh" "${args[@]}"
}

if [ "$ACTION" = "uninstall" ]; then
    do_uninstall
elif [ "$ACTION" = "move" ]; then
    do_move
else
    do_install
fi
