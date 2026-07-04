#!/usr/bin/env bash
# Обновление и перезапуск всего стека на сервере.
# Ожидает, что репозиторий фронтенда склонирован рядом: ../lobotomy-frontend
set -e
cd "$(dirname "$0")"
git pull
git -C ../lobotomy-frontend pull
docker compose up -d --build
