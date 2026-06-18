"""
PROYECTO: Tesis Máster Big Data ORT - Guzmán Ferrari
SCRIPT: fit_lognormal.py
FASE: Bloque 1 - Fase Lognormal (Semana 2)
OBJETIVO: Ajuste paramétrico mediante Estimación por Máxima Verosimilitud (MLE)
          sobre el Data Lake analítico histórico (Dataset A) para extraer los
          parámetros empíricos que consumirá el simulador de Monte Carlo.
"""

from pathlib import Path
import numpy as np
import pandas as pd
import scipy.stats as stats
import config 

# =============================================================================
# 1. CONFIGURACIÓN DE RUTAS AGNÓSTICAS (ENFOQUE MVP)
# =============================================================================
#Determina la raíz del proyecto retrocediendo desde src/bloque_1_pricing/
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DATASET_A_PATH = REPO_ROOT / "data" / "dataset_a"
OUTPUT_DIR = REPO_ROOT / "data" / "outputs"
OUTPUT_FILE = OUTPUT_DIR / "empirical_parameters.pkl"

# Aseguramos la existencia del directorio de salidas
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def run_parametric_fitting():
    # =============================================================================
    # 2. INGESTA MASIVA DESDE EL DATA LAKE LOCAL
    # =============================================================================
    print(f"[*] Leyendo Data Lake local en Parquet desde: {DATASET_A_PATH}")

    # Reemplazo de os.path.exists por la validación nativa del objeto Path
    if not DATASET_A_PATH.exists():
        raise FileNotFoundError(
            f"Error fatal: No se encontró el Dataset A en la ruta '{DATASET_A_PATH}'."
        )

    # PyArrow lee la estructura columnar y hereda nativamente las particiones
    # 'industry' y 'merchant_id' como columnas del DataFrame de forma ultra eficiente.
    df_historical = pd.read_parquet(DATASET_A_PATH)

    print(
        f"[+] Ingesta exitosa. Registros totales leídos: {len(df_historical)} (Esperados: 144)"
    )

    results = []

    # =============================================================================
    # 3. BUCLE DE AISLAMIENTO Y AJUSTE MATEMÁTICO (MLE)
    # =============================================================================
    # Iteramos respetando estrictamente el MERCHANT_ORDER del config.py.
    # Esto blinda el orden de indexación para la simulación multivariada (Cholesky).
    for merchant in config.MERCHANT_ORDER:
        print(f"\n[>] Procesando ajuste para merchant: {merchant}")

        # Filtramos la serie temporal de 24 meses del comercio actual
        df_merchant = df_historical[df_historical["merchant_id"] == merchant]

        if len(df_merchant) == 0:
            print(
                f"[⚠️ ALERTA] No se encontraron registros para el comercio {merchant} en el Parquet."
            )
            continue

        # Convertimos la serie a un array numérico vectorizado de NumPy para acelerar SciPy
        cbk_rates = df_merchant["cbk_rate_simulated"].to_numpy()

        # ---------------------------------------------------------------------
        # RESTRICCIÓN DE NEGOCIO CRÍTICA (FLOC=0):
        # Obligamos al algoritmo de SciPy a fijar la localización (desplazamiento)
        # en cero absoluto. En medios de pago, la tasa de fraude no puede ser negativa.
        # Si dejamos que 'loc' flote libre, distorsionará la simulación de Monte Carlo.
        # ---------------------------------------------------------------------
        shape_emp, loc_emp, scale_emp = stats.lognorm.fit(cbk_rates, floc=0)

        # ---------------------------------------------------------------------
        # CONVERSIÓN DE PARÁMETROS SCI-PY A PARÁMETROS FINANCIEROS REALES:
        # SciPy define la Lognormal de tal forma que el parámetro 'shape' es igual
        # directamente al sigma (volatilidad logarítmica).
        # El parámetro 'scale' de SciPy equivale a e^(mu). Para recuperar el mu
        # financiero (la media logarítmica empírica), aplicamos el logaritmo natural.
        # ---------------------------------------------------------------------
        sigma_emp = shape_emp
        mu_emp = np.log(scale_emp)

        # =============================================================================
        # 4. EXTRACCIÓN DE PARÁMETROS TEÓRICOS PARA ANÁLISIS DE CONTRASTE ACADÉMICO
        # =============================================================================
        # Recuperamos los datos base del config.py para contrastar la teoría vs la realidad realizada
        cfg = config.MERCHANTS_CONFIG[merchant]
        cbk_base = cfg["cbk_rate_base"]
        sigma_teorico = cfg["sigma"]

        # Fórmula matemática estándar de la Lognormal para derivar el Mu Teórico:
        # mu = ln(E[X]) - (sigma^2)/2 , donde E[X] es la tasa base esperada.
        mu_teorico = np.log(cbk_base) - (sigma_teorico**2) / 2

        # Acumulamos las métricas en la estructura estructurada
        results.append(
            {
                "merchant_id": merchant,
                "mu_teorico": mu_teorico,
                "mu_empirico": mu_emp,
                "sigma_teorico": sigma_teorico,
                "sigma_empirico": sigma_emp,
                "media_realizada": cbk_rates.mean(),
            }
        )

        print(
            f"    -> Mu    Teórico: {mu_teorico:.4f} | Empírico (MLE): {mu_emp:.4f}"
        )
        print(
            f"    -> Sigma Teórico: {sigma_teorico:.4f} | Empírico (MLE): {sigma_emp:.4f}"
        )

    # =============================================================================
    # 5. CONSOLIDACIÓN, PERSISTENCIA Y DIAGNÓSTICO FINAL
    # =============================================================================
    # Consolidamos los resultados en un DataFrame limpio de control
    df_params = pd.DataFrame(results)

    # Guardamos los parámetros calculados localmente en formato Pickle (.pkl)
    # Este archivo será consumido de forma directa por el módulo de Monte Carlo,
    # evitando reprocesamientos innecesarios y optimizando el tiempo de cómputo en la Mac.
    df_params.to_pickle(OUTPUT_FILE)
    print(f"\n[+] Matriz de parámetros empíricos guardada con éxito en: {OUTPUT_FILE}")

    # Desplegamos el DataFrame final en la terminal de VS Code para validación visual rápida
    print("\n================ MATRIZ DE PARÁMETROS FINALES CONSOLIDADA ================")
    print(
        df_params[
            [
                "merchant_id",
                "mu_teorico",
                "mu_empirico",
                "sigma_teorico",
                "sigma_empirico",
                "media_realizada",
            ]
        ].to_string(index=False)
    )
    print("==========================================================================")


if __name__ == "__main__":
    run_parametric_fitting()