#!/bin/sh
# Render's dockerCommand keeps quotes literally, so `sh -c "a && b"` can't work: it runs from here.
# On the free plan there's no one-shot `migrate` service, so migrate first, then serve.
set -e
alembic -c /app/alembic.ini upgrade head
exec uvicorn larder_api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers
