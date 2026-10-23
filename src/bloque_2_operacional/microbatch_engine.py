"""
PROYECTO: Tesis Máster Big Data ORT - Guzmán Ferrari
SCRIPT: microbatch_engine.py
OBJETIVO: 
    Motor analítico Micro-batch en Pandas. Evalúa el tráfico diario y el 
    Fraud Balance retrospectivo (IBNR) para disparar Guardrails de suspensión.
LÓGICA DE ALERTAS:
    1. DATA_SILENCE: 0 transacciones en el día.
    2. DATA_QUALITY_BREACH: Tasa de nulos en device_id > 5%.
    3. TRAFFIC_DEVIATION: Ticket promedio diario excede en 20% el teórico.
    4. NEGATIVE_FRAUD_BALANCE: Saldo proyectado de cohortes abiertas < 0.
"""

import sys
import argparse
import sqlite3
import random
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pathlib import Path

# Resolución estricta de rutas y carga de matriz genética
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(REPO_ROOT))
import config

DB_PATH = REPO_ROOT / 'data' / 'operacional' / 'gtee_operational.db'

# Curva de maduración IBNR estática (Si no existe en config.py, se usa esta por defecto)
# Representa el % de contracargos que ya llegaron según los meses transcurridos.
FALLBACK_MATURATION_CURVE = {
    0: 0.10,  # Mes actual: Solo llegó el 10% del fraude real
    1: 0.25,  # 1 mes atrás: Llegó el 25%
    2: 0.60,  # 2 meses atrás: Llegó el 60%
    3: 0.90,  # 3 meses atrás: Llegó el 90%
    4: 1.00   # 4 meses o más: Cohorte 100% madura
}

def evaluate_guardrails(target_date_str):
    target_date = datetime.strptime(target_date_str, '%Y-%m-%d')
    # Semilla diaria: solo afecta a los log_id (UUID) del Guardrails_Log
    random.seed(config.seed_diaria(target_date_str, config.SEED_OFFSET_MICROBATCH))
    print("\n=======================================================")
    print(f"[*] MOTOR MICRO-BATCH: EVALUACIÓN DE GUARDRAILS ({target_date_str})")
    print("=======================================================")
    
    if not DB_PATH.exists():
        raise FileNotFoundError(f"[-] Error: Base de datos no encontrada en {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    
    # Variables de control temporal
    start_of_day = target_date.strftime('%Y-%m-%dT00:00:00')
    end_of_day = target_date.strftime('%Y-%m-%dT23:59:59')
    four_months_ago = (target_date - relativedelta(months=4)).strftime('%Y-%m-01T00:00:00')

    # Extraer comercios ya suspendidos para evitar Alert Fatigue (Respetando el límite temporal)
    try:
        query_suspendidos = f"""
            SELECT DISTINCT merchant_id 
            FROM Guardrails_Log 
            WHERE action_taken = 'COVERAGE_SUSPENDED'
            AND triggered_date <= '{start_of_day}'
        """
        df_suspendidos = pd.read_sql_query(query_suspendidos, conn)
        comercios_suspendidos = df_suspendidos['merchant_id'].tolist()
    except pd.errors.DatabaseError:
        # Si la tabla recién se crea o no tiene registros, la lista inicia vacía
        comercios_suspendidos = []

        
    # -------------------------------------------------------------------------
    # PASO 1: EVALUACIÓN VOLUMÉTRICA DIARIA (LOTE DE 24 HORAS)
    # -------------------------------------------------------------------------
    query_daily = f"""
        SELECT merchant_id, usd_amount, device_id, ip_address, document 
        FROM Transactions_Gtee 
        WHERE transaction_timestamp BETWEEN '{start_of_day}' AND '{end_of_day}'
    """
    df_daily = pd.read_sql_query(query_daily, conn)
    
    alertas_a_insertar = []

    for merchant_id in config.MERCHANT_ORDER:
        if merchant_id in comercios_suspendidos:
            continue # Ignorar: El merchant ya está suspendido contractualmente

        df_merch_daily = df_daily[df_daily['merchant_id'] == merchant_id]
        # Regla 1: Silencio de Datos (Data Silence)
        if df_merch_daily.empty:
            alertas_a_insertar.append({
                'log_id': config.uuid_determinista(),
                'merchant_id': merchant_id,
                'alert_type': 'DATA_SILENCE',
                'triggered_date': target_date.strftime('%Y-%m-%dT%H:%M:%S'),
                'action_taken': 'MANUAL_REVIEW_REQUIRED'
            })
            continue # Si no hay datos, no se pueden evaluar métricas de calidad
            
# Regla 2: Calidad de Datos (API Outage / Nulos)
        total_tx = len(df_merch_daily)
        campos_criticos = ['device_id', 'ip_address', 'document']
        
        breach_detectado = False
        for campo in campos_criticos:
            null_rate = df_merch_daily[campo].isnull().sum() / total_tx
            if null_rate > 0.05:
                breach_detectado = True
                break # Un solo campo roto es suficiente para suspender
                
        if breach_detectado:
            alertas_a_insertar.append({
                'log_id': config.uuid_determinista(),
                'merchant_id': merchant_id,
                'alert_type': 'DATA_QUALITY_BREACH',
                'triggered_date': target_date.strftime('%Y-%m-%dT%H:%M:%S'),
                'action_taken': 'COVERAGE_SUSPENDED'
            })
            
        # Regla 3: Desviación de Tráfico (Ticket Promedio)
        teoric_avg_ticket = config.MERCHANTS_CONFIG[merchant_id]['avg_ticket']
        real_avg_ticket = df_merch_daily['usd_amount'].mean()
        desvio_pct = abs(real_avg_ticket - teoric_avg_ticket) / teoric_avg_ticket
        
        if desvio_pct > 0.20:
            alertas_a_insertar.append({
                'log_id': config.uuid_determinista(),
                'merchant_id': merchant_id,
                'alert_type': 'TRAFFIC_DEVIATION',
                'triggered_date': target_date.strftime('%Y-%m-%dT%H:%M:%S'),
                'action_taken': 'LISTEN_MODE_ACTIVATED'
            })

# -------------------------------------------------------------------------
    # PASO 2: EVALUACIÓN ACTUARIAL IBNR (COHORTES ABIERTAS)
    # -------------------------------------------------------------------------
    # JOIN dimensional: Calculamos el fee real y traemos los costos operativos
    query_cohorts = f"""
        SELECT 
            t.merchant_id,
            strftime('%Y-%m', t.transaction_timestamp) as cohort_month,
            SUM(t.usd_amount) as total_tpv,
            SUM(t.usd_amount * (m.fee_assigned / 100.0)) as total_fees,
            SUM(c.cbk_usd_amount) as total_cbk_raw,
            COUNT(c.chargeback_id) as total_cbk_count,
            MAX(m.cbk_process_cost) as unit_cbk_cost,
            MAX(m.analyst_cost) as monthly_analyst_cost
        FROM Transactions_Gtee t
        JOIN Merchants_Gtee m ON t.merchant_id = m.merchant_id
        LEFT JOIN Chargebacks_Gtee c ON t.transaction_id = c.transaction_id
        WHERE t.transaction_timestamp >= '{four_months_ago}'
        AND t.status = 'APPROVED'
        GROUP BY t.merchant_id, cohort_month
    """
    df_cohorts = pd.read_sql_query(query_cohorts, conn)
    
    # Rellenar nulos para cohortes sin contracargos
    df_cohorts['total_cbk_raw'] = df_cohorts['total_cbk_raw'].fillna(0)
    df_cohorts['total_cbk_count'] = df_cohorts['total_cbk_count'].fillna(0)

    for merchant_id in config.MERCHANT_ORDER:
        if merchant_id in comercios_suspendidos:
            continue # Ignorar: El merchant ya está suspendido contractualmente
        
        df_merch_cohorts = df_cohorts[df_cohorts['merchant_id'] == merchant_id]
        
        balance_negativo_detectado = False
        
        for _, row in df_merch_cohorts.iterrows():
            cohort_str = row['cohort_month'] # Formato 'YYYY-MM'
            cohort_date = datetime.strptime(cohort_str, '%Y-%m')
            
            # Calcular edad de la cohorte en meses respecto a la fecha objetivo
            month_diff = (target_date.year - cohort_date.year) * 12 + (target_date.month - cohort_date.month)
            
            # Limitar índice al máximo definido en la curva
            maturation_idx = min(month_diff, 4)
            
            # Intentar usar la curva de config, si falla usar el fallback
            try:
                maturation_factor = config.CBK_MATURATION_CURVE[maturation_idx]
            except (AttributeError, KeyError):
                # Se activa si la variable no existe o si falta el índice (ej. llave 0)
                maturation_factor = FALLBACK_MATURATION_CURVE[maturation_idx]
                
            # Proyección Actuarial IBNR y de Costos
            fees = row['total_fees']
            tpv_aprobado = row['total_tpv']
            cbk_raw = row['total_cbk_raw']
            cbk_count = row['total_cbk_count']
            
            factor_seguro = max(maturation_factor, 0.01) 
            
            # A. Proyección Empírica
            projected_loss_empirica = cbk_raw / factor_seguro
            projected_count_empirica = cbk_count / factor_seguro

            # B. Proyección Teórica (Piso IBNR)
            tasa_base = config.MERCHANTS_CONFIG[merchant_id]['cbk_rate_base']
            ticket_medio = config.MERCHANTS_CONFIG[merchant_id]['avg_ticket']
            
            expected_loss_teorica = tpv_aprobado * tasa_base
            expected_count_teorica = expected_loss_teorica / ticket_medio

            # C. Asignación Conservadora
            projected_loss = max(projected_loss_empirica, expected_loss_teorica)
            projected_cbk_count = max(projected_count_empirica, expected_count_teorica)
            
            # Prorrateo temporal del costo fijo operativo
            if month_diff == 0:
                # Mes en curso: se cobra la fracción de los días operados
                dias_transcurridos = target_date.day
                costo_fijo_aplicable = row['monthly_analyst_cost'] * (dias_transcurridos / 30.0)
            else:
                # Meses anteriores: se asume el mes completo
                costo_fijo_aplicable = row['monthly_analyst_cost']
            
            # Deducción de costos operativos totales (Fijo prorrateado + Variable)
            total_process_cost = projected_cbk_count * row['unit_cbk_cost']
            analyst_cost = costo_fijo_aplicable + (projected_cbk_count * config.COSTO_VARIABLE_ANALISTA_CBK)
            
            fraud_balance_proyectado = fees - projected_loss - total_process_cost - analyst_cost
            
            # --- INICIO BLOQUE DE AUDITORÍA EN CONSOLA ---
            print(f"    [Auditoría IBNR] Merchant: {merchant_id} | Cohorte: {cohort_str}")
            print(f"      - Fees recaudados:       ${fees:,.2f}")
            print(f"      - Pérdida proyectada:    ${projected_loss:,.2f} (Factor maduración: {factor_seguro:.2f})")
            print(f"      - Costo Proc. Disputas:  ${total_process_cost:,.2f} (Cant. Proyectada: {projected_cbk_count:,.1f})")
            print(f"      - Costo Fijo Analista:   ${analyst_cost:,.2f}")
            print(f"      => FRAUD BALANCE:        ${fraud_balance_proyectado:,.2f}")
            print("      " + "-"*50)
            # --- FIN BLOQUE DE AUDITORÍA ---
            
            if fraud_balance_proyectado < 0:
                balance_negativo_detectado = True
                break # Basta con que una sola cohorte esté rota para suspender
                
        if balance_negativo_detectado:
            alertas_a_insertar.append({
                'log_id': config.uuid_determinista(),
                'merchant_id': merchant_id,
                'alert_type': 'NEGATIVE_FRAUD_BALANCE',
                'triggered_date': target_date.strftime('%Y-%m-%dT%H:%M:%S'),
                'action_taken': 'COVERAGE_SUSPENDED'
            })

    # -------------------------------------------------------------------------
    # PASO 3: PERSISTENCIA INMUTABLE (LOG DE AUDITORÍA)
    # -------------------------------------------------------------------------
    if alertas_a_insertar:
        df_alerts = pd.DataFrame(alertas_a_insertar)
        try:
            df_alerts.to_sql('Guardrails_Log', con=conn, if_exists='append', index=False)
            print(f"[!] ATENCIÓN: Se insertaron {len(alertas_a_insertar)} alertas en Guardrails_Log.")
            for _, alert in df_alerts.iterrows():
                # Inyección del ícono de alerta visual en el output de consola
                print(f"    -> 🚨 [{alert['merchant_id']}] {alert['alert_type']} | Acción: {alert['action_taken']}")
        except sqlite3.IntegrityError as e:
            print(f"[-] Error de integridad al insertar en Guardrails_Log: {e}")
    else:
        print("[+] Operación limpia. No se detectaron vulneraciones de Guardrails en este lote.")

    conn.close()
    print("=======================================================\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Motor Micro-batch: Alertas y Guardrails')
    parser.add_argument('--target_date', type=str, required=True, help='Fecha virtual (YYYY-MM-DD)')
    args = parser.parse_args()
    
    evaluate_guardrails(args.target_date)