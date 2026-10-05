#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

use_dev_dependencies="true"
dev_option=""

write_step() {
    printf '%s\n' "$1"
}

write_phase() {
    printf '\n=== %s ===\n' "$1"
}

resolve_venv_python() {
    local venv_dir="$1"
    if [[ -x "${venv_dir}/bin/python" ]]; then
        printf '%s\n' "${venv_dir}/bin/python"
    elif [[ -x "${venv_dir}/Scripts/python.exe" ]]; then
        printf '%s\n' "${venv_dir}/Scripts/python.exe"
    else
        printf "No python interpreter found under '%s' (checked bin/python and Scripts/python.exe).\n" "${venv_dir}" >&2
        exit 1
    fi
}

usage() {
    cat <<'EOF'
Usage: ./scripts/python/update_venv.sh [options]

Options:
  --include-dev       Install the dev dependency-group explicitly.
  --no-dev            Skip the dev dependency-group.
  -h, --help          Show this help text.
EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --include-dev)
                if [[ "${dev_option}" == "no-dev" ]]; then
                    printf "Use either --include-dev or --no-dev, but not both.\n" >&2
                    exit 1
                fi
                use_dev_dependencies="true"
                dev_option="include-dev"
                shift
                ;;
            --no-dev)
                if [[ "${dev_option}" == "include-dev" ]]; then
                    printf "Use either --include-dev or --no-dev, but not both.\n" >&2
                    exit 1
                fi
                use_dev_dependencies="false"
                dev_option="no-dev"
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                printf "Unknown argument: %s\n" "$1" >&2
                usage >&2
                exit 1
                ;;
        esac
    done
}

parse_args "$@"

if ! command -v uv >/dev/null 2>&1; then
    printf "uv is required but was not found on PATH. Install it from https://docs.astral.sh/uv/getting-started/installation/ and retry.\n" >&2
    exit 1
fi

if [[ ! -d "${REPO_ROOT}/.venv" ]]; then
    printf "No .venv directory was found. Run ./scripts/python/setup_env.sh first.\n" >&2
    exit 1
fi
venv_python="$(resolve_venv_python "${REPO_ROOT}/.venv")"

write_step "Starting virtual environment update via uv."

write_phase "Phase 1: Validate Environment"
write_step "[venv] Using existing interpreter: ${venv_python}"
"${venv_python}" --version

if [[ ! -f "${REPO_ROOT}/pyproject.toml" ]]; then
    printf "pyproject.toml is required for the uv update flow.\n" >&2
    exit 1
fi
write_step "[Project] Verified pyproject.toml and existing .venv."

write_phase "Phase 2: Update Dependencies"
sync_args=("sync" "--upgrade")
if [[ "${use_dev_dependencies}" == "false" ]]; then
    sync_args+=("--no-group" "dev")
fi
write_step "[Dependencies] Running: uv ${sync_args[*]}"
(
    cd "${REPO_ROOT}"
    uv "${sync_args[@]}"
)

write_phase "Phase 3: Summary"
write_step "Virtual environment updated successfully."
printf 'Suggested interpreter path: %s\n' "${venv_python}"
