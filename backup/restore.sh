#!/usr/bin/env bash
# Пересобирает окружение из локальной копии, без обращения к PyPI и GitHub.
# Нужен только uv и папка backup/wheels рядом.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d backup/wheels ]; then
  echo "Нет backup/wheels — офлайн-восстановление невозможно." >&2
  echo "Тогда: uv venv && uv pip install -r backup/requirements.lock.txt" >&2
  exit 1
fi

echo "Проверяю контрольные суммы колёс..."
(cd backup && shasum -a 256 -c wheels.sha256 --quiet) || { echo "Колёса побиты, восстановление отменено." >&2; exit 1; }

rm -rf .venv
uv venv --python 3.12
uv pip install --python .venv/bin/python --no-index --find-links backup/wheels -r backup/requirements.lock.txt
.venv/bin/python -c "from browser_use import Agent; from importlib.metadata import version; print('готово: browser-use', version('browser-use'))"
