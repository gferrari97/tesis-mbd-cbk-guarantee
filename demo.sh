#!/usr/bin/env bash
# =============================================================================
# PROYECTO: Tesis Máster Big Data ORT - Guzmán Ferrari
# SCRIPT: demo.sh
# OBJETIVO: Demostración guiada de la corrida, con pausas entre etapas.
#
# USO:
#   ./demo.sh            -> Bloques 1, 2 y 3
#   ./demo.sh bloque1    -> Solo Pricing
#   ./demo.sh bloque2    -> Solo Operacional (requiere Bloque 1 corrido antes)
#   ./demo.sh bloque3    -> Solo Dashboard (requiere la base operacional)
#
# El Bloque 2 hace un "warm-up" silencioso de WARMUP_START..WARMUP_END y muestra
# en vivo, día por día, LIVE_START..LIVE_END (ventana con anomalías inyectadas).
# =============================================================================

set -euo pipefail
cd "$(dirname "$0")"

WARMUP_START="${WARMUP_START:-2026-08-01}"
WARMUP_END="${WARMUP_END:-2026-08-24}"
LIVE_START="${LIVE_START:-2026-08-25}"
LIVE_END="${LIVE_END:-2026-08-28}"
LOG_DIR="data/logs"

BOLD=$'\033[1m'; CYAN=$'\033[36m'; DIM=$'\033[2m'; RESET=$'\033[0m'

banner() {
    clear
    echo "${CYAN}══════════════════════════════════════════════════════════════════════${RESET}"
    echo "${BOLD}  $1${RESET}"
    [[ -n "${2:-}" ]] && echo "${DIM}  $2${RESET}"
    echo "${CYAN}══════════════════════════════════════════════════════════════════════${RESET}"
    echo
}

pause() {
    echo
    read -r -p "${DIM}[ Enter para continuar ]${RESET}" _
}

# Fechas día por día (date de macOS/BSD)
date_range() {
    local d="$1"
    while [[ "$d" < "$2" || "$d" == "$2" ]]; do
        echo "$d"
        d=$(date -j -v+1d -f "%Y-%m-%d" "$d" "+%Y-%m-%d")
    done
}

run_bloque1() {
    banner "BLOQUE 1 · PRICING" "1/4 · Generación del Dataset A (histórico consolidado)"
    make -s dataset-a; pause

    banner "BLOQUE 1 · PRICING" "2/4 · Ajuste de distribución lognormal por merchant"
    make -s fit; pause

    banner "BLOQUE 1 · PRICING" "3/4 · Simulación Monte Carlo del portafolio correlacionado"
    make -s simulate; pause

    banner "BLOQUE 1 · PRICING" "4/4 · Derivación de pricing, VaR y Expected Shortfall"
    make -s pricing; pause

    banner "BLOQUE 1 · PRICING" "Gráficos generados"
    make -s plots; pause
}

run_bloque2() {
    banner "BLOQUE 2 · OPERACIONAL" "Inicialización de la base SQLite (desde cero)"
    make -s clean-db db; pause

    mkdir -p "$LOG_DIR"
    banner "BLOQUE 2 · OPERACIONAL" "Warm-up: historia $WARMUP_START → $WARMUP_END (log en $LOG_DIR/warmup.log)"
    echo "[*] Procesando lotes diarios en segundo plano..."
    if ! make -s pipeline START="$WARMUP_START" END="$WARMUP_END" > "$LOG_DIR/warmup.log" 2>&1; then
        echo "[!] Falló el warm-up. Últimas líneas del log:"; tail -20 "$LOG_DIR/warmup.log"; exit 1
    fi
    echo "[+] Warm-up completo."; pause

    for d in $(date_range "$LIVE_START" "$LIVE_END"); do
        banner "BLOQUE 2 · OPERACIONAL" "Lote diario en vivo: $d"
        make -s pipeline START="$d" END="$d"; pause
    done
}

run_bloque3() {
    banner "BLOQUE 3 · MONITOREO" "Dashboard Streamlit (Ctrl+C para cerrar)"
    make -s dashboard
}

case "${1:-all}" in
    bloque1) run_bloque1 ;;
    bloque2) run_bloque2 ;;
    bloque3) run_bloque3 ;;
    all)     run_bloque1; run_bloque2; run_bloque3 ;;
    *)       echo "Uso: $0 [bloque1|bloque2|bloque3|all]"; exit 1 ;;
esac
