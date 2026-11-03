# kdump-tools bash 자동완성 (install.sh가 /etc/bash_completion.d/kdump-tools로 설치)

_analyze_kdump() {
    local cur prev
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    case "$prev" in
        -config|--config|-llm-report|--llm-report)
            mapfile -t COMPREPLY < <(compgen -f -- "$cur")
            return
            ;;
    esac

    if [[ "$cur" == -* ]]; then
        mapfile -t COMPREPLY < <(compgen -W "-report -r -llm --llm -no-llm --no-llm -config --config --llm-report -h --help --version" -- "$cur")
    else
        mapfile -t COMPREPLY < <(compgen -f -- "$cur")
    fi
}

complete -o filenames -F _analyze_kdump analyze-kdump
