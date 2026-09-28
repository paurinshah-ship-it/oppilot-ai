#!/bin/bash

set -e

echo "======================================"
echo " Provider Performance Copilot Deploy"
echo "======================================"

# Make sure we are in the project directory
cd "$(dirname "$0")"

# Get commit message
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
git status --short

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
echo "✅ DEPLOYMENT COMPLETE"
echo "GitHub has been updated."
echo "Streamlit Cloud can now redeploy main."
echo "======================================"