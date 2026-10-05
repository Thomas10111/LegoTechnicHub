#!/usr/bin/env bash
# Prepare an NVIDIA Jetson (JetPack 5 or 6) to run technic-hub.
#
# JetPack ships Python 3.8 (JetPack 5) or 3.10 (JetPack 6), but this project uses
# Python 3.12 like the ObjectDetection project. uv installs 3.12 into a project
# local virtual environment without touching the system Python.
#
# Usage: ./scripts/setup_jetson.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/4] Installing and starting BlueZ"
sudo apt-get update
sudo apt-get install -y bluez curl
sudo systemctl enable --now bluetooth
sudo rfkill unblock bluetooth || true

echo "[2/4] Allowing $USER to use Bluetooth without sudo"
sudo usermod -aG bluetooth "$USER"

echo "[3/4] Installing uv"
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "[4/4] Creating .venv with Python 3.12 and installing technic-hub"
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"

echo
echo "Done. Log out and back in once so the bluetooth group applies, then:"
echo "  source .venv/bin/activate"
echo "  technic-hub scan"
