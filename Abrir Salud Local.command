#!/bin/zsh
cd "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
if [[ ! -x .venv/bin/python ]]; then
  echo 'Faltan las dependencias. Abre Instalar dependencias.command una sola vez.'
  read '?Pulsa Intro para cerrar.'
  exit 1
fi
exec .venv/bin/python launch.py
