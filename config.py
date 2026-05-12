"""
Configuración central del proyecto.
"""
from pathlib import Path

ROOT = Path(__file__).parent

# ── Carpetas ───────────────────────────────────────────────────────────────────
INPUT_DIR  = ROOT / "input"
DATA_DIR   = ROOT / "data"
RAW_DIR    = DATA_DIR / "raw"
OUTPUT_DIR = ROOT / "output"
LOGS_DIR   = ROOT / "logs"

# ── Configuración por fuente ───────────────────────────────────────────────────
# date_format:
#   "YYYYMM"     → columna tipo "202305"  (año+mes, sin día)
#   "DD-MM-YYYY" → columna tipo "15-03-2026"
#   None         → pandas infiere automáticamente

SOURCES = {
    "temusystem": {
        "pattern":     "temusystem",
        "primary_key": ["Tracking number"],
        "date_column": "Settlement month(eg:202305)",
        "date_format": "YYYYMM",          # formato especial año+mes
        "sheet":       0,
        "parquet_dir": DATA_DIR / "temusystem",
    },
    "proforma": {
        "pattern":     "proforma",
        "primary_key": ["NROGUIA"],
        "date_column": "FECHA",
        "date_format": "DD-MM-YYYY",
        "sheet":       0,
        "parquet_dir": DATA_DIR / "proforma",
    },
}

PARQUET_COMPRESSION = "snappy"

# ── Reconciliación entre bases ─────────────────────────────────────────────────
# Cómo cruzar las dos bases: qué columna de cada una representa el mismo ID.
RECONCILIATION = {
    "temusystem_key": "Tracking number",  # columna ID en temusystem
    "proforma_key":   "NROGUIA",          # columna ID en proforma
}
