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
PUBLISH_FILES=(top500.txt top10000.txt top100000.txt all.txt ranking.csv manifest.json)

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

for filename in "${PUBLISH_FILES[@]}"; do
    install -m 0644 "${OUTPUT_DIR}/${filename}" "${DATA_CHECKOUT}/${filename}"
done
"${APP}" --verify-output "${DATA_CHECKOUT}"

git -C "${DATA_CHECKOUT}" config user.name "${GIT_AUTHOR_NAME}"
git -C "${DATA_CHECKOUT}" config user.email "${GIT_AUTHOR_EMAIL}"
git -C "${DATA_CHECKOUT}" add -- "${PUBLISH_FILES[@]}"

if git -C "${DATA_CHECKOUT}" diff --cached --quiet; then
    echo "Generated data is unchanged; data branch was not updated."
    exit 0
fi

git -C "${DATA_CHECKOUT}" diff --cached --check
source_date=$("${PYTHON}" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["source_updated_at"])' "${OUTPUT_DIR}/manifest.json")
git -C "${DATA_CHECKOUT}" commit -m "chore(data): publish ${source_date} snapshot"
git -C "${DATA_CHECKOUT}" push origin HEAD:data

remote_head=$(git -C "${DATA_CHECKOUT}" ls-remote origin refs/heads/data | cut -f1)
local_head=$(git -C "${DATA_CHECKOUT}" rev-parse HEAD)
if [[ "${remote_head}" != "${local_head}" ]]; then
    echo "Remote data branch does not match the published commit." >&2
    exit 1
fi

echo "Published data branch commit ${local_head}."
