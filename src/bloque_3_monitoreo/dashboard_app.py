"""
PROYECTO: Tesis Máster Big Data ORT - Guzmán Ferrari
SCRIPT: dashboard_app.py
OBJETIVO: Interfaz visual de página única para monitoreo operativo y financiero (Soporte IBNR y Tooltips Nativos).
"""

import streamlit as st
import sqlite3
import pandas as pd
import altair as alt
from pathlib import Path

# Configuración de página
st.set_page_config(page_title="Chargeback Guarantee Monitor", layout="wide")

# Resolución de ruta
CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent.parent
DB_PATH = REPO_ROOT / 'data' / 'operacional' / 'gtee_operational.db'

@st.cache_data
def load_and_process_data():
    """Extrae y procesa la serie temporal transaccional y aplica la curva IBNR."""
    query_tx = """
        SELECT 
            DATE(t.transaction_timestamp) as date,
            STRFTIME('%Y-%m', t.transaction_timestamp) as month,
            t.merchant_id,
            m.fee_assigned,
            m.cbk_process_cost,
            m.analyst_cost,
            COUNT(t.transaction_id) as tx_qty,
            SUM(CASE WHEN t.status = 'APPROVED' THEN t.usd_amount ELSE 0 END) as tpv,
            AVG(t.usd_amount) as avg_ticket,
            SUM(CASE WHEN t.status = 'REJECTED' THEN 1 ELSE 0 END) * 100.0 / COUNT(t.transaction_id) as rejection_rate_pct,
            SUM(CASE WHEN t.device_id IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(t.transaction_id) as null_device_pct,
            SUM(CASE WHEN t.ip_address IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(t.transaction_id) as null_ip_pct,
            SUM(CASE WHEN t.document IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(t.transaction_id) as null_doc_pct
        FROM Transactions_Gtee t
        JOIN Merchants_Gtee m ON t.merchant_id = m.merchant_id
        GROUP BY date, month, t.merchant_id
    """
    
    query_cbk = """
        SELECT 
            DATE(t.transaction_timestamp) as date,
            t.merchant_id,
            COUNT(c.chargeback_id) as cbk_qty,
            SUM(c.cbk_usd_amount) as cbk_usd
        FROM Chargebacks_Gtee c
        JOIN Transactions_Gtee t ON c.transaction_id = t.transaction_id
        GROUP BY date, t.merchant_id
    """
    
    query_alerts = """
        SELECT merchant_id, alert_type, triggered_date, action_taken
        FROM Guardrails_Log
        ORDER BY triggered_date DESC
    """

    with sqlite3.connect(DB_PATH) as conn:
        df_tx = pd.read_sql_query(query_tx, conn)
        df_cbk = pd.read_sql_query(query_cbk, conn)
        df_alerts = pd.read_sql_query(query_alerts, conn)

    # Cruce de datos y cálculo financiero base
    df = pd.merge(df_tx, df_cbk, on=['date', 'merchant_id'], how='left').fillna(0)
    df['revenue'] = df['tpv'] * (df['fee_assigned'] / 100.0)
    df['daily_opex'] = (df['analyst_cost'] / 30.0) + (df['cbk_qty'] * df['cbk_process_cost'])
    
    # Cálculo de métricas nominales
    df['nominal_fraud_balance'] = df['revenue'] - df['cbk_usd'] - df['daily_opex']
    df['cbk_rate_pct'] = (df['cbk_usd'] / df['tpv']) * 100
    df['cbk_rate_pct'] = df['cbk_rate_pct'].fillna(0)
    
    # Aplicación de curva IBNR para Fraud Balance Proyectado
    df['date_dt'] = pd.to_datetime(df['date'])
    max_date = df['date_dt'].max()
    df['tx_month_dt'] = pd.to_datetime(df['month'] + '-01')
    
    # Cálculo de antigüedad de la cohorte en meses
    df['months_aged'] = (max_date.year - df['tx_month_dt'].dt.year) * 12 + (max_date.month - df['tx_month_dt'].dt.month) + 1
    
    def apply_ibnr(age):
        if age == 1: return 0.25
        elif age == 2: return 0.70
        elif age == 3: return 0.95
        else: return 1.00
        
    df['ibnr_factor'] = df['months_aged'].apply(apply_ibnr)
    df['projected_cbk_usd'] = df['cbk_usd'] / df['ibnr_factor']
    df['projected_fraud_balance'] = df['revenue'] - df['projected_cbk_usd'] - df['daily_opex']
    
    # Tasa de fraude proyectada IBNR
    df['projected_cbk_rate_pct'] = (df['projected_cbk_usd'] / df['tpv']) * 100
    df['projected_cbk_rate_pct'] = df['projected_cbk_rate_pct'].fillna(0)

    # Cálculo acumulado proyectado
    df = df.sort_values(by=['merchant_id', 'date'])
    df['fb_acumulado_proyectado'] = df.groupby('merchant_id')['projected_fraud_balance'].cumsum()
    
    return df, df_alerts

def load_last_transactions(merchant_filter, month_filter):
    """Extrae transacciones granulares con filtro de Merchant y Mes."""
    query = """
        SELECT transaction_id, merchant_id, usd_amount, transaction_timestamp, status, device_id, ip_address, document
        FROM Transactions_Gtee
        WHERE 1=1
    """
    if merchant_filter != 'Portafolio Global':
        query += f" AND merchant_id = '{merchant_filter}'"
    if month_filter != 'Histórico Completo':
        query += f" AND STRFTIME('%Y-%m', transaction_timestamp) = '{month_filter}'"
        
    query += " ORDER BY transaction_timestamp DESC LIMIT 10"
    
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(query, conn)
    return df

# Extracción de datos centralizada
df_master, df_alerts = load_and_process_data()

# =============================================================================
# ENCABEZADO Y FILTROS GLOBALES
# =============================================================================
st.title("Monitoreo Operativo - Chargeback Guarantee")
st.markdown("Auditoría de rentabilidad actuarial (IBNR) y seguimiento de anomalías transaccionales.")

col_filtro1, col_filtro2 = st.columns(2)
with col_filtro1:
    meses_disponibles = ['Histórico Completo'] + sorted(list(df_master['month'].unique()))
    mes_seleccionado = st.selectbox("Filtrar por Mes", meses_disponibles)
with col_filtro2:
    merchants_disponibles = ['Portafolio Global'] + sorted(list(df_master['merchant_id'].unique()))
    merchant_seleccionado = st.selectbox("Filtrar por Merchant", merchants_disponibles)

# Aplicación de filtros
df_filtered = df_master.copy()
if mes_seleccionado != 'Histórico Completo':
    df_filtered = df_filtered[df_filtered['month'] == mes_seleccionado]
if merchant_seleccionado != 'Portafolio Global':
    df_filtered = df_filtered[df_filtered['merchant_id'] == merchant_seleccionado]

# =============================================================================
# 1. KPIs FINANCIEROS (Modelo Actuarial IBNR)
# =============================================================================
st.subheader("1. Estado Financiero (Proyección IBNR)")

kpi_tpv = df_filtered['tpv'].sum()
kpi_rev = df_filtered['revenue'].sum()
kpi_cost_nominal = df_filtered['cbk_usd'].sum() + df_filtered['daily_opex'].sum()
kpi_cost_proyectado = df_filtered['projected_cbk_usd'].sum() + df_filtered['daily_opex'].sum()

kpi_fb_proyectado = df_filtered['projected_fraud_balance'].sum()
kpi_fb_nominal = df_filtered['nominal_fraud_balance'].sum()

fb_color = "#00cc66" if kpi_fb_proyectado >= 0 else "#ff4b4b"

col1, col2, col3, col4 = st.columns(4)
col1.metric("TPV Aprobado", f"${kpi_tpv:,.0f}")
col2.metric("Ingresos (Fees)", f"${kpi_rev:,.0f}")
col3.metric("Costos Proy. (IBNR)", f"${kpi_cost_proyectado:,.0f}", f"Nominal: ${kpi_cost_nominal:,.0f}", delta_color="inverse")
col4.markdown(f"<span style='font-size: 0.9em;'>Fraud Balance Proyectado</span><br><span style='font-size: 2.0em; font-weight: bold; color: {fb_color};'>${kpi_fb_proyectado:,.0f}</span>", unsafe_allow_html=True)
col4.markdown(f"<span style='font-size: 0.9em; color: gray;'>↑ Nominal: ${kpi_fb_nominal:,.0f}</span>", unsafe_allow_html=True)

st.markdown("---")

st.markdown("**Evolución del Fraud Balance Acumulado Proyectado (USD)**")
chart_fb_data = df_filtered[['date', 'merchant_id', 'fb_acumulado_proyectado']].copy()

line_fb = alt.Chart(chart_fb_data).mark_line(interpolate='monotone', point=True).encode(
    x=alt.X('date:T', title='Fecha'),
    y=alt.Y('fb_acumulado_proyectado:Q', title='Fraud Balance (USD)', axis=alt.Axis(format='d')),
    color=alt.Color('merchant_id:N', title='Merchant'),
    tooltip=[
        alt.Tooltip('date:T', title='Fecha'), 
        alt.Tooltip('merchant_id:N', title='Merchant'), 
        alt.Tooltip('fb_acumulado_proyectado:Q', title='Balance Proyectado (USD)', format=',.0f')
    ]
)
st.altair_chart(line_fb, width='stretch')

# =============================================================================
# 2. AUDITORÍA OPERACIONAL Y TASA DE RIESGO
# =============================================================================
st.subheader("2. Auditoría Operacional y Comportamiento")

if merchant_seleccionado != 'Portafolio Global':
    st.markdown(f"**Tasa de Fraude (Nominal y Proyectada IBNR) vs Fee Contratado ({merchant_seleccionado})**")
    
    base_rates = alt.Chart(df_filtered).encode(x=alt.X('date:T', title='Fecha'))
    
    line_cbk_proj = base_rates.mark_line(color='#ff4b4b', point=True).encode(
        y=alt.Y('projected_cbk_rate_pct:Q', title='Porcentaje (%)', axis=alt.Axis(format=',.2f')),
        tooltip=[alt.Tooltip('date:T', title='Fecha'), alt.Tooltip('projected_cbk_rate_pct:Q', title='Tasa Proyectada IBNR (%)', format=',.2f')]
    )
    
    line_cbk_nom = base_rates.mark_line(color='#ffcccc', strokeDash=[2, 2], point=True).encode(
        y=alt.Y('cbk_rate_pct:Q'),
        tooltip=[alt.Tooltip('date:T', title='Fecha'), alt.Tooltip('cbk_rate_pct:Q', title='Tasa Nominal Realizada (%)', format=',.2f')]
    )
    
    line_fee = base_rates.mark_line(color='#0068c9', strokeDash=[5, 5]).encode(
        y=alt.Y('fee_assigned:Q'),
        tooltip=[alt.Tooltip('fee_assigned:Q', title='Fee Asignado (%)', format=',.2f')]
    )
    
    chart_rates = (line_cbk_proj + line_cbk_nom + line_fee).properties(height=300)
    st.altair_chart(chart_rates, width='stretch')

st.markdown("#### Métricas de Tráfico")
col_op1, col_op2, col_op3 = st.columns(3)

with col_op1:
    st.markdown("**Volumen (DATA_SILENCE)**")
    chart_vol = df_filtered[['date', 'merchant_id', 'tx_qty']].copy()
    line_vol = alt.Chart(chart_vol).mark_line(interpolate='monotone', point=True).encode(
        x=alt.X('date:T', title='Fecha'),
        y=alt.Y('tx_qty:Q', title='Cantidad Transacciones', axis=alt.Axis(format='d')),
        color='merchant_id:N',
        tooltip=[alt.Tooltip('date:T', title='Fecha'), alt.Tooltip('merchant_id:N', title='Merchant'), alt.Tooltip('tx_qty:Q', title='Volumen', format='d')]
    )
    st.altair_chart(line_vol, width='stretch')

with col_op2:
    st.markdown("**Ticket Promedio (TRAFFIC_DEVIATION)**")
    chart_ticket = df_filtered[['date', 'merchant_id', 'avg_ticket']].copy()
    line_ticket = alt.Chart(chart_ticket).mark_line(interpolate='monotone', point=True).encode(
        x=alt.X('date:T', title='Fecha'),
        y=alt.Y('avg_ticket:Q', title='Ticket Promedio (USD)', axis=alt.Axis(format='d')),
        color='merchant_id:N',
        tooltip=[alt.Tooltip('date:T', title='Fecha'), alt.Tooltip('merchant_id:N', title='Merchant'), alt.Tooltip('avg_ticket:Q', title='USD', format=',.0f')]
    )
    st.altair_chart(line_ticket, width='stretch')

with col_op3:
    st.markdown("**Rechazo Orgánico (Exógeno)**")
    chart_rej = df_filtered[['date', 'merchant_id', 'rejection_rate_pct']].copy()
    line_rej = alt.Chart(chart_rej).mark_line(interpolate='monotone', point=True).encode(
        x=alt.X('date:T', title='Fecha'),
        y=alt.Y('rejection_rate_pct:Q', title='% Decline Rate', axis=alt.Axis(format=',.1f')),
        color='merchant_id:N',
        tooltip=[alt.Tooltip('date:T', title='Fecha'), alt.Tooltip('merchant_id:N', title='Merchant'), alt.Tooltip('rejection_rate_pct:Q', title='% Rechazo', format=',.1f')]
    )
    st.altair_chart(line_rej, width='stretch')

# =============================================================================
# 3. CALIDAD DE DATOS (DATA QUALITY BREACH)
# =============================================================================
st.subheader("3. Calidad de Datos Contractual")
st.markdown("Seguimiento de campos obligatorios en el API de integración. Umbral de suspensión > 5%.")

col_dq1, col_dq2, col_dq3 = st.columns(3)

with col_dq1:
    st.markdown("**Nulos en Device ID**")
    chart_dev = df_filtered[['date', 'merchant_id', 'null_device_pct']].copy()
    line_dev = alt.Chart(chart_dev).mark_line(interpolate='monotone', point=True).encode(
        x=alt.X('date:T', title='Fecha'),
        y=alt.Y('null_device_pct:Q', title='% Nulos', axis=alt.Axis(format=',.1f')),
        color='merchant_id:N',
        tooltip=[alt.Tooltip('date:T', title='Fecha'), alt.Tooltip('merchant_id:N', title='Merchant'), alt.Tooltip('null_device_pct:Q', title='% Nulos', format=',.1f')]
    )
    st.altair_chart(line_dev, width='stretch')

with col_dq2:
    st.markdown("**Nulos en IP Address**")
    chart_ip = df_filtered[['date', 'merchant_id', 'null_ip_pct']].copy()
    line_ip = alt.Chart(chart_ip).mark_line(interpolate='monotone', point=True).encode(
        x=alt.X('date:T', title='Fecha'),
        y=alt.Y('null_ip_pct:Q', title='% Nulos', axis=alt.Axis(format=',.1f')),
        color='merchant_id:N',
        tooltip=[alt.Tooltip('date:T', title='Fecha'), alt.Tooltip('merchant_id:N', title='Merchant'), alt.Tooltip('null_ip_pct:Q', title='% Nulos', format=',.1f')]
    )
    st.altair_chart(line_ip, width='stretch')

with col_dq3:
    st.markdown("**Nulos en Documento**")
    chart_doc = df_filtered[['date', 'merchant_id', 'null_doc_pct']].copy()
    line_doc = alt.Chart(chart_doc).mark_line(interpolate='monotone', point=True).encode(
        x=alt.X('date:T', title='Fecha'),
        y=alt.Y('null_doc_pct:Q', title='% Nulos', axis=alt.Axis(format=',.1f')),
        color='merchant_id:N',
        tooltip=[alt.Tooltip('date:T', title='Fecha'), alt.Tooltip('merchant_id:N', title='Merchant'), alt.Tooltip('null_doc_pct:Q', title='% Nulos', format=',.1f')]
    )
    st.altair_chart(line_doc, width='stretch')

# =============================================================================
# 4. BITÁCORAS Y REGISTROS TRANSACTIONALES
# =============================================================================
st.subheader("4. Registros de Auditoría")

tab1, tab2 = st.tabs(["Bitácora de Suspensión (Guardrails)", "Últimas Transacciones Operadas"])

with tab1:
    df_alerts_disp = df_alerts.copy()
    if merchant_seleccionado != 'Portafolio Global':
        df_alerts_disp = df_alerts_disp[df_alerts_disp['merchant_id'] == merchant_seleccionado]

    if not df_alerts_disp.empty:
        st.dataframe(df_alerts_disp, width='stretch')
    else:
        st.success("Operación normal. No hay alertas críticas registradas para la selección actual.")

with tab2:
    df_last_tx = load_last_transactions(merchant_seleccionado, mes_seleccionado)
    if not df_last_tx.empty:
        df_last_tx['usd_amount'] = df_last_tx['usd_amount'].apply(lambda x: f"${x:,.0f}")
        st.dataframe(df_last_tx, width='stretch')
    else:
        st.warning("No hay transacciones registradas para el filtro seleccionado.")