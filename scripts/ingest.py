"""
ingest.py
─────────
Detecta el tipo de Excel por nombre de archivo (temusystem / proforma),
hace upsert en el parquet particionado correspondiente y reconstruye
el master de esa fuente.

Uso:
    python scripts/ingest.py                          # procesa todos los xlsx en input/
    python scripts/ingest.py input/temusystem_mar.xlsx
"""

import sys
import warnings
import logging
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import INPUT_DIR, RAW_DIR, LOGS_DIR, SOURCES, PARQUET_COMPRESSION

# ── Logging ────────────────────────────────────────────────────────────────────
LOGS_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOGS_DIR / f"ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
_stream_handler = logging.StreamHandler()
_stream_handler.stream = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1, closefd=False)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.FileHandler(log_file, encoding="utf-8"), _stream_handler],
)
log = logging.getLogger(__name__)


# ── Detección de fuente ────────────────────────────────────────────────────────

def detect_source(path: Path) -> dict | None:
    name = path.name.lower()
    for src_name, cfg in SOURCES.items():
        if cfg["pattern"].lower() in name:
            log.info(f"  Fuente detectada: {src_name}")
            return {"name": src_name, **cfg}
    return None


# ── Carga y validación ─────────────────────────────────────────────────────────

def load_xlsx(path: Path, sheet) -> pd.DataFrame:
    log.info(f"Leyendo {path.name} …")
    df = pd.read_excel(path, sheet_name=sheet, dtype_backend="numpy_nullable")
    log.info(f"  → {len(df):,} filas | {df.shape[1]} columnas")
    return df


def parse_date_column(series: pd.Series, fmt: str) -> pd.Series:
    """
    Normaliza la columna de fecha a datetime según el formato declarado en config.
    - "YYYYMM"     : "202305"  → 2023-05-01  (primer día del mes)
    - "DD-MM-YYYY" : "15-03-2026" → 2026-03-15
    - None         : pandas infiere
    """
    if fmt == "YYYYMM":
        # Puede venir como int (202305) o string; convertir a string y parsear
        return pd.to_datetime(series.astype(str).str.strip(), format="%Y%m", errors="coerce")
    elif fmt == "DD-MM-YYYY":
        return pd.to_datetime(series, dayfirst=True, errors="coerce")
    else:
        return pd.to_datetime(series, errors="coerce")


def validate(df: pd.DataFrame, source: dict) -> pd.DataFrame:
    pk       = source["primary_key"]
    date_col = source["date_column"]
    date_fmt = source.get("date_format")

    missing = [c for c in pk + [date_col] if c not in df.columns]
    if missing:
        raise ValueError(
            f"Columnas faltantes en '{source['name']}': {missing}\n"
            f"Columnas disponibles: {list(df.columns)}"
        )

    before = len(df)
    df = df.dropna(subset=pk)
    if len(df) < before:
        log.warning(f"  {before - len(df)} filas eliminadas por clave nula")

    df[date_col] = parse_date_column(df[date_col], date_fmt)
    bad = df[date_col].isna().sum()
    if bad:
        log.warning(f"  {bad} filas con fecha inválida (se excluirán)")
    df = df.dropna(subset=[date_col])

    df["_year"]  = df[date_col].dt.year.astype(int)
    df["_month"] = df[date_col].dt.month.astype(int)
    return df


# ── Upsert por partición ───────────────────────────────────────────────────────

def upsert_partition(df: pd.DataFrame, year: int, month: int, source: dict):
    pk      = source["primary_key"]
    part_dir = source["parquet_dir"] / f"year={year}" / f"month={month:02d}"
    part_dir.mkdir(parents=True, exist_ok=True)
    part_file = part_dir / "data.parquet"

    chunk = (
        df[(df["_year"] == year) & (df["_month"] == month)]
        .drop(columns=["_year", "_month"])
        .copy()
    )

    if part_file.exists():
        existing = pd.read_parquet(part_file)
        merged = (
            pd.concat([existing, chunk])
            .drop_duplicates(subset=pk, keep="last")
            .reset_index(drop=True)
        )
    else:
        merged = chunk.drop_duplicates(subset=pk, keep="last").reset_index(drop=True)

    merged.to_parquet(part_file, compression=PARQUET_COMPRESSION, index=False)
    log.info(f"  Partición {year}-{month:02d}: {len(merged):,} filas")


def rebuild_master(source: dict):
    """Une todas las particiones en un único parquet master para la fuente."""
    parquet_dir = source["parquet_dir"]
    master_path = parquet_dir / "master.parquet"
    parts = sorted(parquet_dir.rglob("data.parquet"))

    if not parts:
        log.warning(f"  Sin particiones para {source['name']}, master omitido")
        return

    pk = source["primary_key"]
    dfs = [pd.read_parquet(p) for p in parts]
    master = (
        pd.concat(dfs, ignore_index=True)
        .drop_duplicates(subset=pk, keep="last")
        .reset_index(drop=True)
    )
    master.to_parquet(master_path, compression=PARQUET_COMPRESSION, index=False)
    log.info(f"  Master '{source['name']}': {len(master):,} filas → {master_path.name}")


# ── Archivo raw ────────────────────────────────────────────────────────────────

def archive_raw(path: Path, source_name: str):
    dest_dir = RAW_DIR / source_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"{path.stem}_{ts}{path.suffix}"
    path.rename(dest)
    log.info(f"  Archivado → raw/{source_name}/{dest.name}")


# ── Proceso de un archivo ──────────────────────────────────────────────────────

def process_file(path: Path):
    log.info("-" * 60)
    log.info(f"Archivo: {path.name}")

    source = detect_source(path)
    if source is None:
        log.warning(f"  No se reconoce el tipo de archivo, se omite.")
        return

    df = load_xlsx(path, source["sheet"])
    df = validate(df, source)

    periods = df.groupby(["_year", "_month"]).size()
    log.info(f"  Períodos: {list(periods.index)}")
    for (year, month), _ in periods.items():
        upsert_partition(df, int(year), int(month), source)

    rebuild_master(source)
    archive_raw(path, source["name"])


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1:
        files = [Path(p) for p in sys.argv[1:]]
    else:
        files = sorted(INPUT_DIR.glob("*.xlsx"))

    if not files:
        log.warning(f"No hay archivos xlsx en {INPUT_DIR}")
        return

    log.info(f"Archivos: {[f.name for f in files]}")
    for f in files:
        process_file(f)

    log.info("Ingesta completada.")


if __name__ == "__main__":
    main()
