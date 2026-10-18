
#!/usr/bin/env python3
"""Actualiza la tabla histórica del INPC con datos oficiales del INEGI."""

import json
import os
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent.parent
DESTINO = ROOT / "herramientas" / "inpc" / "inpc.json"

TOKEN = os.environ.get("INEGI_TOKEN", "").strip()
INDICADOR = os.environ.get("INEGI_INPC_INDICADOR", "").strip()
FUENTE = os.environ.get("INEGI_INPC_FUENTE", "BIE-BISE").strip()

def consultar(url):
    try:
        with urlopen(url, timeout=40) as respuesta:
            return json.load(respuesta)
    except (HTTPError, URLError, ValueError) as error:
        raise RuntimeError(
            "No se pudo consultar la API del INEGI"
        ) from error

def main():
    if not TOKEN:
        sys.exit("Falta el secreto INEGI_TOKEN.")

    if not INDICADOR or not INDICADOR.isdigit():
        sys.exit(
            "Falta configurar INEGI_INPC_INDICADOR "
            "con la clave oficial verificada."
        )

    if FUENTE not in ("BISE", "BIE-BISE"):
        sys.exit("Fuente del INEGI no válida.")

    base = (
        "https://www.inegi.org.mx/app/api/"
        "indicadores/desarrolladores/jsonxml"
    )

    metadatos_url = (
        f"{base}/CL_INDICATOR/{INDICADOR}/es/"
        f"{FUENTE}/2.0/{TOKEN}?type=json"
    )

    metadatos = consultar(metadatos_url)
    catalogo = metadatos.get("CODE", [])

    if not catalogo:
        sys.exit("No se encontraron metadatos del indicador.")

    descripcion = str(catalogo[0].get("Description", ""))
    descripcion_normalizada = descripcion.lower()

    if (
        "precios al consumidor" not in descripcion_normalizada
        and "inpc" not in descripcion_normalizada
    ):
        sys.exit(
            "El indicador seleccionado no corresponde al INPC: "
            + descripcion
        )

    url = (
        f"{base}/INDICATOR/{INDICADOR}/es/00/"
        f"false/{FUENTE}/2.0/{TOKEN}?type=json"
    )

    datos = consultar(url)
    series = datos.get("Series", [])

    if len(series) != 1:
        sys.exit("La API no devolvió una serie única.")

    serie = series[0]

    if str(serie.get("INDICADOR")) != INDICADOR:
        sys.exit("El identificador de la serie no coincide.")

    observaciones = serie.get("OBSERVATIONS", [])
    valores = {}

    for observacion in observaciones:
        periodo = str(observacion.get("TIME_PERIOD", ""))
        coincidencia = re.fullmatch(
            r"(\d{4})[-/](0[1-9]|1[0-2])",
            periodo
        )

        if not coincidencia:
            continue

        anio = int(coincidencia.group(1))
        mes = int(coincidencia.group(2))
        bruto = observacion.get("OBS_VALUE")

        if bruto in (None, "", "N/D", "NA"):
            continue

        try:
            valor = Decimal(str(bruto))
        except InvalidOperation:
            continue

        if not valor.is_finite() or valor <= 0:
            continue

        clave = (anio, mes)

        if clave in valores and valores[clave] != valor:
            sys.exit("Existen observaciones duplicadas distintas.")

        valores[clave] = valor

    actual = date.today().year
    inicio = actual - 10

    registros = []

    for anio in range(actual, inicio - 1, -1):
        meses = [
            float(valores[(anio, mes)])
            if (anio, mes) in valores
            else None
            for mes in range(1, 13)
        ]

        registros.append({
            "anio": anio,
            "meses": meses
        })

    if not any(
        valor is not None
        for registro in registros
        for valor in registro["meses"]
    ):
        sys.exit(
            "No se encontraron índices mensuales válidos."
        )

    # Impide publicar una serie histórica incompleta.
    for registro in registros:
        if registro["anio"] < actual:
            if any(v is None for v in registro["meses"]):
                sys.exit(
                    "Faltan índices históricos del año "
                    + str(registro["anio"])
                )

    resultado = {
        "fuente": "INEGI",
        "indicador": INDICADOR,
        "descripcion": descripcion,
        "actualizado": date.today().isoformat(),
        "registros": registros
    }

    DESTINO.parent.mkdir(parents=True, exist_ok=True)

    contenido = json.dumps(
        resultado,
        ensure_ascii=False,
        indent=2
    ) + "\n"

    if DESTINO.exists():
        if DESTINO.read_text(encoding="utf-8") == contenido:
            print("Los datos ya están actualizados.")
            return

    DESTINO.write_text(contenido, encoding="utf-8")
    print("Archivo INPC actualizado correctamente.")

if __name__ == "__main__":
    main()
