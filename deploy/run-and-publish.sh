#!/usr/bin/env bash
set -euo pipefail

umask 027

APP_ROOT=${APP_ROOT:-/opt/chinaz-top-domains}
STATE_ROOT=${STATE_ROOT:-/var/lib/chinaz-top-domains}
CACHE_ROOT=${CACHE_ROOT:-/var/cache/chinaz-top-domains}
OUTPUT_DIR=${OUTPUT_DIR:-${STATE_ROOT}/output}
DATA_CHECKOUT=${DATA_CHECKOUT:-${STATE_ROOT}/data-repo}
DEPLOY_KEY=${DEPLOY_KEY:-${STATE_ROOT}/.ssh/id_ed25519}
GIT_AUTHOR_NAME=${GIT_AUTHOR_NAME:-chinaz-top-domains-bot}
GIT_AUTHOR_EMAIL=${GIT_AUTHOR_EMAIL:-22260104+Aethersailor@users.noreply.github.com}

: "${DATA_REPO_SSH:?DATA_REPO_SSH must be configured}"

APP=${APP_ROOT}/venv/bin/chinaz-top-domains
PYTHON=${APP_ROOT}/venv/bin/python
DATA_FILES=(top500.txt top10000.txt top100000.txt all.txt ranking.csv manifest.json)
STATUS_FILE=status.json

export GIT_SSH_COMMAND="ssh -i ${DEPLOY_KEY} -o IdentitiesOnly=yes -o BatchMode=yes"

"${APP}" --full --cache-dir "${CACHE_ROOT}" --output-dir "${OUTPUT_DIR}"
"${APP}" --verify-output "${OUTPUT_DIR}"

if [[ ! -d "${DATA_CHECKOUT}/.git" ]]; then
    git clone --branch data --single-branch "${DATA_REPO_SSH}" "${DATA_CHECKOUT}"
else
    git -C "${DATA_CHECKOUT}" fetch origin data
    git -C "${DATA_CHECKOUT}" switch data
    git -C "${DATA_CHECKOUT}" merge --ff-only origin/data
fi

for filename in "${DATA_FILES[@]}"; do
    install -m 0644 "${OUTPUT_DIR}/${filename}" "${DATA_CHECKOUT}/${filename}"
done
"${APP}" --verify-output "${DATA_CHECKOUT}"

git -C "${DATA_CHECKOUT}" config user.name "${GIT_AUTHOR_NAME}"
git -C "${DATA_CHECKOUT}" config user.email "${GIT_AUTHOR_EMAIL}"
git -C "${DATA_CHECKOUT}" add -- "${DATA_FILES[@]}"

data_changed=true
if git -C "${DATA_CHECKOUT}" diff --cached --quiet -- "${DATA_FILES[@]}"; then
    data_changed=false
fi

checked_on=$(TZ=Asia/Shanghai date +%F)
existing_checked_on=$(
    "${PYTHON}" -c \
        'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("checked_on", ""))' \
        "${DATA_CHECKOUT}/${STATUS_FILE}" 2>/dev/null || true
)

if [[ "${data_changed}" == false && "${existing_checked_on}" == "${checked_on}" ]]; then
    echo "Generated data is unchanged; today's check is already recorded."
    exit 0
fi

"${PYTHON}" - "${DATA_CHECKOUT}/manifest.json" "${DATA_CHECKOUT}/${STATUS_FILE}" \
    "${checked_on}" "${data_changed}" <<'PY'
import json
import os
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
status_path = Path(sys.argv[2])
checked_on = sys.argv[3]
data_changed = sys.argv[4] == "true"

with manifest_path.open(encoding="utf-8") as handle:
    manifest = json.load(handle)

status = {
    "schema_version": 1,
    "checked_on": checked_on,
    "source_updated_at": manifest["source_updated_at"],
    "data_changed": data_changed,
    "tool_version": manifest["tool_version"],
    "source_entries": manifest["source_entries"],
    "unique_domains": manifest["unique_domains"],
}
temporary_path = status_path.with_suffix(status_path.suffix + ".tmp")
temporary_path.write_text(
    json.dumps(status, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
    newline="\n",
)
os.replace(temporary_path, status_path)
PY

git -C "${DATA_CHECKOUT}" add -- "${STATUS_FILE}"
git -C "${DATA_CHECKOUT}" diff --cached --check
source_date=$("${PYTHON}" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["source_updated_at"])' "${OUTPUT_DIR}/manifest.json")
if [[ "${data_changed}" == true ]]; then
    commit_title="chore(data): publish ${source_date} snapshot"
else
    commit_title="chore(data): record ${checked_on} check"
fi
git -C "${DATA_CHECKOUT}" commit -m "${commit_title}"
git -C "${DATA_CHECKOUT}" push origin HEAD:data

remote_head=$(git -C "${DATA_CHECKOUT}" ls-remote origin refs/heads/data | cut -f1)
local_head=$(git -C "${DATA_CHECKOUT}" rev-parse HEAD)
if [[ "${remote_head}" != "${local_head}" ]]; then
    echo "Remote data branch does not match the published commit." >&2
    exit 1
fi

echo "Published data branch commit ${local_head}."
