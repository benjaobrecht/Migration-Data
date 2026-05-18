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
│   ├── reconciliacion.py      ← cruza temusystem vs proforma sin filtro de Expense Difference
│   ├── reconciliacion_2.py    ← USO MANUAL: cruza considerando solo registros con diferencia real
│   ├── reset.py               ← borra todos los datos generados y deja el proyecto limpio
│   └── analisis.py            ← OPCIONAL: consultas DuckDB libres (SQL ad-hoc)
├── queries/                   ← consultas SQL listas para usar con analisis.py
│   ├── Cruce_Cantidades.sql
│   ├── expense_difference_por_mes.sql
│   ├── reconciliacion_temu_sin_proforma.sql
│   └── reconciliacion_proforma_sin_temu.sql
├── data/                      ← generado localmente, NO versionado
│   ├── temusystem/
│   │   ├── year=2026/month=01/data.parquet
│   │   ├── year=2026/month=02/data.parquet
│   │   └── master.parquet     ← todo el histórico junto, sin duplicados
│   ├── proforma/
│   │   └── master.parquet
│   └── raw/                   ← xlsx originales archivados automáticamente (con timestamp)
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
# Clonar el repositorio
git clone https://github.com/benjaobrecht/Migration-Data.git
cd Migration-Data

# Crear y activar entorno virtual
python -m venv .venv
.venv\Scripts\activate # Este comando es para activar el entorno virtual, cada vez que se abra una terminal nueva hay que activar el entorno


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

Se recomienda usar `reconciliacion_2.py`, que aplica el filtro correcto de `Expense Difference` antes de hacer los cruces:

```powershell
# Revisar todo el histórico completo (recomendado)
python scripts/reconciliacion_2.py

# Solo el año 2026
python scripts/reconciliacion_2.py --year 2026

# Solo marzo 2026
python scripts/reconciliacion_2.py --year 2026 --month 3
```

### ¿Qué produce?

Un archivo Excel en `output/` con tres sheets:

| Sheet | Contenido |
|---|---|
| `en_temu_sin_proforma` | Órdenes con `Expense Difference` real (excluye `No Difference`) que no están en proforma |
| `en_proforma_sin_temu` | Órdenes de proforma que no tienen ningún match en temusystem |
| `resumen` | Conteo de brechas agrupado por mes |

### Lógica del cruce

| Dirección | Universo de temusystem usado |
|---|---|
| `en_temu_sin_proforma` | Solo registros con `Expense Difference` ≠ `No Difference` |
| `en_proforma_sin_temu` | Toda la tabla (incluye `No Difference`) |

El cruce entre meses busca en **todo el histórico** de la base contraria, no solo en el mes equivalente. Una orden de marzo en temusystem que aparece en proforma en enero se considera encontrada.

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

```

### Query directa desde terminal

```powershell
python scripts/analisis.py --query "SELECT COUNT(DISTINCT \"Tracking number\") FROM temusystem"
```

### Desde un archivo `.sql`

La carpeta `queries/` contiene consultas listas para usar. Cada archivo tiene una consulta:

| Archivo | Qué hace |
|---|---|
| `Cruce_Cantidades.sql` | Conteo de brechas por mes en ambas direcciones (sin filtro de Expense Difference) |
| `expense_difference_por_mes.sql` | Distribución de valores de `Expense Difference` para un mes dado |
| `reconciliacion_temu_sin_proforma.sql` | Detalle de órdenes con diferencia real en temusystem que no están en proforma |
| `reconciliacion_proforma_sin_temu.sql` | Detalle de órdenes de proforma que no tienen match en temusystem |

```powershell
python scripts/analisis.py --sql queries/Cruce_Cantidades.sql
python scripts/analisis.py --sql queries/reconciliacion_temu_sin_proforma.sql
python scripts/analisis.py --sql queries/reconciliacion_proforma_sin_temu.sql
```

El resultado se muestra en la terminal (hasta 20 filas) y se guarda automáticamente en `output/` como Excel.

Para agregar una consulta nueva, creás un archivo `.sql` en `queries/` y lo llamás igual que los anteriores.

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

3. python scripts/reconciliacion_2.py --year 2026 --month X
   └─ Excel con brechas del mes en output/

4. (opcional) python scripts/analisis.py
   └─ consultas SQL ad-hoc sobre todo el histórico
```
