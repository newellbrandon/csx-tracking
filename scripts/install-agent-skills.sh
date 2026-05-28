#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DEST="${REPO_ROOT}/.cursor/skills"
AGENT_SKILLS_REPO="https://github.com/mongodb/agent-skills.git"

if ! command -v git >/dev/null 2>&1; then
  echo "Error: git is required but not found on PATH." >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

echo "Cloning ${AGENT_SKILLS_REPO} ..."
git clone --depth 1 "${AGENT_SKILLS_REPO}" "${tmpdir}/agent-skills"

if [[ ! -d "${tmpdir}/agent-skills/skills" ]]; then
  echo "Error: expected skills directory not found in cloned repository." >&2
  exit 1
fi

mkdir -p "${SKILLS_DEST}"

echo "Installing skills into ${SKILLS_DEST} ..."
cp -R "${tmpdir}/agent-skills/skills/." "${SKILLS_DEST}/"

echo ""
echo "Installed MongoDB agent skills:"
find "${SKILLS_DEST}" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort | sed 's/^/  - /'
echo ""
echo "Done. Re-run this script to refresh skills from upstream."
