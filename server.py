"""
MCP - Boletin Oficial de la Provincia de Tucuman
=================================================
Proxy directo (sin indice propio) contra la API oficial del Boletin Oficial:

    Frontend : https://boletintucuman.gob.ar        (SPA Angular)
    API REST : https://api.boletintucuman.gob.ar     (.NET, Swagger V2.0)
    PDFs     : https://admin.boletintucuman.gob.ar    (ediciones y anexos)

La API oficial ofrece busqueda full-text server-side (parametro CadenaBuscar) y
devuelve el CONTENIDO en texto plano de cada aviso, por lo que no hace falta
crawler ni OCR. Este servidor solo traduce esa API a herramientas MCP.

LIMITACIONES CONOCIDAS DE LA API OFICIAL (verificadas 07/2026): los filtros
OrganismoId, Expediente, NumeroInstrumento y Anunciante, y el uso de comillas en
CadenaBuscar, provocan HTTP 500 en el backend oficial. Por eso NO se exponen:
la busqueda confiable es por texto (tokens), fecha, anio, clase, tipo de aviso y
numero de boletin. El filtro por tipo de aviso requiere clase de aviso, que este
servidor resuelve automaticamente.

Patron y convenciones de deploy identicos a los conectores COMARB / TFN / TFA
del ecosistema DGR Tucuman (FastMCP, Railway, streamable-http).
"""

import os
import json
from datetime import date

import httpx

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# --------------------------------------------------------------------------- #
# Configuracion
# --------------------------------------------------------------------------- #
API_BASE = os.environ.get("BO_API_BASE", "https://api.boletintucuman.gob.ar")
BOLETINES = f"{API_BASE}/api/Boletines"
TIMEOUT = httpx.Timeout(35.0, connect=15.0)
UA = "boletin-tucuman-mcp/1.0 (+DGR Tucuman research connector)"

CLASES_AVISO = {0: "Todos", 1: "Avisos", 2: "Legislacion y Normativa Provincial"}
_TIPOS_CACHE: dict[int, int] = {}  # tipo_aviso_id -> clase_aviso

mcp = FastMCP(
    "Boletin Oficial Tucuman",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8000")),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    ),
)


# --------------------------------------------------------------------------- #
# Helpers HTTP
# --------------------------------------------------------------------------- #
async def _get(path: str, params: dict | None = None):
    url = path if path.startswith("http") else f"{BOLETINES}/{path.lstrip('/')}"
    clean = {k: v for k, v in (params or {}).items() if v not in (None, "", [])}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA}) as c:
            r = await c.get(url, params=clean)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        return {"_error": f"HTTP {e.response.status_code} al consultar la API oficial.",
                "_detalle": e.response.text[:200],
                "_sugerencia": "Si se uso un filtro no soportado (organismo, expediente, "
                               "anunciante o comillas), quitarlo: la API oficial responde 500."}
    except Exception as e:  # noqa: BLE001
        return {"_error": f"No se pudo consultar la API del Boletin: {type(e).__name__}: {e}",
                "_sugerencia": "Reintentar en unos segundos; si persiste, el servicio "
                               "api.boletintucuman.gob.ar puede estar caido o lento."}


async def _post(path: str, payload: dict):
    url = f"{BOLETINES}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA}) as c:
            r = await c.post(url, json=payload)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        return {"_error": f"HTTP {e.response.status_code} al consultar la API oficial.",
                "_detalle": e.response.text[:200]}
    except Exception as e:  # noqa: BLE001
        return {"_error": f"No se pudo consultar la API del Boletin: {type(e).__name__}: {e}"}


def _fmt_fecha(f: str | None) -> str | None:
    """Normaliza a YYYY-MM-DD. Acepta YYYY-MM-DD o DD/MM/YYYY."""
    if not f:
        return None
    f = f.strip()
    if "/" in f:
        p = f.split("/")
        if len(p) == 3:
            d, m, a = p
            try:
                return f"{a}-{int(m):02d}-{int(d):02d}"
            except ValueError:
                return f
    return f


async def _clase_de_tipo(tipo_aviso_id: int) -> int | None:
    """Resuelve la clase_aviso de un tipo (la API exige clase junto al tipo)."""
    if not _TIPOS_CACHE:
        data = await _get("GetAllTipoAviso")
        if isinstance(data, list):
            for t in data:
                if t.get("id") is not None and t.get("claseAviso") is not None:
                    _TIPOS_CACHE[int(t["id"])] = int(t["claseAviso"])
    return _TIPOS_CACHE.get(int(tipo_aviso_id))


def _aviso_resumen(it: dict, incluir_texto: bool, max_snippet: int = 400) -> dict:
    contenido = (it.get("contenido") or "").replace("\r\n", "\n").strip()
    out = {
        "id": it.get("id"),
        "titulo": (it.get("titulo") or "").strip(),
        "tipo_aviso": it.get("tipoAviso"),
        "tipo_aviso_id": it.get("tipoAvisoId"),
        "clase_aviso": CLASES_AVISO.get(it.get("claseAviso"), it.get("claseAviso")),
        "numero_boletin": it.get("numeroBoletin"),
        "fecha_boletin": it.get("fechaBoletin"),
        "numero_aviso": it.get("numeroAviso"),
        "cantidad_caracteres": it.get("cantidadCaracteres"),
        "tiene_archivo": it.get("tieneArchivo"),
        "url_anexo": it.get("urlAnexo") or [],
    }
    if incluir_texto:
        out["contenido"] = contenido
    else:
        out["extracto"] = contenido[:max_snippet] + ("…" if len(contenido) > max_snippet else "")
    return out


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
@mcp.tool()
async def bo_buscar(
    consulta: str = "",
    fecha_desde: str = "",
    fecha_hasta: str = "",
    anio: int | None = None,
    clase_aviso: int | None = None,
    tipo_aviso_id: int | None = None,
    numero_boletin: int | None = None,
    incluir_texto: bool = False,
    pagina: int = 1,
    tamanio_pagina: int = 10,
) -> str:
    """Busca avisos y normas en el Boletin Oficial de Tucuman (fuente oficial en vivo).

    Herramienta principal. 'consulta' hace busqueda full-text por tokens sobre el
    texto completo de los avisos (la resuelve la API oficial). Los filtros se combinan.

    Parametros:
      consulta       : palabras a buscar en el cuerpo de los avisos (ej. 'prescripcion',
                       'impuesto inmobiliario', 'convenio multilateral', 'sellos').
                       Es busqueda por tokens: NO usar comillas ni frases exactas
                       (rompen la API oficial; se remueven automaticamente).
      fecha_desde    : YYYY-MM-DD o DD/MM/YYYY (fecha de boletin desde).
      fecha_hasta    : YYYY-MM-DD o DD/MM/YYYY (fecha de boletin hasta).
      anio           : filtra por anio de publicacion (alternativa a las fechas).
      clase_aviso    : 0 Todos | 1 Avisos | 2 Legislacion y Normativa Provincial.
      tipo_aviso_id  : id de tipo (DECRETO, RESOLUCIONES, LEY, ACORDADA, etc.; ver
                       bo_tipos_aviso). Si se omite clase_aviso, este servidor la
                       resuelve solo (la API exige clase junto al tipo).
      numero_boletin : numero de edicion del boletin.
      incluir_texto  : True devuelve el contenido COMPLETO de cada aviso; False (defecto)
                       un extracto de ~400 caracteres. Usar True al acotar a pocos resultados.
      pagina         : numero de pagina (>=1).
      tamanio_pagina : resultados por pagina (1-50; usar <=10 con incluir_texto=True).

    NO hay filtro por organismo emisor, expediente, anunciante ni instrumento: esos
    filtros devuelven error en la API oficial. Para acotar por emisor (ej. la DGR),
    usar 'consulta' con un termino discriminante del texto.

    Devuelve JSON con total, pagina, tamanio_pagina y resultados[] (metadatos +
    extracto o contenido). Para el PDF de la edicion completa usar bo_traer_edicion.
    """
    clase = clase_aviso
    if tipo_aviso_id is not None and clase is None:
        clase = await _clase_de_tipo(tipo_aviso_id)

    params = {
        "CadenaBuscar": (consulta or "").replace('"', " ").strip() or None,
        "FechaDesde": _fmt_fecha(fecha_desde),
        "FechaHasta": _fmt_fecha(fecha_hasta),
        "Anio": anio,
        "ClaseAviso": clase,
        "TipoAvisoId": tipo_aviso_id,
        "NumeroBoletin": numero_boletin,
        "PageNumber": max(1, pagina),
        "PageSize": max(1, min(tamanio_pagina, 50)),
    }
    data = await _get("", params)
    if isinstance(data, dict) and data.get("_error"):
        return json.dumps(data, ensure_ascii=False, indent=2)

    items = data.get("items", []) if isinstance(data, dict) else []
    out = {
        "total": data.get("totalCount"),
        "pagina": data.get("pageNumber"),
        "tamanio_pagina": data.get("pageSize"),
        "resultados": [_aviso_resumen(it, incluir_texto) for it in items],
        "_fuente": "https://boletintucuman.gob.ar (API oficial en vivo)",
    }
    if not items:
        out["_nota"] = "Sin coincidencias. Ampliar/afinar 'consulta' o el rango de fechas."
    return json.dumps(out, ensure_ascii=False, indent=2)


@mcp.tool()
async def bo_traer_edicion(fecha_boletin: str) -> str:
    """Devuelve la URL del PDF de la edicion completa del Boletin Oficial de un dia.

    Parametros:
      fecha_boletin : fecha de la edicion, YYYY-MM-DD o DD/MM/YYYY.

    Devuelve JSON {fecha, existe, url_pdf}. El PDF se sirve desde
    admin.boletintucuman.gob.ar. Si 'existe' es False, no hubo edicion ese dia.
    """
    f = _fmt_fecha(fecha_boletin)
    data = await _post("GetBoletin", {"FechaBoletin": f})
    if isinstance(data, dict) and data.get("_error"):
        return json.dumps(data, ensure_ascii=False, indent=2)
    return json.dumps({
        "fecha": f,
        "existe": data.get("existe"),
        "url_pdf": data.get("filePath"),
        "_fuente": "https://boletintucuman.gob.ar",
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def bo_tipos_aviso(clase_aviso: int | None = None) -> str:
    """Lista las clases de aviso y los tipos de aviso (con su id) para armar filtros.

    Parametros:
      clase_aviso : opcional. Si se indica (1 o 2) devuelve solo los tipos de esa clase;
                    si se omite, devuelve el catalogo completo de tipos.
    """
    if clase_aviso is not None:
        tipos = await _get("GetTipoAviso", {"ClaseAviso": clase_aviso})
    else:
        tipos = await _get("GetAllTipoAviso")
    if isinstance(tipos, dict) and tipos.get("_error"):
        return json.dumps(tipos, ensure_ascii=False, indent=2)
    lista = tipos if isinstance(tipos, list) else []
    return json.dumps({
        "clases_aviso": [{"id": k, "descripcion": v} for k, v in CLASES_AVISO.items()],
        "tipos_aviso": sorted(
            [{"id": t.get("id"), "descripcion": t.get("descripcion"),
              "clase_aviso": t.get("claseAviso")} for t in lista],
            key=lambda t: (t.get("descripcion") or ""),
        ),
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def bo_estado() -> str:
    """Health-check del conector: verifica que la API oficial responde y da un contador
    de cobertura (legislacion provincial del anio en curso). Usar antes de investigar,
    en la linea de ca_estado_indice / tfn_estado de los otros conectores.
    """
    anio = date.today().year
    data = await _get("", {"ClaseAviso": 2, "Anio": anio, "PageNumber": 1, "PageSize": 1})
    if isinstance(data, dict) and data.get("_error"):
        return json.dumps({"disponible": False, **data}, ensure_ascii=False, indent=2)
    return json.dumps({
        "disponible": True,
        "api_base": API_BASE,
        "anio_consultado": anio,
        "legislacion_provincial_en_anio": data.get("totalCount"),
        "_fuente": "https://boletintucuman.gob.ar",
    }, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
