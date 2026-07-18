# MCP · Boletín Oficial de la Provincia de Tucumán

Conector MCP (proxy directo, sin índice propio) sobre la API oficial del
Boletín Oficial de Tucumán. Da búsqueda full-text en vivo del texto de los
avisos y normas provinciales, sin crawler ni OCR.

## Arquitectura

| Capa      | Host                                   |
|-----------|----------------------------------------|
| Frontend  | `https://boletintucuman.gob.ar` (Angular) |
| API REST  | `https://api.boletintucuman.gob.ar` (.NET / Swagger V2.0) |
| PDFs      | `https://admin.boletintucuman.gob.ar` (ediciones y anexos) |

La API expone `CadenaBuscar` (full-text server-side) y devuelve el `contenido`
en texto plano de cada aviso ⇒ el conector solo la traduce a herramientas MCP.
Es el mismo patrón que **tfn-mcp** (proxy en vivo), no el de índice propio de
COMARB/TFA. Mantenimiento y costo mínimos; el dato está siempre actualizado.

## Herramientas

| Tool | Función |
|------|---------|
| `bo_buscar` | Búsqueda principal: texto + fecha/año + clase + tipo de aviso + nº de boletín, con paginación y contenido completo opcional. |
| `bo_traer_edicion` | URL del PDF de la edición completa de un día. |
| `bo_tipos_aviso` | Catálogo de clases y tipos de aviso (para armar filtros). |
| `bo_estado` | Health-check + contador de cobertura. |

## Limitaciones conocidas de la API oficial (verificadas 07/2026)

Estos filtros devuelven **HTTP 500** en el backend oficial y por eso NO se
exponen: `OrganismoId`, `Expediente`, `NumeroInstrumento`, `Anunciante`, y las
**comillas** en `CadenaBuscar` (no hay búsqueda por frase exacta; es por tokens).
Para acotar por emisor (p. ej. la DGR) se usa `consulta` con un término
discriminante del texto. La API tampoco ofrece parámetro de ordenamiento: para
"lo más reciente" conviene acotar con `fecha_desde`/`fecha_hasta`.

## Deploy en Railway

1. Subir estos archivos a un repo de GitHub.
2. En Railway: **New Project → Deploy from GitHub repo**.
3. Railway detecta el `Dockerfile` y expone el puerto vía `PORT` (automático).
4. La URL pública del servicio termina en `/mcp` (transporte `streamable-http`).
5. Agregar esa URL como conector en Claude. La API es pública, sin autenticación.

Sin variables de entorno obligatorias. Opcional: `BO_API_BASE` para apuntar a
otro host de la API.
