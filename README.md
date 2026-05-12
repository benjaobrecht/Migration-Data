# Migration — Consolidado TEMU

Sistema de consolidación y análisis de datos usando **Parquet + DuckDB**.
Reemplaza el flujo manual de Excel por un pipeline eficiente que soporta
históricos grandes y permite cruzar las bases de temusystem y proforma.

---

## ¿Por qué Parquet + DuckDB y no Excel?

| | Excel | Parquet + DuckDB |
|---|---|---|
| Archivo de 500k filas | ~80 MB, lento | ~8 MB, instantáneo |
| Consultar un mes específico | Cargar todo | Lee solo esa partición |
| Cruzar dos bases de 1M filas | Crash / minutos | Segundos |
| Histórico acumulado | Un archivo cada vez más pesado | Particiones independientes |

---

## Estructura del proyecto

```
Migration/
├── config.py                  ← configuración central (fuentes, claves, columnas)
├── requirements.txt
├── scripts/
│   ├── ingest.py              ← USO MANUAL: carga xlsx → upsert en parquet particionado
│   ├── reconciliacion.py      ← USO MANUAL: cruza temusystem vs proforma, detecta brechas
│   └── analisis.py            ← OPCIONAL: consultas DuckDB libres (SQL ad-hoc)
├── data/                      ← generado localmente, NO versionado
│   ├── temusystem/
│   │   ├── year=2026/month=01/data.parquet
│   │   ├── year=2026/month=02/data.parquet
│   │   └── master.parquet     ← todo el histórico junto, sin duplicados
│   ├── proforma/
│   │   └── master.parquet
│   └── raw/                   ← xlsx originales archivados automáticamente
├── input/                     ← xlsx de entrada (no versionado)
├── output/                    ← reportes Excel generados
└── logs/                      ← log de cada ejecución
```

---

## Requisitos

- Python **3.9 o superior**
- Windows (los comandos de activación del entorno usan rutas de Windows)

---

## Paso 0 — Setup inicial (una sola vez)

```powershell
# Crear y activar entorno virtual
python -m venv .venv
.venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt
```

### Configuración en `config.py`

Las columnas ya están configuradas con los valores reales de cada fuente:

```python
SOURCES = {
    "temusystem": {
        "primary_key": ["Tracking number"],
        "date_column": "Settlement month(eg:202305)",
        "date_format": "YYYYMM",        # formato año+mes: 202305
    },
    "proforma": {
        "primary_key": ["NROGUIA"],
        "date_column": "FECHA",
        "date_format": "DD-MM-YYYY",    # formato: 15-03-2026
    },
}
```

Si en algún momento cambian los nombres de columna en los Excel, este es el único archivo que hay que editar.

---

## Paso 1 — Ingestar nuevos Excel

Cada vez que descargás un Excel nuevo, lo ponés en `input/` y corrés:

```powershell
python scripts/ingest.py
```

También podés apuntar a un archivo específico:

```powershell
python scripts/ingest.py "input/temusystem march.xlsx"
```

### ¿Qué hace internamente?

1. Lee todos los `.xlsx` de `input/`
2. Detecta el tipo por el nombre del archivo:
   - Nombre contiene `temusystem` → fuente temusystem
   - Nombre contiene `proforma` → fuente proforma
3. Normaliza la fecha de cada fila (`202305` → `2023-05-01`, `15-03-2026` → `2026-03-15`)
4. Distribuye cada fila en la partición correcta según su **fecha real**, no el nombre del archivo
5. Hace **upsert**: si un `Tracking number` / `NROGUIA` ya existe lo actualiza, si es nuevo lo agrega
6. Reconstruye el `master.parquet` con todo el histórico sin duplicados
7. Mueve el xlsx a `data/raw/` como archivo

### Ejemplo: Excel de marzo con filas de otros meses

```
input/temusystem march.xlsx  →  tiene filas de febrero, marzo y abril

Resultado después de ingest.py:
  temusystem/year=2026/month=02/  ← filas de feb quedan acá
  temusystem/year=2026/month=03/  ← filas de mar quedan acá
  temusystem/year=2026/month=04/  ← filas de abr quedan acá
```

### Ejemplo: actualización del mismo mes

```powershell
# Primera carga de marzo
python scripts/ingest.py "input/temusystem march.xlsx"

# Llega una corrección del mismo mes → hace upsert, no duplica
python scripts/ingest.py "input/temusystem march_actualizacion.xlsx"
```

---

## Paso 2 — Reconciliación (análisis principal)

Detecta qué órdenes de servicio están en una base pero no en la otra.

```powershell
# Revisar todo el histórico completo (recomendado)
python scripts/reconciliacion.py

# Solo el año 2026
python scripts/reconciliacion.py --year 2026

# Solo marzo 2026
python scripts/reconciliacion.py --year 2026 --month 3
```

### ¿Qué produce?

Un archivo Excel en `output/` con tres sheets:

| Sheet | Contenido |
|---|---|
| `en_temu_sin_proforma` | Órdenes que están en temusystem pero no en proforma (con todas sus columnas) |
| `en_proforma_sin_temu` | Órdenes que están en proforma pero no en temusystem (con todas sus columnas) |
| `resumen` | Conteo de brechas agrupado por mes |

### Lógica del cruce entre meses

Cuando se busca si una orden de marzo de temusystem existe en proforma, se busca en **todos los meses de proforma**, no solo en marzo. Así una orden cargada en temusystem en marzo pero registrada en proforma en enero aparece como "encontrada" y no como brecha.

---

## Paso 3 — Análisis libre con DuckDB

Para consultas personalizadas sobre el histórico completo.

### Modo interactivo

```powershell
python scripts/analisis.py
```

```sql
duckdb> SELECT COUNT(*) FROM temusystem;
duckdb> SELECT COUNT(*) FROM proforma;

-- Registros por mes
duckdb> SELECT YEAR(FECHA) año, MONTH(FECHA) mes, COUNT(*) n
        FROM proforma GROUP BY 1, 2 ORDER BY 1, 2;

-- Buscar una orden específica en las dos bases
duckdb> SELECT * FROM temusystem WHERE "Tracking number" = 'ABC123';
duckdb> SELECT * FROM proforma WHERE "NROGUIA" = 'ABC123';

-- Órdenes que están en ambas bases
duckdb> SELECT t."Tracking number", t."Settlement month(eg:202305)", p."FECHA"
        FROM temusystem t
        JOIN proforma p ON t."Tracking number" = p."NROGUIA";
```

### Query directa desde terminal

```powershell
python scripts/analisis.py --query "SELECT COUNT(DISTINCT \"Tracking number\") FROM temusystem"
```

### Desde un archivo `.sql`

Creás un archivo con tu consulta, por ejemplo `mi_consulta.sql`:

```sql
SELECT
    t."Tracking number",
    t."Settlement month(eg:202305)" AS mes_temu,
    p."FECHA"                        AS fecha_proforma
FROM temusystem t
JOIN proforma p ON t."Tracking number" = p."NROGUIA"
WHERE YEAR(p."FECHA") = 2026
```

```powershell
python scripts/analisis.py --sql mi_consulta.sql
# → guarda el resultado en output/ como Excel automáticamente
```

### Exportar todos los análisis predefinidos

```powershell
python scripts/analisis.py --export reporte_mayo_2026
# → genera output/reporte_mayo_2026_TIMESTAMP.xlsx con varios sheets
```

---

## Reset — volver a cero

Si necesitás borrar todos los datos generados y empezar de cero (útil al cambiar de fuente o en un nuevo equipo):

```powershell
python scripts/reset.py
```

Borra `data/`, `output/` y `logs/`. **No toca** `input/`, `config.py` ni `scripts/`.
Pide confirmación escribiendo `RESET` antes de borrar nada.

---

## Flujo mensual resumido

```
Cada mes:

1. Descargar Excel nuevo
   └─ moverlo a input/

2. python scripts/ingest.py
   └─ actualiza particiones y master.parquet

3. python scripts/reconciliacion.py --year 2026 --month X
   └─ Excel con brechas del mes en output/

4. (opcional) python scripts/analisis.py
   └─ consultas SQL ad-hoc sobre todo el histórico
```
