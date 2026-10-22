import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# =============================================================================
# 1. CONFIGURACIÓN DE RUTAS Y REGLAS DE NEGOCIO
# =============================================================================
# Determina e inyecta la raíz del proyecto retrocediendo desde src/bloque_1_pricing/
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(REPO_ROOT))

import config

INPUT_SIM_FILE = REPO_ROOT / "data" / "outputs" / "portfolio_simulations.pkl"
OUTPUT_PLOT_PORTFOLIO = REPO_ROOT / "data" / "outputs" / "var_portafolio_agregado.png"
OUTPUT_PLOT_COMPARISON = REPO_ROOT / "data" / "outputs" / "var_comparativa_densidad.png"
OUTPUT_PLOT_HEATMAP = REPO_ROOT / "data" / "outputs" / "heatmap_correlacion.png"
# Contrato de interfaz con el Bloque 2 (dataset_B_generator.py lo consume)
OUTPUT_FEES = REPO_ROOT / "data" / "outputs" / "fees_optimos.json"

MARK_UP_OPERATIVO = 1.20
PERCENTIL_PRICING = 95
PERCENTIL_ESTRES = 99

def main():
    print("[*] Iniciando motor de derivación de Pricing (Chargeback Guarantee)...")
    
    # =============================================================================
    # 2. CARGA DE RESULTADOS ESTOCÁSTICOS BINARIOS
    # =============================================================================
    if not INPUT_SIM_FILE.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {INPUT_SIM_FILE}")
        
    resultados_sim = pd.read_pickle(INPUT_SIM_FILE)
    impacto_total_merchants = resultados_sim['impacto_total_merchants']
    perdida_portafolio_agregada = resultados_sim['perdida_portafolio_agregada']
    matriz_corr = resultados_sim['matriz_correlacion_empirica']
    
    # =============================================================================
    # 3. CÁLCULO DE VALUE AT RISK (VaR) Y TAIL RISK (CVaR)
    # =============================================================================
    # Extracción vectorizada de percentiles sobre eje 1 (las 10.000 iteraciones)
    var_95_individual = np.percentile(impacto_total_merchants, PERCENTIL_PRICING, axis=1)
    var_99_individual = np.percentile(impacto_total_merchants, PERCENTIL_ESTRES, axis=1)
    
    # Cálculo para el portafolio agregado
    var_95_portafolio = np.percentile(perdida_portafolio_agregada, PERCENTIL_PRICING)
    var_99_portafolio = np.percentile(perdida_portafolio_agregada, PERCENTIL_ESTRES)
    
    # Expected Shortfall (CVaR 99%)
    cvar_99_portafolio = np.mean(perdida_portafolio_agregada[perdida_portafolio_agregada > var_99_portafolio])
    
    # Demostración de subaditividad de Markowitz
    suma_var_99_individuales = np.sum(var_99_individual)
    ahorro_capital_covarianza = suma_var_99_individuales - var_99_portafolio

    # =============================================================================
    # 4. DERIVACIÓN DEL FEE ÓPTIMO POR MERCHANT (REGLAS DE NEGOCIO)
    # =============================================================================
    # Mantenemos la integridad referenciando el diccionario maestro de configuración
    tpv_vector = np.array([config.MERCHANTS_CONFIG[m]['tpv_base_usd'] for m in config.MERCHANT_ORDER])
    
    # Aplicación del Mark-up para asegurar Fraud Balance positivo
    precio_objetivo_usd = var_95_individual * MARK_UP_OPERATIVO
    fee_optimo_porcentaje = (precio_objetivo_usd / tpv_vector) * 100

    # =============================================================================
    # 5. REPORTE DE RESULTADOS EN TERMINAL
    # =============================================================================
    print("-" * 75)
    print(f"{'MERCHANT':<15} | {'VaR 95% (USD)':<15} | {'PRECIO (USD)':<15} | {'FEE ÓPTIMO (%)'}")
    print("-" * 75)
    for i, merchant in enumerate(config.MERCHANT_ORDER):
        print(f"{merchant:<15} | ${var_95_individual[i]:<14,.2f} | ${precio_objetivo_usd[i]:<14,.2f} | {fee_optimo_porcentaje[i]:.3f}%")
    print("-" * 75)
    
    print(f"\n[*] VALIDACIÓN DE CAPITAL Y TAIL RISK (99%)")
    print(f"Suma de Reservas Aisladas:      ${suma_var_99_individuales:,.2f}")
    print(f"Reserva de Portafolio (VaR):    ${var_99_portafolio:,.2f}")
    print(f"Ahorro de Capital (Subaditividad): ${ahorro_capital_covarianza:,.2f}")
    print(f"Expected Shortfall (CVaR 99%):  ${cvar_99_portafolio:,.2f}")

    # =============================================================================
    # 5.1 PERSISTENCIA DEL FEE ÓPTIMO (INPUT DEL BLOQUE 2)
    # =============================================================================
    # Se redondea a 3 decimales, la misma precisión reportada en terminal.
    OUTPUT_FEES.parent.mkdir(parents=True, exist_ok=True)
    fees_optimos = {m: round(float(fee_optimo_porcentaje[i]), 3) for i, m in enumerate(config.MERCHANT_ORDER)}
    with open(OUTPUT_FEES, 'w', encoding='utf-8') as f:
        json.dump(fees_optimos, f, indent=4)
    print(f"\n[*] Fees óptimos persistidos en: {OUTPUT_FEES}")

    # =============================================================================
    # 6. EXPORTACIÓN DE VISUALIZACIONES ANALÍTICAS (SUBADITIVIDAD)
    # =============================================================================
    if not OUTPUT_PLOT_PORTFOLIO.parent.exists():
        OUTPUT_PLOT_PORTFOLIO.parent.mkdir(parents=True, exist_ok=True)

    # GRÁFICO 1: Matriz de Correlación (Heatmap)
    plt.figure(figsize=(8, 6))
    sns.heatmap(matriz_corr, annot=True, cmap='coolwarm', vmin=-1, vmax=1, 
                xticklabels=config.MERCHANT_ORDER, yticklabels=config.MERCHANT_ORDER)
    plt.title('Matriz de Correlación Empírica (Dataset A)')
    plt.tight_layout()
    plt.savefig(OUTPUT_PLOT_HEATMAP, dpi=300)
    plt.close()

    # GRÁFICO 2: Distribución de Portafolio Agregado
    plt.figure(figsize=(10, 6))
    plt.hist(perdida_portafolio_agregada, bins=100, color='#99ccff', alpha=0.7)
    plt.axvline(var_99_portafolio, color='blue', linestyle='solid', linewidth=2, label=f'VaR 99% Portafolio: ${var_99_portafolio:,.0f}')
    plt.axvline(cvar_99_portafolio, color='purple', linestyle='dotted', linewidth=2, label=f'CVaR 99% (Expected Shortfall): ${cvar_99_portafolio:,.0f}')
    plt.axvline(suma_var_99_individuales, color='black', linestyle='dashed', linewidth=2, label=f'Suma VaR 99% Aislados: ${suma_var_99_individuales:,.0f}')
    plt.title('Distribución de Pérdidas Financieras: Portafolio Agregado')
    plt.xlabel('Pérdida Financiera Total (Fraude + OPEX en USD)')
    plt.ylabel('Frecuencia (Iteraciones)')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_PLOT_PORTFOLIO, dpi=300)
    plt.close()

    # GRÁFICO 3: Comparativa de Forma (Densidad KDE)
    idx_retail_2_ar = 3
    perdida_retail_2 = impacto_total_merchants[idx_retail_2_ar, :]
    
    plt.figure(figsize=(10, 6))
    sns.kdeplot(perdida_retail_2, color='red', label='Retail_2 AR (Aislado)', fill=True, alpha=0.2)
    sns.kdeplot(perdida_portafolio_agregada, color='blue', label='Portafolio Agregado', fill=True, alpha=0.2)
    plt.title('Comparativa de Densidad de Probabilidad (Absorción de Volatilidad)')
    plt.xlabel('Pérdida Financiera Total (USD)')
    plt.ylabel('Densidad de Probabilidad')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_PLOT_COMPARISON, dpi=300)
    plt.close()

    print(f"\n[*] Gráficos exportados exitosamente en directorio data/outputs/")

if __name__ == "__main__":
    main()