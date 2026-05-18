"""
reset.py
────────
Elimina todos los datos generados y deja el proyecto limpio para empezar de cero.

Borra:
  - data/temusystem/   (particiones parquet + master)
  - data/proforma/     (particiones parquet + master)
  - data/raw/          (xlsx archivados)
  - output/            (reportes Excel generados)
  - logs/              (logs de ejecuciones)

NO toca:
  - input/             (tus xlsx de entrada)
  - config.py          (configuracion)
  - scripts/           (codigo)

Uso:
    python scripts/reset.py
"""

import os
import stat
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA_DIR, RAW_DIR, OUTPUT_DIR, LOGS_DIR, SOURCES

def _limpiar_carpeta(carpeta: Path) -> None:
    """Borra el contenido de una carpeta sin borrar la carpeta en sí."""
    for item in carpeta.iterdir():
        if item.is_dir():
            shutil.rmtree(item, onexc=lambda f, p, _: (os.chmod(p, stat.S_IWRITE), f(p)))
        else:
            os.chmod(item, stat.S_IWRITE)
            item.unlink()


CARPETAS_A_BORRAR = [
    *[cfg["parquet_dir"] for cfg in SOURCES.values()],
    RAW_DIR,
    OUTPUT_DIR,
    LOGS_DIR,
]


def main():
    print()
    print("=" * 52)
    print("  RESET — esto borrara todos los datos generados  ")
    print("=" * 52)
    print()
    print("Se eliminaran:")
    for carpeta in CARPETAS_A_BORRAR:
        existe = "[existe]" if carpeta.exists() else "[vacia] "
        print(f"  {existe}  {carpeta.relative_to(carpeta.parent.parent)}")
    print()
    print("NO se tocara: input/, config.py, scripts/")
    print()

    confirmacion = input("Escribe RESET para confirmar: ").strip()
    if confirmacion != "RESET":
        print("\nReset cancelado.")
        return

    print()
    for carpeta in CARPETAS_A_BORRAR:
        if carpeta.exists():
            _limpiar_carpeta(carpeta)
            print(f"  Limpiado: {carpeta.relative_to(carpeta.parent.parent)}")
        else:
            print(f"  Ya vacia: {carpeta.relative_to(carpeta.parent.parent)}")

    print()
    print("Reset completado. El proyecto esta listo para empezar de cero.")
    print("Siguiente paso: poner los xlsx en input/ y correr python scripts/ingest.py")


if __name__ == "__main__":
    main()
