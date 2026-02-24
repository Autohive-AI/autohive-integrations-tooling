#!/usr/bin/env bash
# Run code quality checks on integration directories.
#
# Checks performed per directory:
#   1. Install dependencies from requirements.txt
#   2. Python syntax check (py_compile)
#   3. Import availability check (check_imports.py)
#   4. JSON validity check
#
# Usage:
#   scripts/check_code.sh <dir> [dir ...]
#
# Exit codes:
#   0 - All checks passed
#   1 - One or more checks failed
#   2 - No directories provided
#
# Examples:
#   scripts/check_code.sh my-integration
#   scripts/check_code.sh integration-a integration-b

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <dir> [dir ...]" >&2
    exit 2
fi

FAILED=0

for dir in "$@"; do
    echo "----------------------------------------"
    echo "Checking: $dir"
    echo "----------------------------------------"
    echo ""

    # Install dependencies
    if [ -f "$dir/requirements.txt" ]; then
        echo "📦 Installing dependencies..."
        pip install -r "$dir/requirements.txt" -q 2>&1 || true
        echo ""
    fi

    # Syntax check
    echo "🐍 Checking Python syntax..."
    SYNTAX_OK=true
    while IFS= read -r -d '' pyfile; do
        if ! python -m py_compile "$pyfile" 2>&1; then
            echo "   ❌ $pyfile"
            SYNTAX_OK=false
            FAILED=1
        fi
    done < <(find "$dir" -name "*.py" -type f -print0)

    if $SYNTAX_OK; then
        echo "   ✅ Syntax OK"
    else
        echo ""
        echo "   Fix: Check the Python files above for syntax errors"
        echo "   Run locally: python -m py_compile <file.py>"
    fi
    echo ""

    # Import check
    echo "📥 Checking imports..."
    if [ -f "$dir/config.json" ]; then
        ENTRY_POINT=$(python -c "import json; print(json.load(open('$dir/config.json')).get('entry_point', ''))" 2>/dev/null || echo "")
        if [ -n "$ENTRY_POINT" ] && [ -f "$dir/$ENTRY_POINT" ]; then
            if ! python "$SCRIPT_DIR/check_imports.py" "$dir/$ENTRY_POINT" 2>&1; then
                echo "   ❌ Import errors in $dir/$ENTRY_POINT"
                echo ""
                echo "   Fix: Install missing packages in requirements.txt"
                echo "   Or check if package name is spelled correctly"
                FAILED=1
            else
                echo "   ✅ Imports OK"
            fi
        else
            echo "   ⚠️ No entry point found, skipping"
        fi
    else
        echo "   ⚠️ No config.json found, skipping"
    fi
    echo ""

    # JSON check
    echo "📄 Checking JSON files..."
    JSON_OK=true
    while IFS= read -r -d '' jsonfile; do
        if ! python -m json.tool "$jsonfile" > /dev/null 2>&1; then
            echo "   ❌ $jsonfile"
            JSON_OK=false
            FAILED=1
        fi
    done < <(find "$dir" -name "*.json" -type f -print0)

    if $JSON_OK; then
        echo "   ✅ JSON files OK"
    else
        echo ""
        echo "   Fix: Check for missing commas, quotes, or brackets"
        echo "   Validate at: https://jsonlint.com/"
    fi
    echo ""
done

echo "========================================"
if [ $FAILED -eq 1 ]; then
    echo "❌ CODE CHECK FAILED"
    echo "========================================"
    exit 1
fi
echo "✅ CODE CHECK PASSED"
echo "========================================"
