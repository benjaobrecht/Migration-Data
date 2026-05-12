"""
analisis.py
───────────
Motor de análisis con DuckDB sobre los consolidados parquet.
Lee las particiones directamente en disco sin cargar todo en memoria.

Uso:
    python scripts/analisis.py                          # menú interactivo
    python scripts/analisis.py --query "SELECT ..."     # query directa
    python scripts/analisis.py --sql consultas.sql      # archivo SQL
    python scripts/analisis.py --export reporte         # exporta todos los análisis

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


# ── Queries de análisis predefinidos ──────────────────────────────────────────

QUERIES_PREDEFINIDOS = {
    "resumen_temusystem": """
        SELECT
            YEAR(FECHA)  AS año,
            MONTH(FECHA) AS mes,
            COUNT(*)     AS registros
        FROM temusystem
        GROUP BY 1, 2
        ORDER BY 1, 2
    """,

    "resumen_proforma": """
        SELECT
            YEAR(FECHA)  AS año,
            MONTH(FECHA) AS mes,
            COUNT(*)     AS registros
        FROM proforma
        GROUP BY 1, 2
        ORDER BY 1, 2
    """,

    # ── Cruce: registros en temusystem que NO están en proforma ──
    "en_temusystem_sin_proforma": """
        SELECT t.*
        FROM temusystem t
        LEFT JOIN proforma p USING (ID)   -- ← ajustar por clave de cruce real
        WHERE p.ID IS NULL
    """,

    # ── Cruce: registros en proforma que NO están en temusystem ──
    "en_proforma_sin_temusystem": """
        SELECT p.*
        FROM proforma p
        LEFT JOIN temusystem t USING (ID)
        WHERE t.ID IS NULL
    """,

    # ── Diferencias en columnas comunes ──────────────────────────
    "diferencias_columna_ejemplo": """
        SELECT
            t.ID,
            t.FECHA,
            t.MONTO   AS monto_temu,
            p.MONTO   AS monto_proforma,
            t.MONTO - p.MONTO AS diferencia
        FROM temusystem t
        JOIN proforma p USING (ID)
        WHERE t.MONTO <> p.MONTO      -- ← ajustar columna a comparar
        ORDER BY ABS(t.MONTO - p.MONTO) DESC
    """,
}


# ── Exportar resultados ────────────────────────────────────────────────────────

def exportar_excel(resultados: dict[str, pd.DataFrame], nombre: str):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"{nombre}_{ts}.xlsx"

    log.info(f"Exportando → {path.name}")
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet, df in resultados.items():
            df.to_excel(writer, sheet_name=sheet[:31], index=False)
            ws = writer.sheets[sheet[:31]]
            for col_cells in ws.columns:
                max_len = max((len(str(c.value or "")) for c in col_cells), default=8) + 2
                ws.column_dimensions[col_cells[0].column_letter].width = min(max_len, 45)
    log.info(f"Reporte guardado: {path}")
    return path


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Análisis DuckDB sobre consolidados parquet")
    parser.add_argument("--query",  type=str,  help="Query SQL directa")
    parser.add_argument("--sql",    type=Path, help="Archivo .sql a ejecutar")
    parser.add_argument("--export", type=str,  help="Exporta todos los análisis predefinidos a Excel")
    parser.add_argument("--list",   action="store_true", help="Lista análisis disponibles")
    args = parser.parse_args()

    con = crear_conexion()

    # ── Listar análisis disponibles ──
    if args.list:
        print("\nAnálisis predefinidos:")
        for nombre in QUERIES_PREDEFINIDOS:
            print(f"  · {nombre}")
        return

    # ── Exportar todos los análisis predefinidos ──
    if args.export:
        resultados = {}
        for nombre, sql in QUERIES_PREDEFINIDOS.items():
            try:
                df = con.execute(sql).df()
                resultados[nombre] = df
                log.info(f"  {nombre}: {len(df):,} filas")
            except Exception as e:
                log.warning(f"  {nombre} falló: {e}")
        exportar_excel(resultados, args.export)
        return

    # ── Query desde archivo .sql ──
    if args.sql:
        sql = args.sql.read_text(encoding="utf-8")
        df  = con.execute(sql).df()
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = OUTPUT_DIR / f"resultado_{ts}.xlsx"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
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
