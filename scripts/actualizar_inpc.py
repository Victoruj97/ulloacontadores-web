
#!/usr/bin/env python3
"""Actualiza el INPC mensual desde la API oficial del INEGI."""

import json
import os
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
DESTINO = ROOT / "herramientas" / "inpc" / "inpc.json"

TOKEN = os.environ.get("INEGI_TOKEN", "").strip()
INDICADOR = os.environ.get("INEGI_INPC_INDICADOR", "").strip()
FUENTE = os.environ.get("INEGI_INPC_FUENTE", "BIE-BISE").strip()

SERIE_ANTERIOR = "865541"


def consultar_inegi():
    if not TOKEN:
        raise RuntimeError("Falta INEGI_TOKEN")

    if not INDICADOR:
        raise RuntimeError("Falta INEGI_INPC_INDICADOR")

    if FUENTE not in ("BISE", "BIE-BISE"):
        raise RuntimeError("Fuente del INEGI no válida")

    url = (
        "https://www.inegi.org.mx/app/api/indicadores/"
        "desarrolladores/jsonxml/INDICATOR/"
        f"{quote(INDICADOR, safe='')}/es/00/false/"
        f"{FUENTE}/2.0/{quote(TOKEN, safe='')}?type=json"
    )

    solicitud = Request(
        url,
        headers={
            "User-Agent": "UlloaContadores-INPC/1.0",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(solicitud, timeout=60) as respuesta:
            contenido = respuesta.read()
    except HTTPError as error:
        raise RuntimeError(
            f"INEGI respondió HTTP {error.code}"
        ) from error
    except URLError as error:
        raise RuntimeError(
            f"No se pudo conectar al INEGI: {error.reason}"
        ) from error

    try:
        datos = json.loads(contenido.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as error:
        raise RuntimeError(
            "El INEGI no devolvió un JSON válido"
        ) from error

    if not isinstance(datos, dict):
        raise RuntimeError("Respuesta inesperada del INEGI")

    series = datos.get("Series")

    if not isinstance(series, list) or not series:
        raise RuntimeError(
            "La API no devolvió series. "
            "Verifica indicador, fuente y token."
        )

    coincidencias = [
        serie for serie in series
        if str(serie.get("INDICADOR")) == INDICADOR
    ]

    if len(coincidencias) != 1:
        raise RuntimeError(
            "No se encontró una serie única para "
            "el indicador configurado"
        )

    return coincidencias[0]


def extraer_indices(serie):
    observaciones = serie.get("OBSERVATIONS")

    if not isinstance(observaciones, list):
        raise RuntimeError("No hay observaciones válidas")

    valores = {}

    for observacion in observaciones:
        periodo = str(
            observacion.get("TIME_PERIOD", "")
        ).strip()

        coincidencia = re.fullmatch(
            r"(\d{4})[-/](0?[1-9]|1[0-2])",
            periodo,
        )

        if not coincidencia:
            continue

        anio = int(coincidencia.group(1))
        mes = int(coincidencia.group(2))

        bruto = str(
            observacion.get("OBS_VALUE", "")
        ).strip()

        try:
            valor = Decimal(bruto)
        except InvalidOperation:
            continue

        if not valor.is_finite() or valor <= 0:
            continue

        indice = valor.quantize(
            Decimal("0.001"),
            rounding=ROUND_HALF_UP,
        )

        clave = (anio, mes)

        if clave in valores and valores[clave] != indice:
            raise RuntimeError(
                f"Índice duplicado diferente: {periodo}"
            )

        valores[clave] = indice

    if len(valores) < 100:
        raise RuntimeError(
            "La API devolvió menos de 100 índices "
            "mensuales válidos. Verifica el indicador."
        )

    return valores


def leer_anteriores():
    if not DESTINO.exists():
        return {}, None

    datos = json.loads(
        DESTINO.read_text(encoding="utf-8")
    )

    anteriores = {}

    for registro in datos.get("registros", []):
        anio = int(registro["anio"])

        for mes, valor in enumerate(
            registro["meses"], start=1
        ):
            if valor is not None:
                anteriores[(anio, mes)] = Decimal(
                    str(valor)
                )

    return anteriores, datos


def main():
    print("Consultando API oficial del INEGI...", flush=True)

    serie = consultar_inegi()
    valores = extraer_indices(serie)

    hoy = date.today()
    inicio = hoy.year - 10

    anteriores, documento_anterior = leer_anteriores()

    # No permitir cambiar silenciosamente de serie.
    if documento_anterior:
        indicador_previo = str(
            documento_anterior.get("indicador", "")
        )

        if indicador_previo not in (
            INDICADOR,
            SERIE_ANTERIOR,
        ):
            raise RuntimeError(
                "El indicador existente no coincide "
                "con el configurado. Revisión necesaria."
            )

    # Verificar que los datos históricos publicados
    # sean compatibles con la serie consultada.
    for clave, anterior in anteriores.items():
        anio, mes = clave

        if not inicio <= anio <= hoy.year:
            continue

        nuevo = valores.get(clave)

        if nuevo is None:
            raise RuntimeError(
                f"Falta el índice {anio}-{mes:02d}. "
                "Se conserva el archivo anterior."
            )

        if abs(nuevo - anterior) > Decimal("0.001"):
            raise RuntimeError(
                f"Diferencia histórica en "
                f"{anio}-{mes:02d}: "
                f"publicado={anterior}, API={nuevo}. "
                "Verifica que sea la misma serie "
                "y base del INPC."
            )

    registros = []

    for anio in range(hoy.year, inicio - 1, -1):
        meses = []

        for mes in range(1, 13):
            valor = valores.get((anio, mes))
            meses.append(
                float(valor) if valor is not None else None
            )

        if anio < hoy.year and any(
            valor is None for valor in meses
        ):
            raise RuntimeError(
                f"Faltan índices del año {anio}. "
                "Se conserva el archivo anterior."
            )

        registros.append({
            "anio": anio,
            "meses": meses,
        })

    nuevos = {
        clave: valor
        for clave, valor in valores.items()
        if inicio <= clave[0] <= hoy.year
    }

    anteriores_vigentes = {
        clave: valor
        for clave, valor in anteriores.items()
        if inicio <= clave[0] <= hoy.year
    }

    if (
        documento_anterior is not None
        and nuevos == anteriores_vigentes
    ):
        print("El INPC ya está actualizado.")
        return

    resultado = {
        "fuente": "INEGI",
        "indicador": INDICADOR,
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

    ultimo = max(nuevos)

    print(
        "Último periodo disponible:",
        f"{ultimo[0]}-{ultimo[1]:02d}",
    )
    print("INPC:", nuevos[ultimo])
    print("Archivo inpc.json actualizado correctamente.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.exit(f"ERROR: {error}")
)
