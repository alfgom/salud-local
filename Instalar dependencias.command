#!/bin/zsh
cd "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
python3 -m venv .venv || exit 1
.venv/bin/python -m pip install -r requirements.txt || exit 1
echo 'Instalación completada. Abre Abrir Salud Local.command.'
read '?Pulsa Intro para cerrar.'
