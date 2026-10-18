
#!/usr/bin/env python3
"""Actualiza el INPC desde el CSV oficial del INEGI."""

import csv
import io
import json
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
DESTINO = ROOT / "herramientas" / "inpc" / "inpc.json"

URL = (
    "https://www.inegi.org.mx/app/indicesdeprecios/"
    "Exportacion.aspx?INPTipoExporta=CSV"
)

SERIE = "865541"
ESTRUCTURA = "112001700010"

MESES = {
    "Ene": 1, "Feb": 2, "Mar": 3, "Abr": 4,
    "May": 5, "Jun": 6, "Jul": 7, "Ago": 8,
    "Sep": 9, "Oct": 10, "Nov": 11, "Dic": 12,
}


def descargar_csv():
    actual = date.today().year

    parametros = {
        "idEstructura": ESTRUCTURA,
        "_formato": "CSV",
        "_anioI": str(actual - 10),
        "_anioF": str(actual),
        "_meta": "0",
        "_tipo": "Niveles",
        "_info": "Índices",
        "_orient": "vertical",
        "_esquema": "0",
        "_of": "inp",
        "_cuadro": ESTRUCTURA,
        "_series": (
            "e|865541,1380001,865546,865547,865555,"
        ),
        "_cveEstructura": ESTRUCTURA,
    }

    solicitud = Request(
        URL,
        data=urlencode(parametros).encode("utf-8"),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": (
                "application/x-www-form-urlencoded"
            ),
            "Referer": (
                "https://www.inegi.org.mx/app/"
                "indicesdeprecios/"
            ),
        },
        method="POST",
    )

    try:
        with urlopen(solicitud, timeout=60) as respuesta:
            if respuesta.status != 200:
                raise RuntimeError("Respuesta HTTP no válida")
            contenido = respuesta.read()
    except (HTTPError, URLError) as error:
        raise RuntimeError(
            "No se pudo descargar el CSV del INEGI"
        ) from error

    if not contenido:
        raise RuntimeError("El INEGI devolvió un archivo vacío")

    return contenido.decode("cp1252-sig")


def extraer_indices(contenido):
    filas = list(csv.reader(io.StringIO(contenido)))

    encabezado = None
    columna = None

    for numero, fila in enumerate(filas):
        if fila and fila[0].strip() == "Fecha":
            encabezado = numero
            columnas = [x.strip() for x in fila]

            if SERIE not in columnas:
                raise RuntimeError(
                    "El CSV no contiene la serie " + SERIE
                )

            columna = columnas.index(SERIE)
            break

    if encabezado is None:
        raise RuntimeError(
            "No se encontró el encabezado Fecha"
        )

    valores = {}

    for fila in filas[encabezado + 1:]:
        if len(fila) <= columna:
            continue

        periodo = fila[0].strip()
        coincidencia = re.fullmatch(
            r"(Ene|Feb|Mar|Abr|May|Jun|Jul|Ago|"
            r"Sep|Oct|Nov|Dic)\s+(\d{4})",
            periodo,
        )

        if not coincidencia:
            continue

        mes = MESES[coincidencia.group(1)]
        anio = int(coincidencia.group(2))
        bruto = fila[columna].strip()

        try:
            valor = Decimal(bruto)
        except InvalidOperation:
            continue

        if not valor.is_finite() or valor <= 0:
            continue

        indice = float(
            valor.quantize(
                Decimal("0.001"),
                rounding=ROUND_HALF_UP,
            )
        )

        clave = (anio, mes)

        if clave in valores and valores[clave] != indice:
            raise RuntimeError(
                f"Índice duplicado diferente: {periodo}"
            )

        valores[clave] = indice

    if len(valores) < 100:
        raise RuntimeError(
            "La descarga contiene pocos índices válidos"
        )

    return valores


def main():
    print("Consultando CSV oficial del INEGI...")

    contenido = descargar_csv()
    valores = extraer_indices(contenido)

    hoy = date.today()
    inicio = hoy.year - 10

    registros = []

    for anio in range(hoy.year, inicio - 1, -1):
        meses = [
            valores.get((anio, mes))
            for mes in range(1, 13)
        ]

        if anio < hoy.year and any(
            valor is None for valor in meses
        ):
            raise RuntimeError(
                f"Faltan índices del año {anio}"
            )

        registros.append({
            "anio": anio,
            "meses": meses,
        })

    if not any(
        valor is not None
        for registro in registros
        for valor in registro["meses"]
    ):
        raise RuntimeError("No se encontraron índices")

    anteriores = {}

    if DESTINO.exists():
        anterior = json.loads(
            DESTINO.read_text(encoding="utf-8")
        )

        for registro in anterior.get("registros", []):
            for mes, valor in enumerate(
                registro["meses"], start=1
            ):
                if valor is not None:
                    anteriores[(registro["anio"], mes)] = (
                        Decimal(str(valor))
                    )

    # Impedir que una descarga incompleta borre
    # índices que ya estaban publicados.
    for clave, valor in anteriores.items():
        anio, mes = clave

        if inicio <= anio <= hoy.year:
            if clave not in valores:
                raise RuntimeError(
                    f"El INEGI no devolvió {anio}-{mes:02d}. "
                    "Se conserva el archivo anterior."
                )

    # Detectar si los índices cambiaron realmente.
    nuevos = {
        (registro["anio"], mes): Decimal(str(valor))
        for registro in registros
        for mes, valor in enumerate(
            registro["meses"], start=1
        )
        if valor is not None
    }

    anteriores_vigentes = {
        clave: valor
        for clave, valor in anteriores.items()
        if inicio <= clave[0] <= hoy.year
    }

    if nuevos == anteriores_vigentes and DESTINO.exists():
        print("El INPC ya está actualizado.")
        return

    resultado = {
        "fuente": "INEGI",
        "indicador": SERIE,
        "descripcion": (
            "Índice Nacional de Precios al Consumidor"
        ),
        "actualizado": hoy.isoformat(),
        "registros": registros,
    }

    DESTINO.parent.mkdir(
        parents=True, exist_ok=True
    )

    temporal = DESTINO.with_suffix(".json.tmp")
    temporal.write_text(
        json.dumps(
            resultado,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    temporal.replace(DESTINO)

    ultimo = max(valores)
    print(
        "Último periodo disponible:",
        f"{ultimo[0]}-{ultimo[1]:02d}",
    )
    print("INPC:", valores[ultimo])
    print("Archivo inpc.json actualizado correctamente.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.exit(f"ERROR: {error}")
