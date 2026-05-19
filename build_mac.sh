#!/bin/bash
# build_mac.sh — Build Email Agent.app on macOS
# Usage: bash build_mac.sh
set -e

echo "==> Installing/upgrading build dependencies..."
pip install --upgrade pyinstaller flask

echo "==> Cleaning previous build..."
rm -rf build dist

echo "==> Running PyInstaller..."
pyinstaller email_agent.spec

echo ""
echo "==> Build complete!"
echo "    App:  dist/Email Agent.app"
echo "    Share the 'Email Agent.app' file with coworkers."
echo "    They double-click it — no Python or terminal needed."
