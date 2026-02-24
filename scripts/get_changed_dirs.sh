#!/usr/bin/env bash
# Get changed integration directories from a git diff.
#
# Requires: Python 3.13+
#
# Usage:
#   scripts/get_changed_dirs.sh <base_ref>
#
# Arguments:
#   base_ref  Git ref to diff against (e.g., origin/main, HEAD~1)
#
# Output:
#   Space-separated list of changed integration directory names.
#   Excludes infrastructure folders (.github, scripts, tests, etc.)
#
# Exit codes:
#   0 - Success (may output empty string if no integration dirs changed)
#   1 - Missing base_ref argument
#
# Examples:
#   scripts/get_changed_dirs.sh origin/main
#   scripts/get_changed_dirs.sh HEAD~1

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <base_ref>" >&2
    exit 1
fi

BASE_REF="$1"

# Folders that are not integrations
SKIP_DIRS=".github scripts tests template-structure"

CHANGED_FILES=$(git diff --name-only "$BASE_REF" HEAD 2>/dev/null || echo "")

CHANGED_DIRS=""
for file in $CHANGED_FILES; do
    # Only consider files inside subdirectories
    if [[ "$file" != *"/"* ]]; then
        continue
    fi

    DIR=$(echo "$file" | cut -d'/' -f1)

    # Skip infrastructure directories
    skip=false
    for skip_dir in $SKIP_DIRS; do
        if [[ "$DIR" == "$skip_dir" ]]; then
            skip=true
            break
        fi
    done
    if $skip; then
        continue
    fi

    # Deduplicate
    if [[ ! " $CHANGED_DIRS " =~ " $DIR " ]]; then
        CHANGED_DIRS="$CHANGED_DIRS $DIR"
    fi
done

echo "$CHANGED_DIRS" | xargs
