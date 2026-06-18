"""
PROYECTO: Tesis Máster Big Data ORT - Guzmán Ferrari
ARCHIVO: generate_dataset_a.py
OBJETIVO: Generador del Dataset A (Pasado/Agregado) con Autocorrelación AR(1),
          descomposición de Cholesky y transformación Lognormal.
          Persistencia en Apache Parquet particionado (Emulación Hive/HDFS).
"""

import os
import numpy as np
import pandas as pd
import config

def run_dataset_a_generation():
    print("=== INICIANDO GENERACIÓN DEL DATASET A (HISTÓRICO CONSOLIDADO) ===")
    
    # -------------------------------------------------------------------------
    # 1. SALVAGUARDA MATEMÁTICA: Validación de la Matriz de Correlación
    # -------------------------------------------------------------------------
    eigenvalues, _ = np.linalg.eigh(config.CORRELATION_MATRIX)
    if np.any(eigenvalues <= 0):
        raise ValueError("🚨 ERROR CRÍTICO ARQUITECTÓNICO: La matriz de correlación no es Definida Positiva.")
    print("-> Salvaguarda de Cholesky: Matriz válida (Definida Positiva).")
    
    # Calcular la matriz triangular inferior L
    L = np.linalg.cholesky(config.CORRELATION_MATRIX)
    
    # -------------------------------------------------------------------------
    # 2. DEFINICIÓN DEL ESPACIO TEMPORAL Y MEMORIA TEMPORAL AR(1)
    # -------------------------------------------------------------------------
    meses_indices = pd.date_range(start="2024-01-01", end="2025-12-01", freq="MS")
    total_meses = len(meses_indices)     # 24 meses
    total_merchants = len(config.MERCHANT_ORDER) # 6 comercios
    
    # Fijamos semilla para la reproducibilidad académica
    np.random.seed(42)
    
    # Coeficientes de memoria temporal (Inercia mes a mes)
    phi_cbk = 0.45  # Inercia del fraude
    phi_tpv = 0.60  # Inercia del volumen transaccional
    
    ruido_ar_cbk = np.zeros((total_meses, total_merchants))
    ruido_ar_tpv = np.zeros((total_meses, total_merchants))
    
    # Inicialización del primer mes (tomo un disparo aleatorio base)
    ruido_ar_cbk[0, :] = np.random.normal(0, 1, total_merchants)
    ruido_ar_tpv[0, :] = np.random.normal(0, 1, total_merchants)
    
    # Construcción estructurada de la inercia temporal mediante bucle secuencial
    for t in range(1, total_meses):
        ruido_ar_cbk[t, :] = phi_cbk * ruido_ar_cbk[t-1, :] + np.sqrt(1 - phi_cbk**2) * np.random.normal(0, 1, total_merchants)
        ruido_ar_tpv[t, :] = phi_tpv * ruido_ar_tpv[t-1, :] + np.sqrt(1 - phi_tpv**2) * np.random.normal(0, 1, total_merchants)
    
    # Aplicamos la matriz de Cholesky al ruido de fraude para inyectar la correlación geográfica/industrial
    ruido_correlacionado_cbk = ruido_ar_cbk @ L.T
    
    # -------------------------------------------------------------------------
    # 3. CONSTRUCCIÓN DE LOS REGISTROS DEL PORTAFOLIO
    # -------------------------------------------------------------------------
    registros = []
    
    for m_idx, fecha in enumerate(meses_indices):
        anio_mes = fecha.strftime("%Y-%m")
        mes_calendario = fecha.month
        
        for m_pos, merchant_id in enumerate(config.MERCHANT_ORDER):
            m_cfg = config.MERCHANTS_CONFIG[merchant_id]
            
            # Incorporación de variación de TPV mes a mes (Jitter del 5% autocorrelacionado)
            tpv_jitter = 1.0 + (ruido_ar_tpv[m_idx, m_pos] * 0.05)
            tpv_base = m_cfg['tpv_base_usd'] * tpv_jitter
            
            ticket_medio = m_cfg['avg_ticket']
            m = m_cfg['cbk_rate_base']
            v = m_cfg['sigma'] ** 2
            
            # Transformación paramétrica matemática de Normal a Lognormal
            mu_log = np.log(m**2 / np.sqrt(v + m**2))
            sigma_log = np.sqrt(np.log(1 + (v / m**2)))
            
            # Extraer el factor estocástico correlacionado
            z = ruido_correlacionado_cbk[m_idx, m_pos]
            cbk_rate_simulado = np.exp(mu_log + sigma_log * z)
            
            # Aplicación de multiplicadores estacionales (Reglas de negocio)
            tpv_multiplicador = 1.0
            cbk_rate_multiplicador = 1.0
            
            if merchant_id in config.ESTACIONALIDAD_CONFIG:
                if mes_calendario in config.ESTACIONALIDAD_CONFIG[merchant_id]:
                    mult_tpv, mult_cbk = config.ESTACIONALIDAD_CONFIG[merchant_id][mes_calendario]
                    tpv_multiplicador = mult_tpv
                    cbk_rate_multiplicador = mult_cbk
            
            # Variables finales afectadas por la estacionalidad
            tpv_final = tpv_base * tpv_multiplicador
            cbk_rate_final = cbk_rate_simulado * cbk_rate_multiplicador
            
            # Cálculo económico robusto (Evitando fracciones de contracargos)
            cbk_fraud_amt_teorico = tpv_final * cbk_rate_final
            cbk_fraud_qty = int(np.round(cbk_fraud_amt_teorico / ticket_medio))
            
            # Salvaguarda de paridad realista para evitar ceros artificiales
            if cbk_fraud_qty == 0 and cbk_fraud_amt_teorico >= (ticket_medio / 2):
                cbk_fraud_qty = 1
                
            # Recalculamos el monto real exacto indexado a unidades enteras
            cbk_fraud_amt_real = cbk_fraud_qty * ticket_medio
            
            # Costos operativos
            cbk_process_cost = cbk_fraud_qty * m_cfg['cbk_cost_per_unit']
            analyst_cost = m_cfg['costo_fijo_operativo'] + (config.COSTO_VARIABLE_ANALISTA_CBK * cbk_fraud_qty)
            
            registros.append({
                'year_month': anio_mes,
                'industry': m_cfg['industry'],
                'merchant_id': merchant_id,
                'country': m_cfg['country'],
                'tpv_usd': tpv_final,
                'avg_ticket': ticket_medio,
                'cbk_rate_simulated': cbk_rate_final,
                'cbk_fraud_qty': cbk_fraud_qty,
                'cbk_fraud_amt': cbk_fraud_amt_real,
                'cbk_process_cost': cbk_process_cost,
                'analyst_cost': analyst_cost
            })
            
    # Transformar a DataFrame de Pandas
    df_dataset_a = pd.DataFrame(registros)
    
    # -------------------------------------------------------------------------
    # 4. PERSISTENCIA EN PARQUET PARTICIONADO (Capa Analítica Local)
    # -------------------------------------------------------------------------
    output_root = "data/dataset_a"
    
    df_dataset_a.to_parquet(
        output_root,
        engine='pyarrow',
        partition_cols=['industry', 'merchant_id'],
        index=False
    )
    
    print(f"-> Éxito: Dataset A guardado en '{output_root}/'. Total registros: {len(df_dataset_a)}")
    print("=== PROCESO DE LA SEMANA 1 FINALIZADO CON ÉXITO ===")

if __name__ == "__main__":
    run_dataset_a_generation()