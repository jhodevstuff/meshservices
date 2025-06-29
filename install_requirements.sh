#!/bin/bash
set -e

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 not installed lol" >&2
  exit 1
fi

python3 -m pip install --upgrade pip
python3 -m pip install \
    pyserial \
    requests \
    beautifulsoup4 \
    feedparser \
    wikipedia \
    googletrans==4.0.0rc1

echo "Installed all requirements."
