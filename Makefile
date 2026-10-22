# =============================================================================
# PROYECTO: Tesis Máster Big Data ORT - Guzmán Ferrari
# Disparadores de la corrida completa. `make help` lista los comandos.
# =============================================================================

PY        := .venv/bin/python
STREAMLIT := .venv/bin/streamlit
B1        := src/bloque_1_pricing
B2        := src/bloque_2_operacional
B3        := src/bloque_3_monitoreo
DB        := data/operacional/gtee_operational.db

# Rango del pipeline (sobrescribible: make pipeline START=2026-08-25 END=2026-08-28)
START ?= 2026-08-01
END   ?= 2026-08-31

.PHONY: help all bloque1 bloque2 dataset-a fit simulate pricing plots \
        db pipeline dashboard clean-db clean

help: ## Lista los comandos disponibles
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# --- Bloque 1: Pricing -------------------------------------------------------
dataset-a: ## B1 · Genera Dataset A (histórico consolidado)
	$(PY) $(B1)/generate_dataset_a.py

fit: ## B1 · Ajuste lognormal por merchant
	$(PY) $(B1)/fit_lognormal.py

simulate: ## B1 · Monte Carlo del portafolio
	$(PY) $(B1)/simulate_portfolio.py

pricing: ## B1 · Pricing, VaR/CVaR y gráficos
	$(PY) $(B1)/calculate_pricing.py

plots: ## B1 · Abre los gráficos generados por pricing
	open data/outputs/*.png

bloque1: dataset-a fit simulate pricing ## Corre todo el Bloque 1

# --- Bloque 2: Operacional ---------------------------------------------------
db: ## B2 · Inicializa la base SQLite operacional
	$(PY) $(B2)/initialize_db.py

pipeline: ## B2 · Pipeline diario START..END (default: agosto completo)
	$(PY) $(B2)/run_pipeline.py --start $(START) --end $(END)

bloque2: clean-db db pipeline ## Corre todo el Bloque 2 desde una base limpia

# --- Bloque 3: Monitoreo -----------------------------------------------------
dashboard: ## B3 · Levanta el dashboard Streamlit
	$(STREAMLIT) run $(B3)/dashboard_app.py

# --- Global ------------------------------------------------------------------
all: bloque1 bloque2 ## Regenera todos los datos (Bloques 1 y 2)

clean-db: ## Borra la base operacional (el pipeline hace append: re-correr duplica)
	rm -f $(DB) $(DB)-journal

clean: ## Borra todo data/ (se regenera con make all)
	rm -rf data/
