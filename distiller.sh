#!/usr/bin/env bash
# Wrapper that clears PYTHONPATH before running distiller
# Usage: ./distiller.sh <command> [args...]
cd "$(dirname "$0")" || exit 1
export OLLAMA_MODELS="$HOME/.ollama/models"
PYTHONPATH= uv run distiller "$@"
