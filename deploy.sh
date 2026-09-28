#!/bin/bash

set -e

echo "======================================"
echo " Provider Performance Copilot Deploy"
echo "======================================"

cd "$(dirname "$0")"

MESSAGE="${1:-Update Provider Performance Copilot}"

echo ""
echo "1. Running automated tests..."
.venv/bin/python -m pytest -q

echo ""
echo "✅ Tests passed."

echo ""
echo "2. Checking for changes..."

if [ -z "$(git status --porcelain)" ]; then
    echo "No changes to deploy."
    exit 0
fi

echo ""
echo "Changes waiting to be deployed:"
echo "--------------------------------------"
git status --short
echo "--------------------------------------"

echo ""
read -p "Deploy these changes? (y/n): " CONFIRM

if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
    echo ""
    echo "❌ Deployment cancelled."
    echo "Nothing was committed or pushed."
    exit 0
fi

echo ""
echo "3. Staging changes..."
git add .

echo ""
echo "4. Creating Git commit..."
git commit -m "$MESSAGE"

echo ""
echo "5. Pushing to GitHub..."
git push origin main

echo ""
echo "======================================"