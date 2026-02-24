#!/usr/bin/env bash
# Check that the main README.md is updated when new integrations are added.
#
# Usage:
#   scripts/check_readme.sh <base_ref> <dir> [dir ...]
#
# Arguments:
#   base_ref  Git ref to diff against (e.g., origin/main)
#   dir       One or more integration directories to check
#
# Exit codes:
#   0 - README is up to date (or no new integrations)
#   1 - New integration detected but README not updated
#   2 - Missing arguments
#
# Examples:
#   scripts/check_readme.sh origin/main my-new-integration
#   scripts/check_readme.sh origin/main integration-a integration-b

set -euo pipefail

if [ $# -lt 2 ]; then
    echo "Usage: $0 <base_ref> <dir> [dir ...]" >&2
    exit 2
fi

BASE_REF="$1"
shift

README_CHANGED=$(git diff --name-only "$BASE_REF" HEAD | grep "^README\.md$" || true)

FAILED=0
for dir in "$@"; do
    if [ ! -d "$dir" ]; then
        continue
    fi

    NEW_FILES=$(git diff --name-only --diff-filter=A "$BASE_REF" HEAD | grep "^$dir/" || true)
    if [ -n "$NEW_FILES" ] && [ -z "$README_CHANGED" ]; then
        echo "❌ NEW INTEGRATION DETECTED: '$dir'"
        echo ""
        echo "   But main README.md was NOT updated!"
        echo ""
        echo "   Fix: Add your integration to the main README.md file"
        echo "   Example:"
        echo "   | $dir | Your description | Auth Type |"
        echo ""
        FAILED=1
    fi
done

echo "========================================"
if [ $FAILED -eq 1 ]; then
    echo "❌ README CHECK FAILED"
    echo "========================================"
    exit 1
fi
echo "✅ README CHECK PASSED"
echo "========================================"
