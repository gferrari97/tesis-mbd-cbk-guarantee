"""
PROYECTO: Tesis Máster Big Data ORT - Guzmán Ferrari
SCRIPT: run_pipeline.py
OBJETIVO: 
    Orquestador secuencial para simular el paso del tiempo en el entorno local.
    Ejecuta la tubería completa (Generación -> Chargeback Lag -> Guardrails) 
    día por día en un bucle cerrado.
"""

import subprocess
import pandas as pd
import sys
from pathlib import Path

# =============================================================================
# CONFIGURACIÓN DEL ESPACIO TEMPORAL (RANGO DE SIMULACIÓN)
# =============================================================================
# Continuamos desde el último día que simulamos a mano
START_DATE = '2026-08-17'
END_DATE = '2026-08-31'

BASE_DIR = Path(__file__).resolve().parent

scripts_to_run = [
    "dataset_B_generator.py",
    "chargeback_lag_simulator.py",
    "microbatch_engine.py"
]

def run_simulation():
    date_range = pd.date_range(start=START_DATE, end=END_DATE)
    
    for current_date in date_range:
        target_date_str = current_date.strftime('%Y-%m-%d')
        print(f"\n{'='*70}")
        print(f"🚀 ORQUESTANDO LOTE DIARIO: {target_date_str}")
        print(f"{'='*70}")
        
        for script in scripts_to_run:
            script_path = BASE_DIR / script
            
            # Sys.executable fuerza el uso del Python del entorno virtual (.venv_tesis)
            comando = [sys.executable, str(script_path), "--target_date", target_date_str]
            
            # Ejecutar el subproceso bloqueando hasta que termine (sincrónico)
            resultado = subprocess.run(comando, capture_output=False, text=True)
            
            # Control de fallos de infraestructura o integridad referencial
            if resultado.returncode != 0:
                print(f"\n[!] FALLO CRÍTICO DE EJECUCIÓN en {script} para la fecha {target_date_str}.")
                print("[!] Abortando el pipeline para proteger la integridad de gtee_operational.db.")
                return

if __name__ == "__main__":
    run_simulation()