"""
PROYECTO: Tesis Máster Big Data ORT - Guzmán Ferrari
ARCHIVO de CONFIGURACIÓN CENTRALIZADA: config.py
OBJETIVO: Matriz Genética y Parámetros del Portafolio de Medios de Pago
"""

import numpy as np

# =============================================================================
# 1. ORDEN ESTRICTO DEL PORTAFOLIO
# =============================================================================
# El orden de esta lista rige la indexación de la matriz de correlación.
MERCHANT_ORDER = ['Gaming_1', 'Gaming_2', 'Retail_1', 'Retail_2', 'Travel_1', 'Travel_2']

# =============================================================================
# 2. MATRIZ GENÉTICA DE MERCHANTS (PARÁMETROS BASE CONGELADOS)
# =============================================================================
MERCHANTS_CONFIG = {
    'Gaming_1': {
        'industry': 'Gaming',
        'country': 'BR',
        'tpv_base_usd': 700000.0,
        'avg_ticket': 8.0,
        'cbk_rate_base': 0.0120,   # 1.20%
        'sigma': 0.0065,           # Volatilidad en términos absolutos (0.65%)
        'cbk_cost_per_unit': 2.71, # Costo marginal de adquirencia BR
        'costo_fijo_operativo': 500.0
    },
    'Gaming_2': {
        'industry': 'Gaming',
        'country': 'MX',
        'tpv_base_usd': 1000000.0,
        'avg_ticket': 12.0,
        'cbk_rate_base': 0.0095,   # 0.95%
        'sigma': 0.0035,           # 0.35%
        'cbk_cost_per_unit': 0.02, # Costo marginal de adquirencia MX
        'costo_fijo_operativo': 350.0
    },
    'Retail_1': {
        'industry': 'Retail',
        'country': 'MX',
        'tpv_base_usd': 1500000.0,
        'avg_ticket': 60.0,
        'cbk_rate_base': 0.0045,   # 0.45%
        'sigma': 0.0015,           # 0.15%
        'cbk_cost_per_unit': 0.02,
        'costo_fijo_operativo': 350.0
    },
    'Retail_2': {
        'industry': 'Retail',
        'country': 'AR',
        'tpv_base_usd': 600000.0,
        'avg_ticket': 70.0,
        'cbk_rate_base': 0.0120,   # 1.20% (Caso crítico con colas pesadas)
        'sigma': 0.0085,           # 0.85% #alto para forzar pico de Argentina (como fue en merchant que conozco de AR)
        'cbk_cost_per_unit': 0.01, # Costo marginal de adquirencia AR
        'costo_fijo_operativo': 350.0
    },
    'Travel_1': {
        'industry': 'Travel',
        'country': 'AR',
        'tpv_base_usd': 900000.0,
        'avg_ticket': 350.0,
        'cbk_rate_base': 0.0085,   # 0.85%
        'sigma': 0.0060,           # 0.60%
        'cbk_cost_per_unit': 0.01,
        'costo_fijo_operativo': 350.0
    },
    'Travel_2': {
        'industry': 'Travel',
        'country': 'BR',
        'tpv_base_usd': 2500000.0,
        'avg_ticket': 300.0,
        'cbk_rate_base': 0.0040,   # 0.40%
        'sigma': 0.0015,           # 0.15%
        'cbk_cost_per_unit': 2.71,
        'costo_fijo_operativo': 500.0
    }
}

# =============================================================================
# 3. MATRIZ DE CORRELACIÓN PARAMÉTRICA (ρ) - INPUT PARA CHOLESKY
# =============================================================================
# Las posiciones corresponden estrictamente al orden indexado en MERCHANT_ORDER
CORRELATION_MATRIX = np.array([
    [1.00, 0.65, 0.10, 0.05, 0.05, 0.25],  # Gaming_1 (BR)
    [0.65, 1.00, 0.15, 0.02, 0.02, 0.10],  # Gaming_2 (MX)
    [0.10, 0.15, 1.00, 0.10, 0.05, 0.10],  # Retail_1 (MX)
    [0.05, 0.02, 0.10, 1.00, 0.60, 0.10],  # Retail_2 (AR)
    [0.05, 0.02, 0.05, 0.60, 1.00, 0.20],  # Travel_1 (AR)
    [0.25, 0.10, 0.10, 0.10, 0.20, 1.00]   # Travel_2 (BR)
])

# =============================================================================
# 4. REGLAS DE NEGOCIO GLOBALES Y FACTORES ESTACIONALES
# =============================================================================
COSTO_VARIABLE_ANALISTA_CBK = 2.0  # USD por contracargo procesado manualmente

# Curva de maduración estática del fraude (IBNR)
# Valores derivados empíricamente de la distribución de tiempos de consolidación del Dataset A
CBK_MATURATION_CURVE = {
    1: 0.25,  # Al cierre del mes 1, asume recibido el 25% del fraude total de la cohorte
    2: 0.70,  # Al cierre del mes 2, asume recibido el 70% del fraude total de la cohorte
    3: 0.95,  # Al cierre del mes 3, asume recibido el 95% del fraude total de la cohorte
    4: 1.00   # A partir del mes 4, la cohorte se considera 100% madurada y consolidada
}
# Diccionario de estacionalidad por mes calendario (Clave: Mes int)
# Estructura: 'Nombre_Merchant': {mes: (multiplicador_tpv, multiplicador_cbk_rate)}
ESTACIONALIDAD_CONFIG = {
    'Retail_1': {11: (1.60, 0.80), 12: (1.60, 0.80)}, # Buen Fin / Navidad
    'Retail_2': {11: (1.60, 0.80), 12: (1.60, 0.80)}, 
    'Travel_1': {1: (1.30, 1.00), 2: (1.30, 1.00)},  # Temporada estival austral
    'Travel_2': {1: (1.30, 1.00), 2: (1.30, 1.00)}
}


# =============================================================================
# 5. REPRODUCIBILIDAD DEL BLOQUE 2 (SEMILLAS DIARIAS)
# =============================================================================
# Cada script del pipeline diario se re-siembra con una semilla derivada de la
# fecha simulada: un mismo día produce el mismo lote tanto si se corre el mes
# completo como si se corre ese día aislado (p. ej. demo.sh warm-up + en vivo).
SEED_OPERACIONAL = 42

# Desplazamientos para que cada script use un flujo aleatorio independiente
SEED_OFFSET_DATASET_B = 0
SEED_OFFSET_CBK_LAG = 1
SEED_OFFSET_MICROBATCH = 2

def seed_diaria(target_date_str, offset=0):
    """Semilla determinística para la fecha simulada 'YYYY-MM-DD'."""
    return (SEED_OPERACIONAL + int(target_date_str.replace("-", ""))) * 10 + offset

def uuid_determinista():
    """UUID v4 tomado del generador 'random' sembrado (reemplaza a uuid.uuid4)."""
    import random
    import uuid
    return str(uuid.UUID(int=random.getrandbits(128), version=4))
