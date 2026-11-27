#!/usr/bin/env bash
# Convenience wrapper: run from any directory, dispatches to the project
export DISTILLER_DIR="/c/Users/pc/Documents/门店运营/video-account-distiller"
export OLLAMA_MODELS="$HOME/.ollama/models"

if [ ! -d "$DISTILLER_DIR" ]; then
  echo "Error: Video Account Distiller project not found at $DISTILLER_DIR" >&2
  exit 1
fi

cd "$DISTILLER_DIR" || exit 1
PYTHONPATH= uv run distiller "$@"
