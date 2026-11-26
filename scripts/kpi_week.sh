#!/usr/bin/env bash
# Weekly KPI sheet: the numbers docs/KPI.md asks for, straight from the prod logs.
# usage: ./scripts/kpi_week.sh [window]   (default 7d)
set -euo pipefail
cd "$(dirname "$0")/.."
SINCE="${1:-7d}"

echo "== Embudo: vistas -> entradas -> altas -> primer import, por día y por fuente =="
uv run stocks logs funnel --since "$SINCE"
echo
echo "== Uso por día: cuentas, visitantes, chat, importaciones, feedback =="
uv run stocks logs usage --since "$SINCE"
echo
echo "== Instalaciones en pantalla de inicio =="
uv run stocks logs installs --since "$SINCE"
echo
echo "== Cuentas registradas (altas y último acceso) =="
uv run stocks users
