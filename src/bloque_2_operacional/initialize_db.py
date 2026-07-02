import sqlite3
import os
from pathlib import Path

def initialize_operational_db():
    """
    Inicializa el esquema relacional para el MVP del producto Chargeback Guarantee.
    Crea los directorios necesarios y aplica PRAGMA foreign_keys.
    """
    
    # 1. Resolución dinámica de rutas (Asume que el script está en src/bloque2_operacional/)
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent.parent
    db_dir = project_root / 'data' / 'operacional'
    
    # Crear directorio si no existe
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / 'gtee_operational.db'
    
    print(f"[*] Verificando base de datos en:\n    {db_path}")
    if db_path.exists():
        print("[!] Advertencia: La base de datos ya existe. Conectando al esquema actual...")

    # 2. Conexión y Pragma
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Forzar la integridad referencial en SQLite (Crítico por sesión)
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 3. Ejecución de DDL (Tablas)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Merchants_Gtee (
            merchant_id TEXT PRIMARY KEY,
            industry TEXT NOT NULL,
            country TEXT NOT NULL,
            fee_assigned REAL NOT NULL,
            cbk_process_cost REAL NOT NULL,
            analyst_cost REAL NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Transactions_Gtee (
            transaction_id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL,
            usd_amount REAL NOT NULL,
            transaction_timestamp TEXT NOT NULL,
            status TEXT NOT NULL,
            device_id TEXT,
            ip_address TEXT,
            document TEXT,
            FOREIGN KEY (merchant_id) REFERENCES Merchants_Gtee(merchant_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Chargebacks_Gtee (
            chargeback_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL,
            cbk_usd_amount REAL NOT NULL,
            reason_code TEXT NOT NULL,
            cbk_timestamp TEXT NOT NULL,
            FOREIGN KEY (transaction_id) REFERENCES Transactions_Gtee(transaction_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Guardrails_Log (
            log_id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            triggered_date TEXT NOT NULL,
            action_taken TEXT NOT NULL,
            FOREIGN KEY (merchant_id) REFERENCES Merchants_Gtee(merchant_id)
        )
    ''')

    # 4. Despliegue de Índices
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_trans_merch_time 
        ON Transactions_Gtee(merchant_id, transaction_timestamp)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_cbk_trans 
        ON Chargebacks_Gtee(transaction_id)
    ''')

    conn.commit()
    
    # 5. Auditoría Interna
    cursor.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%';")
    schema_objects = cursor.fetchall()
    
    print("\n[+] Esquema validado con éxito. Objetos en base de datos:")
    for obj in schema_objects:
        print(f"    - {obj[1].upper()}: {obj[0]}")

    conn.close()

if __name__ == "__main__":
    initialize_operational_db()