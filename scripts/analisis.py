"""
analisis.py
───────────
Motor de análisis con DuckDB sobre los consolidados parquet.
Lee las particiones directamente en disco sin cargar todo en memoria.

Uso:
    python scripts/analisis.py                          # modo interactivo
    python scripts/analisis.py --query "SELECT ..."     # query directa
    python scripts/analisis.py --sql queries/mi.sql     # archivo SQL

Tablas disponibles en DuckDB:
    temusystem   → todos los registros de temusystem (master.parquet)
    proforma     → todos los registros de proforma   (master.parquet)
"""

import sys
import argparse
import logging
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUTPUT_DIR, LOGS_DIR, SOURCES

LOGS_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOGS_DIR / f"analisis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
_stream_handler = logging.StreamHandler()
_stream_handler.stream = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1, closefd=False)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.FileHandler(log_file, encoding="utf-8"), _stream_handler],
)
log = logging.getLogger(__name__)


# ── Conexión DuckDB ────────────────────────────────────────────────────────────

def crear_conexion() -> duckdb.DuckDBPyConnection:
    """
    Crea una conexión DuckDB con las vistas de cada fuente registradas.
    Usa los master.parquet si existen, si no lee las particiones directamente.
    """
    con = duckdb.connect()

    for src_name, cfg in SOURCES.items():
        parquet_dir  = cfg["parquet_dir"]
        master_path  = parquet_dir / "master.parquet"
        particiones  = parquet_dir / "**" / "*.parquet"

        if master_path.exists():
            # Lectura rápida del master consolidado
            con.execute(
                f"CREATE VIEW {src_name} AS SELECT * FROM read_parquet('{master_path}')"
            )
            count = con.execute(f"SELECT COUNT(*) FROM {src_name}").fetchone()[0]
            log.info(f"Vista '{src_name}': {count:,} filas (master)")
        elif list(parquet_dir.rglob("data.parquet")):
            # Lee todas las particiones con hive partitioning
            con.execute(
                f"CREATE VIEW {src_name} AS "
                f"SELECT * FROM read_parquet('{particiones}', hive_partitioning=true)"
            )
            count = con.execute(f"SELECT COUNT(*) FROM {src_name}").fetchone()[0]
            log.info(f"Vista '{src_name}': {count:,} filas (particiones)")
        else:
            log.warning(f"Sin datos para '{src_name}', vista omitida")

    return con


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Análisis DuckDB sobre consolidados parquet")
    parser.add_argument("--query", type=str,  help="Query SQL directa")
    parser.add_argument("--sql",   type=Path, help="Archivo .sql a ejecutar (ej: queries/conteo_por_fuente.sql)")
    args = parser.parse_args()

    con = crear_conexion()

    # ── Query desde archivo .sql ──
    if args.sql:
        sql = args.sql.read_text(encoding="utf-8")
        df  = con.execute(sql).df()
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = OUTPUT_DIR / f"resultado_{ts}.xlsx"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        if "periodo" in df.columns:
            resumen = (
                df.groupby(["periodo"] + (["brecha"] if "brecha" in df.columns else []))
                .size()
                .reset_index(name="cantidad")
            )
            with pd.ExcelWriter(out, engine="openpyxl") as writer:
                resumen.to_excel(writer, sheet_name="resumen", index=False)
                log.info(f"  Sheet 'resumen': {len(resumen):,} filas")
                for periodo, grupo in df.groupby("periodo"):
                    grupo.drop(columns="periodo").to_excel(writer, sheet_name=str(periodo)[:31], index=False)
                    log.info(f"  Sheet '{periodo}': {len(grupo):,} filas")
        elif "brecha" in df.columns:
            with pd.ExcelWriter(out, engine="openpyxl") as writer:
                for valor, grupo in df.groupby("brecha"):
                    grupo.drop(columns="brecha").to_excel(writer, sheet_name=str(valor)[:31], index=False)
                    log.info(f"  Sheet '{valor}': {len(grupo):,} filas")
        else:
            df.to_excel(out, index=False)

        log.info(f"Resultado: {len(df):,} filas → {out.name}")
        print(df.to_string(max_rows=20))
        return

    # ── Query directa ──
    if args.query:
        df  = con.execute(args.query).df()
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = OUTPUT_DIR / f"resultado_{ts}.xlsx"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        df.to_excel(out, index=False)
        print(df.to_string(max_rows=50))
        print(f"\n[{len(df):,} filas] → guardado en {out.name}")
        return

    # ── Modo interactivo ──
    print("\nDuckDB interactivo. Tablas disponibles:", list(SOURCES.keys()))
    print("Escribe tu SQL y presiona Enter. 'exit' para salir.\n")
    while True:
        try:
            sql = input("duckdb> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if sql.lower() in ("exit", "quit", ""):
            break
        try:
            df = con.execute(sql).df()
            print(df.to_string(max_rows=40))
            print(f"\n[{len(df):,} filas]\n")
        except Exception as e:
            print(f"Error: {e}\n")


if __name__ == "__main__":
    main()
