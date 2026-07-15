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
import pandas as pd
import numpy as np
import uuid
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
        """
        df_vulnerables = pd.read_sql_query(query_tx, conn)
        
        if df_vulnerables.empty:
            print("[!] No se detectaron transacciones maduras en la ventana evaluada.")
            return

        registros_cbk = []
        
        # 3. Asignación probabilística basada en la matriz genética
        for merchant_id in config.MERCHANT_ORDER:
            cfg = config.MERCHANTS_CONFIG[merchant_id]
            tasa_fraude_teorica = cfg['cbk_rate_base']
            
            df_merch = df_vulnerables[df_vulnerables['merchant_id'] == merchant_id]
            if df_merch.empty:
                continue
                
            # Calcular volumen real extraído y derivar cantidad de fraudes
            volumen_tx = len(df_merch)
            fraudes_esperados = np.random.binomial(n=volumen_tx, p=tasa_fraude_teorica)
            
            if fraudes_esperados > 0:
                # Muestreo aleatorio para simular vulneración de identidades
                df_fraud = df_merch.sample(n=fraudes_esperados)
                
                for _, row in df_fraud.iterrows():
                    registros_cbk.append({
                        'chargeback_id': str(uuid.uuid4()),
                        'transaction_id': row['transaction_id'],
                        'cbk_usd_amount': row['usd_amount'], # Arrastre exacto del monto original
                        'reason_code': 'Fraud',          # Filtro de fraude real
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