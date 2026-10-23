"""
PROYECTO: Tesis Máster Big Data ORT - Guzmán Ferrari
SCRIPT: chargeback_lag_simulator.py
OBJETIVO: 
    Emular el desfasaje temporal (Chargeback Lag) aislando la generación de datos 
    del motor de evaluación de riesgo.
LÓGICA:
    1. Recibe una fecha objetivo (target_date).
    2. Abre una ventana retrospectiva (entre 15 y 90 días hacia el pasado).
    3. Extrae transacciones estrictamente 'APPROVED' de esa ventana.
    4. Aplica la tasa de fraude paramétrica y genera disputas con Reason Code 'Fraud'.
    5. Persiste los eventos en la tabla 'Chargebacks_Gtee'.
"""

import sys
import argparse
import sqlite3
import random
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# Resolución estricta de rutas y carga de matriz genética
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(REPO_ROOT))
import config

DB_PATH = REPO_ROOT / 'data' / 'operacional' / 'gtee_operational.db'

def simulate_delayed_chargebacks(target_date_str):
    """
    Inyecta contracargos diferidos en la base de datos relacional simulando
    la latencia de las redes de pago (Visa/Mastercard).
    """
    target_date = datetime.strptime(target_date_str, '%Y-%m-%d')
    # Semilla diaria: binomial, df.sample (usa el estado global de NumPy) y UUIDs
    seed = config.seed_diaria(target_date_str, config.SEED_OFFSET_CBK_LAG)
    np.random.seed(seed)
    random.seed(seed)
    print("\n=======================================================")
    print(f"[*] SIMULADOR DE CHARGEBACK LAG (FECHA: {target_date_str})")
    print("=======================================================")
    
    if not DB_PATH.exists():
        raise FileNotFoundError(f"[-] Error: Base de datos no encontrada en {DB_PATH}")

    # Conexión a SQLite y habilitación estricta de Foreign Keys
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    
    try:
        # 1. Definición de la ventana de vulnerabilidad (Lag de 15 a 90 días)
        window_start = (target_date - timedelta(days=90)).strftime('%Y-%m-%dT00:00:00')
        window_end = (target_date - timedelta(days=15)).strftime('%Y-%m-%dT23:59:59')
        
        print(f"[*] Escaneando transacciones aprobadas entre {window_start[:10]} y {window_end[:10]}")
        
        # 2. Extracción relacional. Regla de negocio: Solo transacciones APPROVED
        query_tx = f"""
            SELECT transaction_id, merchant_id, usd_amount 
            FROM Transactions_Gtee 
            WHERE status = 'APPROVED' 
            AND transaction_timestamp BETWEEN '{window_start}' AND '{window_end}'
            ORDER BY rowid
        """
        df_vulnerables = pd.read_sql_query(query_tx, conn)
        
        if df_vulnerables.empty:
            print("[!] No se detectaron transacciones maduras en la ventana evaluada.")
            return

        registros_cbk = []
        
        # Extracción en memoria de contracargos preexistentes para exclusión
        query_existentes = "SELECT transaction_id FROM Chargebacks_Gtee"
        df_existentes = pd.read_sql_query(query_existentes, conn)
        
        # 3. Asignación probabilística distribuida en el tiempo
        for merchant_id in config.MERCHANT_ORDER:
            cfg = config.MERCHANTS_CONFIG[merchant_id]
            tasa_fraude_teorica = cfg['cbk_rate_base']
            
            # [TRAMPA 4: NEGATIVE_FRAUD_BALANCE]
            if merchant_id == 'Retail_2' and target_date_str == '2026-08-28':
                print(f"[!] STRESS TEST: Ataque masivo de fraude para Retail_2")
                tasa_fraude_teorica = 0.90 
            
            df_merch = df_vulnerables[df_vulnerables['merchant_id'] == merchant_id]
            
            # Exclusión vectorial en memoria (preservando el volumen real de riesgo)
            df_potenciales = df_merch[~df_merch['transaction_id'].isin(df_existentes['transaction_id'])]
            
            if df_potenciales.empty:
                continue
                
            volumen_potencial = len(df_potenciales)
            
            # Derivación de tasa diaria (ventana de 75 días: T-90 a T-15)
            probabilidad_diaria = tasa_fraude_teorica / 75.0
            
            fraudes_esperados = np.random.binomial(n=volumen_potencial, p=probabilidad_diaria)
            
            if fraudes_esperados > 0:
                # Muestreo seguro limitando al volumen potencial disponible
                df_fraud = df_potenciales.sample(n=min(fraudes_esperados, volumen_potencial))
                
                for _, row in df_fraud.iterrows():
                    registros_cbk.append({
                        'chargeback_id': config.uuid_determinista(),
                        'transaction_id': row['transaction_id'],
                        'cbk_usd_amount': row['usd_amount'], 
                        'reason_code': 'Fraud',          
                        'cbk_timestamp': target_date.strftime('%Y-%m-%dT%H:%M:%S')
                    })
                    
        # 4. Persistencia transaccional de los contracargos
        if registros_cbk:
            df_cbk_to_insert = pd.DataFrame(registros_cbk)
            df_cbk_to_insert.to_sql('Chargebacks_Gtee', con=conn, if_exists='append', index=False)
            print(f"[+] Éxito: {len(registros_cbk)} disputas por fraude real ingresadas al sistema.")
        else:
            print("[*] Operación finalizada: Sin fraudes materializados en esta iteración.")

    except sqlite3.IntegrityError as e:
        print(f"[-] Error crítico de integridad referencial: {e}")
    except Exception as e:
        print(f"[-] Error inesperado en la simulación: {e}")
    finally:
        conn.close()
        print("=======================================================\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Simulador de latencia de contracargos')
    parser.add_argument('--target_date', type=str, required=True, help='Fecha virtual (YYYY-MM-DD)')
    args = parser.parse_args()
    
    simulate_delayed_chargebacks(args.target_date)