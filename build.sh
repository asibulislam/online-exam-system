#!/usr/bin/env bash
# Build step for Render.com (runs on every deploy).
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input
