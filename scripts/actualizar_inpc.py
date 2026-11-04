
#!/usr/bin/env python3
"""Actualiza el INPC desde la API oficial del INEGI sin perder datos previos."""

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


def consultar_inegi():
    if not TOKEN or not INDICADOR:
        raise RuntimeError(
            "Falta INEGI_TOKEN o INEGI_INPC_INDICADOR"
        )

    if FUENTE not in ("BISE", "BIE-BISE"):
        raise RuntimeError("Fuente INEGI no válida")

    url = (
        "https://www.inegi.org.mx/app/api/indicadores/"
        "desarrolladores/"
        f"jsonxml/INDICATOR/{quote(INDICADOR, safe='')}"
        f"/es/00/false/{FUENTE}/2.0/"
        f"{quote(TOKEN, safe='')}?type=json"
    )

    solicitud = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "UlloaContadores-INPC/1.0",
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
            "El INEGI no devolvió JSON válido"
        ) from error

    series = (
        datos.get("Series")
        if isinstance(datos, dict)
        else None
    )

    if not isinstance(series, list):
        raise RuntimeError(
            "Respuesta sin series; revisa indicador, fuente y token"
        )

    coincidencias = [
        serie
        for serie in series
        if str(serie.get("INDICADOR")) == INDICADOR
    ]

    if len(coincidencias) != 1:
        raise RuntimeError(
            "No se encontró una serie única del indicador configurado"
        )

    return coincidencias[0]


def extraer_indices(serie):
    observaciones = serie.get("OBSERVATIONS")

    if not isinstance(observaciones, list):
        raise RuntimeError("No hay observaciones")

    valores = {}

    for obs in observaciones:
        periodo = str(
            obs.get("TIME_PERIOD", "")
        ).strip()

        coincidencia = re.fullmatch(
            r"(\d{4})[-/](0?[1-9]|1[0-2])",
            periodo,
        )

        if not coincidencia:
            continue

        try:
            valor = Decimal(
                str(obs.get("OBS_VALUE", "")).strip()
            )
        except InvalidOperation:
            continue

        if not valor.is_finite() or valor <= 0:
            continue

        clave = (
            int(coincidencia.group(1)),
            int(coincidencia.group(2)),
        )

        indice = valor.quantize(
            Decimal("0.001"),
            rounding=ROUND_HALF_UP,
        )

        if clave in valores and valores[clave] != indice:
            raise RuntimeError(
                f"Índice duplicado diferente: {periodo}"
            )

        valores[clave] = indice

    print(
        "Indicador:", INDICADOR,
        "Observaciones:", len(observaciones),
        "Meses válidos:", len(valores),
        flush=True,
    )

    print(
        "Periodos 2026:",
        [
            f"{anio}-{mes:02d}"
            for anio, mes in sorted(valores)
            if anio == 2026
        ],
        flush=True,
    )

    print(
        "Ejemplos de periodos originales:",
        [
            obs.get("TIME_PERIOD")
            for obs in observaciones[:8]
        ],
        flush=True,
    )

    if len(valores) < 100:
        raise RuntimeError(
            "La API devolvió menos de 100 meses válidos; "
            "verifica el indicador"
        )

    return valores


def leer_anteriores():
    if not DESTINO.exists():
        return {}, None

    documento = json.loads(
        DESTINO.read_text(encoding="utf-8")
    )

    anteriores = {}

    for registro in documento.get("registros", []):
        for mes, valor in enumerate(
            registro["meses"], start=1
        ):
            if valor is not None:
                anteriores[
                    (int(registro["anio"]), mes)
                ] = Decimal(str(valor))

    return anteriores, documento


def main():
    print(
        "Consultando API oficial del INEGI...",
        flush=True,
    )

    serie = consultar_inegi()
    valores = extraer_indices(serie)

    hoy = date.today()
    inicio = hoy.year - 10

    anteriores, documento_anterior = leer_anteriores()

    # No cambiar la serie ni perder datos históricos.
    for (anio, mes), anterior in anteriores.items():
        if not inicio <= anio <= hoy.year:
            continue

        nuevo = valores.get((anio, mes))

        if nuevo is None:
            raise RuntimeError(
                f"Falta el índice {anio}-{mes:02d}. "
                "Se conserva el archivo anterior."
            )

        if abs(nuevo - anterior) > Decimal("0.001"):
            raise RuntimeError(
                f"Diferencia histórica en {anio}-{mes:02d}: "
                f"publicado={anterior}, API={nuevo}. "
                "Verifica la serie y la base; "
                "no se modifica el archivo."
            )

    registros = []

    for anio in range(hoy.year, inicio - 1, -1):
        meses = [
            float(valores[(anio, mes)])
            if (anio, mes) in valores
            else None
            for mes in range(1, 13)
        ]

        if anio < hoy.year and any(
            valor is None for valor in meses
        ):
            raise RuntimeError(
                f"Faltan índices del año {anio}; "
                "no se modifica el archivo"
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
        parents=True,
        exist_ok=True,
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
    print(
        "Archivo inpc.json actualizado correctamente."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.exit(f"ERROR: {error}")
