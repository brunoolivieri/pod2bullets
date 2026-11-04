#!/usr/bin/env bash
# Provisiona o ambiente virtual Python no WSL Ubuntu 26.04
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="/usr/bin/python3"

echo "=== Verificando Python ==="
"$PYTHON" --version

if [ ! -d ".venv" ]; then
    echo "=== Criando .venv ==="
    "$PYTHON" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "=== Atualizando pip e ferramentas de build ==="
pip install --upgrade pip setuptools wheel hatchling

echo "=== Instalando dependências do pod2bullets [dev] ==="
pip install -e ".[dev]"

echo "=== Validando ambiente e GPU ==="
python -c "
import av
import soundfile
import numpy
import fastapi
import feedparser
import typer
print('Bibliotecas base importadas com sucesso!')
try:
    import ctranslate2
    print('CTranslate2 disponível. CUDA devices:', ctranslate2.get_cuda_device_count())
except Exception as e:
    print('CTranslate2 aviso:', e)
"

echo "=== Setup concluído com sucesso! ==="

