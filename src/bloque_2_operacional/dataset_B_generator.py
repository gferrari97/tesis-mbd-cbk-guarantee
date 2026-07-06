"""
PROYECTO: Tesis Máster Big Data ORT - Guzmán Ferrari
SCRIPT: dataset_B_generator.py
OBJETIVO: Emulador de flujo transaccional diario (CRON simulado).
          Genera el Dataset B aplicando modelos estocásticos (Poisson/Normal)
          y reglas heurísticas para emular tráfico Card-Not-Present (CNP).
          Persiste los resultados en la base operativa local SQLite.
"""

import sys
from pathlib import Path
import sqlite3
import pandas as pd
import numpy as np
import uuid
import random
from datetime import datetime, timezone

# =============================================================================
# 1. RESOLUCIÓN DE RUTAS Y DEPENDENCIAS
# =============================================================================
# Resolución dinámica para importar la matriz inmutable desde la raíz
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(REPO_ROOT))
import config

DB_PATH = REPO_ROOT / 'data' / 'operacional' / 'gtee_operational.db'

# =============================================================================
# 2. PARÁMETROS FIJOS EXÓGENOS (OUTPUT BLOQUE 1)
# =============================================================================
# Resultados teóricos del Pricing Estocástico (Monte Carlo - VaR 95%) -- bloque 1
# Se inyectan de forma estática para mantener la inmutabilidad de la dimensión operativa.
FEE_OPTIMO_ASIGNADO = {
    'Gaming_1': 3.929,
    'Gaming_2': 1.894,
    'Retail_1': 0.616,
    'Retail_2': 2.558,
    'Travel_1': 2.392,
    'Travel_2': 1.572
}

def sync_merchants(conn):
    """
    ===========================================================================
    BLOQUE 3: SINCRONIZACIÓN DE LA DIMENSIÓN (MERCHANTS_GTEE)
    ===========================================================================
    Asegura que los comercios existan en la base de datos antes de inyectar 
    transacciones, respetando la directiva PRAGMA foreign_keys = ON.
    """
    cursor = conn.cursor()
    
    for merchant_id in config.MERCHANT_ORDER:
        cfg = config.MERCHANTS_CONFIG[merchant_id]
        
        cursor.execute("SELECT 1 FROM Merchants_Gtee WHERE merchant_id = ?", (merchant_id,))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO Merchants_Gtee 
                (merchant_id, industry, country, fee_assigned, cbk_process_cost, analyst_cost)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                merchant_id,
                cfg['industry'],
                cfg['country'],
                FEE_OPTIMO_ASIGNADO[merchant_id], # Inyección estática del Bloque 1
                cfg['cbk_cost_per_unit'],
                cfg['costo_fijo_operativo']
            ))
    conn.commit()
    print("[+] Sincronización de dimensión 'Merchants_Gtee' validada.")

def generate_daily_transactions(target_date):
    """
    ===========================================================================
    BLOQUE 4: MOTOR ESTOCÁSTICO Y HEURÍSTICA DE IDENTIDADES (DATASET B)
    ===========================================================================
    Genera el lote transaccional diario aplicando:
    1. Distribución Poisson para el volumen (Tasa Diaria).
    2. Distribución Normal para la fluctuación de los montos (sigma=15%).
    3. Heurística de Recurrencia (Pool de Identidades 80/20) para emular
       compradores legítimos recurrentes y clústeres de fraude.
    """
    registros = []
    base_timestamp = target_date.strftime("%Y-%m-%dT%H:%M:%S")
    
    # Memoria temporal para emular la repetición de identidades (El Pool)
    identity_pools = {m: [] for m in config.MERCHANT_ORDER}

    for merchant_id in config.MERCHANT_ORDER:
        cfg = config.MERCHANTS_CONFIG[merchant_id]
        
        # Derivación de la Tasa Media Diaria (Lambda)
        volumen_mensual_esperado = cfg['tpv_base_usd'] / cfg['avg_ticket']
        lambda_diario = volumen_mensual_esperado / 30.0
        
        # Volumetría orgánica mediante Poisson
        tx_qty = np.random.poisson(lambda_diario)
        
        for _ in range(tx_qty):
            # -----------------------------------------------------------------
            # 4.1. Generación del Monto (Normal Dist)
            # -----------------------------------------------------------------
            monto_tx = max(1.0, np.random.normal(cfg['avg_ticket'], cfg['avg_ticket'] * 0.15))
            
            # -----------------------------------------------------------------
            # 4.2. Heurística de Identidad (80% Nuevos / 20% Recurrentes)
            # -----------------------------------------------------------------
            if len(identity_pools[merchant_id]) > 0 and random.random() < 0.20:
                # Reciclar identidad existente (Velocity / Usuario Recurrente)
                identidad = random.choice(identity_pools[merchant_id])
            else:
                # Generar identidad 100% nueva
                identidad = {
                    'device_id': str(uuid.uuid4()),
                    'ip_address': f"{random.randint(1, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
                    'document': str(random.randint(10000000, 99999999))
                }
                identity_pools[merchant_id].append(identidad)
            
            # -----------------------------------------------------------------
            # 4.3. Estado Probabilístico (85% Approved / 15% Rejected)
            # -----------------------------------------------------------------
            status_tx = 'APPROVED' if random.random() < 0.85 else 'REJECTED'
            
            # Ensamblado del registro
            registros.append({
                'transaction_id': str(uuid.uuid4()),
                'merchant_id': merchant_id,
                'usd_amount': round(monto_tx, 2),
                'transaction_timestamp': base_timestamp,
                'status': status_tx,
                'device_id': identidad['device_id'],
                'ip_address': identidad['ip_address'],
                'document': identidad['document']
            })
            
    return pd.DataFrame(registros)

def inject_data_quality_anomalies(df):
    """
    ===========================================================================
    BLOQUE 5: INYECCIÓN ESTRUCTURAL DE ANOMALÍAS (API OUTAGE)
    ===========================================================================
    Simula caídas esporádicas en la transmisión de datos. 
    En un día normal, el ruido basal es < 0.1%.
    Hay una probabilidad baja (ej. 5%) de que ocurra un 'Apagón de API', 
    donde el 30% - 70% de los registros pierden el device_id.
    """
    if len(df) == 0:
        return df
        
    # 1. ¿Ocurrió una falla masiva de red en este lote diario? (5% de probabilidad)
    es_dia_de_falla = random.random() < 0.05
    
    if es_dia_de_falla:
        # Falla masiva: se apaga gran parte de la volumetría
        tasa_anomalia = random.uniform(0.30, 0.70)
        print(f"[🚨 ALERTA OUTAGE] Simulando caída de API externa. Tasa de nulos esperada: {tasa_anomalia:.1%}")
    else:
        # Día normal: ruido blanco basal en la red
        tasa_anomalia = 0.001
        
    # 2. Aplicar la máscara de corrupción según el estado del día
    mascara_ruido = np.random.rand(len(df)) < tasa_anomalia
    df.loc[mascara_ruido, 'device_id'] = None
    
    total_anomalias = mascara_ruido.sum()
    if es_dia_de_falla:
        print(f"[!] Impacto crítico: {total_anomalias} transacciones afectadas por el apagón.")
    
    return df

def run_daily_batch():
    """
    ===========================================================================
    BLOQUE 6: ORQUESTADOR PRINCIPAL (PERSISTENCIA DML)
    ===========================================================================
    """
    print("=== INICIANDO CRON DE INGESTA DIARIA (DATASET B) ===")
    
    # Marca de tiempo de ejecución
    today_simulated = datetime.now(timezone.utc)
    print(f"[*] Fecha de procesamiento (UTC): {today_simulated.strftime('%Y-%m-%dT%H:%M:%S')}")
    
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Error Crítico: No se encontró la base operativa en {DB_PATH}.")
    
    conn = sqlite3.connect(DB_PATH)
    
    try:
        # Fase 1: Dimensiones
        sync_merchants(conn)
        
        # Fase 2: Generación Estocástica
        df_lote = generate_daily_transactions(today_simulated)
        print(f"[*] Volumen orgánico simulado: {len(df_lote)} intentos de pago (Aprobados y Rechazados).")
        
        # Fase 3: Contaminación de Datos
        df_lote = inject_data_quality_anomalies(df_lote)
        
        # Fase 4: Persistencia Física
        df_lote.to_sql('Transactions_Gtee', con=conn, if_exists='append', index=False)
        print(f"[+] Lote diario persistido exitosamente en 'Transactions_Gtee'.")
        
    except sqlite3.IntegrityError as e:
        print(f"[-] Error de Integridad Referencial (SQLite): {e}")
    except Exception as e:
        print(f"[-] Error inesperado durante la ingesta: {e}")
    finally:
        conn.close()
        
    print("=== PROCESO BATCH FINALIZADO ===")

if __name__ == "__main__":
    run_daily_batch()