"""
reconciliacion_2.py
───────────────────
Igual que reconciliacion.py pero filtra temusystem ANTES de los cruces:
excluye filas donde "Expense Difference" = 'No Difference'.

Resultado:
  - Sheet "en_temu_sin_proforma" : órdenes (con diferencia) en temusystem pero no en proforma
  - Sheet "en_proforma_sin_temu" : órdenes en proforma pero no en temusystem (con diferencia)
  - Sheet "resumen"              : conteos por mes para cada brecha

Uso:
    python scripts/reconciliacion_2.py
    python scripts/reconciliacion_2.py --year 2026
    python scripts/reconciliacion_2.py --year 2026 --month 3
    python scripts/reconciliacion_2.py --output mi_reporte
"""

import sys
import argparse
import logging
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUTPUT_DIR, LOGS_DIR, SOURCES, RECONCILIATION

LOGS_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOGS_DIR / f"reconciliacion2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
_stream_handler = logging.StreamHandler()
_stream_handler.stream = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1, closefd=False)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.FileHandler(log_file, encoding="utf-8"), _stream_handler],
)
log = logging.getLogger(__name__)

TEMU_KEY      = RECONCILIATION["temusystem_key"]   # "Tracking number"
PROFORMA_KEY  = RECONCILIATION["proforma_key"]     # "NROGUIA"
EXPENSE_COL   = "Expense Difference"

TEMU_DATE     = SOURCES["temusystem"]["date_column"]   # "Settlement month(eg:202305)"
PROFORMA_DATE = SOURCES["proforma"]["date_column"]     # "FECHA"


# ── Conexión DuckDB ────────────────────────────────────────────────────────────

def crear_conexion() -> duckdb.DuckDBPyConnection:
    """
    Crea las vistas base (master.parquet) y además una vista filtrada de
    temusystem que excluye los registros con "Expense Difference" = 'No Difference'.
    Los cruces usan esa vista filtrada.
    """
    con = duckdb.connect()

    for src_name, cfg in SOURCES.items():
        master = cfg["parquet_dir"] / "master.parquet"
        if not master.exists():
            raise FileNotFoundError(
                f"No se encontró el master de '{src_name}' en {master}\n"
                f"Ejecutá primero: python scripts/ingest.py"
            )
        con.execute(f"CREATE VIEW {src_name} AS SELECT * FROM read_parquet('{master}')")
        n = con.execute(f"SELECT COUNT(*) FROM {src_name}").fetchone()[0]
        log.info(f"Vista '{src_name}': {n:,} registros totales")

    # Vista filtrada: temusystem sin los "No Difference"
    con.execute(f"""
        CREATE VIEW temusystem_filtrado AS
        SELECT * FROM temusystem
        WHERE "{EXPENSE_COL}" <> 'No Difference'
           OR "{EXPENSE_COL}" IS NULL
    """)
    n_filtrado = con.execute("SELECT COUNT(*) FROM temusystem_filtrado").fetchone()[0]
    log.info(f"Vista 'temusystem_filtrado': {n_filtrado:,} registros (excluye 'No Difference')")

    return con


# ── Filtro de período ──────────────────────────────────────────────────────────

def period_filter(date_expr: str, year: int | None, month: int | None) -> str:
    clauses = []
    if year:
        clauses.append(f"YEAR({date_expr}) = {year}")
    if month:
        clauses.append(f"MONTH({date_expr}) = {month}")
    return ("AND " + " AND ".join(clauses)) if clauses else ""


# ── Queries de reconciliación ──────────────────────────────────────────────────

def ordenes_en_temu_sin_proforma(
    con: duckdb.DuckDBPyConnection, year: int | None, month: int | None
) -> pd.DataFrame:
    """
    Órdenes presentes en temusystem (con diferencia) pero ausentes en proforma.
    Usa temusystem_filtrado para excluir 'No Difference' antes del cruce.
    """
    periodo = period_filter(f'CAST("{TEMU_DATE}" AS DATE)', year, month)
    sql = f"""
        SELECT t.*
        FROM temusystem_filtrado t
        WHERE NOT EXISTS (
            SELECT 1 FROM proforma p
            WHERE CAST(p."{PROFORMA_KEY}" AS VARCHAR) = CAST(t."{TEMU_KEY}" AS VARCHAR)
        )
        {periodo}
        ORDER BY t."{TEMU_DATE}"
    """
    df = con.execute(sql).df()
    log.info(f"En temusystem (con diferencia) SIN proforma: {len(df):,} órdenes")
    return df


def ordenes_en_proforma_sin_temu(
    con: duckdb.DuckDBPyConnection, year: int | None, month: int | None
) -> pd.DataFrame:
    """
    Órdenes presentes en proforma pero ausentes en temusystem completo.
    Se compara contra toda la tabla temusystem (incluyendo 'No Difference'):
    si la guía existe en temu con cualquier valor, no es una brecha.
    """
    periodo = period_filter(f'CAST("{PROFORMA_DATE}" AS DATE)', year, month)
    sql = f"""
        SELECT p.*
        FROM proforma p
        WHERE NOT EXISTS (
            SELECT 1 FROM temusystem t
            WHERE CAST(t."{TEMU_KEY}" AS VARCHAR) = CAST(p."{PROFORMA_KEY}" AS VARCHAR)
        )
        {periodo}
        ORDER BY p."{PROFORMA_DATE}"
    """
    df = con.execute(sql).df()
    log.info(f"En proforma SIN temusystem (con diferencia): {len(df):,} órdenes")
    return df


def resumen_por_mes(
    df_temu_sin_proforma: pd.DataFrame,
    df_proforma_sin_temu: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for df, origen in [
        (df_temu_sin_proforma, "en_temu_sin_proforma"),
        (df_proforma_sin_temu, "en_proforma_sin_temu"),
    ]:
        date_col = TEMU_DATE if origen == "en_temu_sin_proforma" else PROFORMA_DATE
        if date_col in df.columns and not df.empty:
            fechas = pd.to_datetime(df[date_col], errors="coerce")
            grupo  = (
                fechas.dt.to_period("M")
                .value_counts()
                .sort_index()
                .reset_index()
            )
            grupo.columns = ["periodo", "cantidad"]
            grupo["origen"] = origen
            rows.append(grupo)

    if not rows:
        return pd.DataFrame(columns=["periodo", "cantidad", "origen"])

    resumen = pd.concat(rows, ignore_index=True)
    resumen["periodo"] = resumen["periodo"].astype(str)
    return resumen[["origen", "periodo", "cantidad"]].sort_values(["origen", "periodo"])


# ── Exportar Excel ─────────────────────────────────────────────────────────────

def exportar_excel(sheets: dict[str, pd.DataFrame], nombre: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"{nombre}_{ts}.xlsx"

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            ws = writer.sheets[sheet_name[:31]]
            for col_cells in ws.columns:
                max_len = max((len(str(c.value or "")) for c in col_cells), default=8) + 2
                ws.column_dimensions[col_cells[0].column_letter].width = min(max_len, 45)

    log.info(f"Reporte exportado → {path}")
    return path


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Reconciliación temusystem vs proforma (excluye 'No Difference')"
    )
    parser.add_argument("--year",   type=int, default=None, help="Filtrar por año")
    parser.add_argument("--month",  type=int, default=None, help="Filtrar por mes (1-12)")
    parser.add_argument("--output", type=str, default="reconciliacion_2",
                        help="Nombre base del archivo Excel de salida")
    args = parser.parse_args()

    if args.year:
        periodo_str = f"_{args.year}" + (f"_{args.month:02d}" if args.month else "")
        log.info(f"Período filtrado: {args.year}" + (f"-{args.month:02d}" if args.month else ""))
    else:
        periodo_str = "_historico_completo"
        log.info("Analizando histórico completo (todos los meses)")

    con = crear_conexion()

    df_temu_sin_proforma = ordenes_en_temu_sin_proforma(con, args.year, args.month)
    df_proforma_sin_temu = ordenes_en_proforma_sin_temu(con, args.year, args.month)
    df_resumen           = resumen_por_mes(df_temu_sin_proforma, df_proforma_sin_temu)

    total_brechas = len(df_temu_sin_proforma) + len(df_proforma_sin_temu)
    log.info(f"Total brechas encontradas: {total_brechas:,}")

    nombre_salida = f"{args.output}{periodo_str}"
    path = exportar_excel(
        {
            "en_temu_sin_proforma": df_temu_sin_proforma,
            "en_proforma_sin_temu": df_proforma_sin_temu,
            "resumen":              df_resumen,
        },
        nombre_salida,
    )

    print("\n" + "-" * 50)
    print(f"Ordenes en temusystem sin proforma : {len(df_temu_sin_proforma):>6,}")
    print(f"Ordenes en proforma sin temusystem : {len(df_proforma_sin_temu):>6,}")
    print("-" * 50)
    print(f"Reporte guardado en: {path}")


if __name__ == "__main__":
    main()
