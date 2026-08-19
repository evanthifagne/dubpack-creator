#!/bin/bash
# macOS : double-clique ce fichier pour lancer DubPack Creator.
cd "$(dirname "$0")" || exit 1
PY=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10+ est introuvable. Installe-le depuis https://www.python.org/downloads/"
  read -r -p "Appuie sur Entrée pour fermer."
  exit 1
fi
"$PY" run.py "$@"
status=$?
if [ $status -ne 0 ]; then read -r -p "Une erreur est survenue. Appuie sur Entrée pour fermer."; fi
