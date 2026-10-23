# Chargeback Guarantee: Pricing estocástico y monitoreo operativo

Tesis del Máster en Big Data, Universidad ORT Uruguay. Autor: Guzmán Ferrari.

Este repositorio tiene el código que reproduce los resultados de la tesis. Hay tres bloques encadenados:

| Bloque | Carpeta | Qué hace | Qué genera |
|---|---|---|---|
| 1 · Pricing | `src/bloque_1_pricing/` | Genera el Dataset A (histórico AR(1) con Cholesky), ajusta una lognormal por merchant (MLE), corre un Monte Carlo correlacionado de 10.000 iteraciones y deriva el fee óptimo (VaR 95% + markup) | `data/dataset_a/`, `data/outputs/*.pkl`, `*.png`, `fees_optimos.json` |
| 2 · Operacional | `src/bloque_2_operacional/` | Simula día por día el tráfico transaccional (Dataset B), el chargeback lag y el motor micro-batch de guardrails | `data/operacional/gtee_operational.db` (SQLite) |
| 3 · Monitoreo | `src/bloque_3_monitoreo/` | Dashboard Streamlit sobre la base operativa | Interfaz web local |

Los parámetros del portafolio (los 6 merchants) están en `config.py`. El Bloque 2 lee los fees que calcula el Bloque 1 desde `data/outputs/fees_optimos.json`, así que hay que correr el Bloque 1 primero.

## Requisitos

- Python 3.11
- macOS o Linux con `make` (`demo.sh` usa el `date` de macOS)

## Instalación

```bash
git clone https://github.com/gferrari97/tesis-mbd-cbk-guarantee.git
cd tesis-mbd-cbk-guarantee
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

El `Makefile` usa el intérprete de `.venv/`, así que no hace falta activar el entorno.

## Ejecución

```bash
make all         # Bloques 1 y 2 completos, desde cero
make dashboard   # Bloque 3: abre el dashboard en http://localhost:8501
```

Para una demostración guiada, con pausas entre etapas:

```bash
./demo.sh            # Bloques 1, 2 y 3
./demo.sh bloque1    # Solo Pricing
```

`make help` lista todos los comandos. Los más útiles:

| Comando | Descripción |
|---|---|
| `make bloque1` | Dataset A → ajuste lognormal → Monte Carlo → pricing y gráficos |
| `make bloque2` | Base SQLite limpia + pipeline diario del 2026-08-01 al 2026-08-31 |
| `make pipeline START=2026-08-25 END=2026-08-28` | Corre solo un rango de días (agrega a la base existente) |
| `make clean` | Borra `data/` por completo |

## Resultados esperados

El Bloque 1 usa semilla fija (`42`), así que da los mismos resultados en todas las corridas:

| Merchant | VaR 95% (USD) | Fee óptimo |
|---|---|---|
| Gaming_1 | 22.920,28 | 3,929% |
| Gaming_2 | 15.784,46 | 1,894% |
| Retail_1 | 7.698,00 | 0,616% |
| Retail_2 | 12.788,01 | 2,558% |
| Travel_1 | 11.958,47 | 1,594% |
| Travel_2 | 21.911,89 | 1,052% |

Portafolio: VaR 99% de USD 80.745,45 contra USD 119.164,05 si se suman las reservas aisladas, lo que da un ahorro de capital de USD 38.418,60. El Expected Shortfall (CVaR 99%) es de USD 85.858,79.

El Bloque 2 también es determinista. Cada día simulado usa una semilla derivada de su fecha (`config.seed_diaria`), así que un día da el mismo resultado si se corre agosto completo o solo ese día. `make bloque2` siempre genera la misma base:

| Tabla | Registros |
|---|---|
| `Transactions_Gtee` | 222.053 |
| `Chargebacks_Gtee` | 173 |
| `Guardrails_Log` | 4 |

Las 4 alertas corresponden a las anomalías inyectadas:

| Fecha | Merchant | Alerta | Acción |
|---|---|---|---|
| 2026-08-25 | Travel_1 | `DATA_SILENCE` | `MANUAL_REVIEW_REQUIRED` |
| 2026-08-26 | Retail_1 | `TRAFFIC_DEVIATION` | `LISTEN_MODE_ACTIVATED` |
| 2026-08-27 | Gaming_1 | `DATA_QUALITY_BREACH` | `COVERAGE_SUSPENDED` |
| 2026-08-28 | Retail_2 | `NEGATIVE_FRAUD_BALANCE` | `COVERAGE_SUSPENDED` |

## Datos

`data/` no se versiona, porque se regenera entero con `make all`. Todos los datos son sintéticos.
