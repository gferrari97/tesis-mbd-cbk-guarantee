"""
PROYECTO: Tesis Máster Big Data ORT - Guzmán Ferrari (N° 302404)
SCRIPT: simulate_portfolio.py
FASE: Bloque 1 - Fase Monte Carlo (Semana 3)
OBJETIVO: Motor de simulación estocástica vectorizado (10.000 iteraciones) para 
          calcular la distribución de pérdidas futuras basándose en la covarianza 
          empírica del Dataset A y sentar las bases del Pricing del producto.
"""

from pathlib import Path
import numpy as np
import pandas as pd
import config

# =============================================================================
# 1. RESTRICCIONES DE INGENIERÍA Y GOBERNANZA (MVP)
# =============================================================================
np.random.seed(42)
ITERACIONES = 10000

# Determina la ubicación del script actual de forma dinámica
BASE_DIR = Path(__file__).resolve().parent

# Configuración de rutas agnósticas para el simulador
INPUT_PARAMS_FILE = BASE_DIR / "data" / "outputs" / "empirical_parameters.pkl"
DATASET_A_PATH = BASE_DIR / "data" / "dataset_a"
OUTPUT_DIR = BASE_DIR / "data" / "outputs"
OUTPUT_SIM_FILE = OUTPUT_DIR / "portfolio_simulations.pkl"

def extraer_cholesky_empirico():
    """
    Calcula la matriz de covarianza cruzada empírica desde los archivos estructurados 
    locales y fuerza la condición semi-definida positiva (PSD) mediante eigenvalue clipping.
    """
    if not DATASET_A_PATH.exists():
        raise FileNotFoundError(f"Falta el Data Lake histórico local en: {DATASET_A_PATH}")
        
    df_a = pd.read_parquet(DATASET_A_PATH)
    
    # Pivoteamos el dataframe para alinear las series mensuales de los comercios
    df_pivot = df_a.pivot_table(index='year_month', columns='merchant_id', values='cbk_rate_simulated')
    
    # Aseguramos la ordenación estricta de la matriz genética
    df_pivot = df_pivot[config.MERCHANT_ORDER]
    emp_corr = df_pivot.corr().values
    
    # Corrección espectral algebraico para garantizar la viabilidad de Cholesky
    eigenvalues, eigenvectors = np.linalg.eigh(emp_corr)
    eigenvalues[eigenvalues < 1e-8] = 1e-8
    emp_corr_psd = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
    
    # Normalización para restaurar la diagonal unitaria de la correlación
    d = np.sqrt(np.diag(emp_corr_psd))
    emp_corr_psd = emp_corr_psd / np.outer(d, d)
    
    return np.linalg.cholesky(emp_corr_psd), emp_corr_psd

def run_montecarlo_simulation():
    print(f"=== INICIANDO MOTOR DE MONTE CARLO ({ITERACIONES} ITERACIONES) ===")
    
    # =============================================================================
    # 2. EXTRACCIÓN DE DEPENDENCIAS ESPACIALES EMPÍRICAS
    # =============================================================================
    L_emp, matriz_emp = extraer_cholesky_empirico()
    print("\n=== MATRIZ DE CORRELACIÓN EMPÍRICA EN LA MUESTRA (AJUSTADA PSD) ===")
    print(np.round(matriz_emp, 4))
    print("===================================================================\n")
    
    # =============================================================================
    # 3. INGESTA DE PARÁMETROS EMPÍRICOS (Dataset A MLE)
    # =============================================================================
    if not INPUT_PARAMS_FILE.exists():
        raise FileNotFoundError(f"Falta el insumo de la Semana 2: {INPUT_PARAMS_FILE}")
    
    df_params = pd.read_pickle(INPUT_PARAMS_FILE)
    df_params['merchant_id'] = pd.Categorical(df_params['merchant_id'], categories=config.MERCHANT_ORDER, ordered=True)
    df_params = df_params.sort_values('merchant_id').reset_index(drop=True)
    
    mu_vector = df_params['mu_empirico'].values.reshape(-1, 1)
    sigma_vector = df_params['sigma_empirico'].values.reshape(-1, 1)

    # =============================================================================
    # 4. EXTRACCIÓN DE VECTORES DETERMINÍSTICOS (Broadcasting desde config.py)
    # =============================================================================
    tpv_vector = np.array([config.MERCHANTS_CONFIG[m]['tpv_base_usd'] for m in config.MERCHANT_ORDER]).reshape(-1, 1)
    ticket_vector = np.array([config.MERCHANTS_CONFIG[m]['avg_ticket'] for m in config.MERCHANT_ORDER]).reshape(-1, 1)
    process_cost_vector = np.array([config.MERCHANTS_CONFIG[m]['cbk_cost_per_unit'] for m in config.MERCHANT_ORDER]).reshape(-1, 1)
    fixed_cost_vector = np.array([config.MERCHANTS_CONFIG[m]['costo_fijo_operativo'] for m in config.MERCHANT_ORDER]).reshape(-1, 1)

    # =============================================================================
    # 5. MOTOR ESTOCÁSTICO: MATRIZ DE RUIDO Y COMPENSACIÓN MULTIVARIADA
    # =============================================================================
    Z = np.random.standard_normal((len(config.MERCHANT_ORDER), ITERACIONES))
    Z_correlacionada = L_emp @ Z

    # Transformación geométrica al espacio de tasas de fraude lognormales
    tasas_simuladas = np.exp(mu_vector + sigma_vector * Z_correlacionada)
    
    # =============================================================================
    # 6. MODELADO FINANCIERO Y OPERATIVO (Proyección de Pérdidas del Portafolio)
    # =============================================================================
    perdida_fraude_usd = tpv_vector * tasas_simuladas
    cbk_qty_simulado = np.ceil(perdida_fraude_usd / ticket_vector)
    
    costo_red_usd = cbk_qty_simulado * process_cost_vector
    costo_analistas_usd = fixed_cost_vector + (config.COSTO_VARIABLE_ANALISTA_CBK * cbk_qty_simulado if hasattr(config, 'COSTO_VARIABLE_ANALISTA_CBK') else 0)
    
    impacto_total_merchants = perdida_fraude_usd + costo_red_usd + costo_analistas_usd

    # =============================================================================
    # 7. CONSOLIDACIÓN DEL PORTAFOLIO Y PERSISTENCIA
    # =============================================================================
    perdida_portafolio_agregada = np.sum(impacto_total_merchants, axis=0)
    
    resultados = {
        'tasas_simuladas': tasas_simuladas,
        'impacto_total_merchants': impacto_total_merchants,
        'perdida_portafolio_agregada': perdida_portafolio_agregada,
        'matriz_correlacion_empirica': matriz_emp
    }
    
    if not OUTPUT_DIR.exists():
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
    pd.to_pickle(resultados, OUTPUT_SIM_FILE)
    
    print(f"[*] Simulación completada en milisegundos (Vectorización NumPy).")
    print(f"[*] Resultados persistidos en: {OUTPUT_SIM_FILE}")
    print(f"    -> Pérdida media esperada del Portafolio: ${np.mean(perdida_portafolio_agregada):,.2f}")
    print(f"    -> Pérdida máxima simulada (Peor escenario): ${np.max(perdida_portafolio_agregada):,.2f}")

if __name__ == "__main__":
    run_montecarlo_simulation()