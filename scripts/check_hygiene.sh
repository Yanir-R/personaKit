#!/usr/bin/env bash
# Fails if the tree contains patterns that must never be published:
# private paths, internal ticket ids, personal identifiers, credential shapes.
set -u
cd "$(dirname "$0")/.."
pattern='(/Users/[A-Za-z0-9_.-]+|/home/[a-z][A-Za-z0-9_-]+/|TRI-[0-9]+|D-0[0-9]{2}|Trinity|sk-ant-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY)'
hits=$(grep -rInE "$pattern" . --exclude-dir=.git --exclude=check_hygiene.sh || true)
if [ -n "$hits" ]; then
  echo "Hygiene check failed. Remove or replace these:"
  echo "$hits"
  exit 1
fi
echo "Hygiene check passed."
