# Política de seguridad

## Reportar una vulnerabilidad

No abras un issue público. Usa el aviso privado de GitHub
(*Security → Report a vulnerability*) con los pasos para reproducir el problema.
Respondo en un máximo de 7 días.

## Superficie de ataque

Skillscope no tiene servidor, base de datos, cuentas ni formularios: es un sitio estático que un
workflow regenera. Los riesgos relevantes y cómo se cubren:

| Riesgo | Control |
|---|---|
| Texto de terceros (README, SKILL.md, preguntas) inyectando HTML o scripts | La web nunca usa `innerHTML`; CSP con `require-trusted-types-for 'script'` hace fallar cualquier regresión. Las páginas estáticas escapan todo y el JSON-LD escapa `<`, `>` y `&`. |
| Rutas manipuladas con nombres de repo | Solo se escriben carpetas cuyo `owner/name` cumple el juego de caracteres de GitHub (`indexer/pages.py`). |
| YAML malicioso en frontmatter | `yaml.safe_load`, sin alias, tamaño acotado. |
| Secretos publicados por un repo analizado | Las evidencias que parecen credenciales se redactan antes de publicarse. |
| Claves de API en el front | No existen: `npm run scan:bundle` falla el build si aparece un token, una cabecera `Authorization` o `process.env` en lo publicado. |
| Búsqueda en vivo en GitHub | Solo al pulsar el botón; sin credenciales (`credentials: "omit"`), sin referrer; la CSP abre `connect-src` únicamente a `https://api.github.com`; se aceptan solo ids `owner/repo` válidos y enlaces `https://github.com/<id>`; el texto llega por `textContent`. |
| Issues de sugerencia (entrada de cualquier visitante) | Solo se extrae un `owner/repo` con las reglas de nombres de GitHub, máximo 20 por build, sin volver a encolar repos ya analizados; el costo de un abuso es como mucho una consulta de metadatos por sugerencia. |
| Popularidad inflada | Si más de la mitad de las estrellas llegó en 7 días (y son ≥ 1.000), la ficha lo dice; no cambia el puntaje porque no es una prueba. |
| Claves en logs | Las claves viajan en cabeceras; las URL se sanitizan antes de guardarse y el log de `httpx` está silenciado. |
| Cadena de suministro de CI | Acciones fijadas por SHA de commit, `permissions: contents: read` por defecto, gitleaks con checksum verificado y Dependabot semanal (`tests/unit/test_workflows.py`). CodeQL (Python, TypeScript y Actions) activado en el repositorio. |
| Contenedor local | Imágenes con versión exacta, nginx sin privilegios, sistema de archivos de solo lectura, `cap_drop: ALL`, `no-new-privileges`, cabeceras de seguridad completas. |
| Abuso de APIs de terceros | Presupuesto por recurso, reserva del 10 %, `ETag`, back-off y respeto de `Retry-After` y `backoff`. |

## Datos personales

Solo se guardan datos públicos de repositorios y conteos o enlaces de menciones. No se guardan
correos, nombres reales ni perfiles. Cualquier dueño puede excluir su repositorio con el topic
`skillscope-optout` o con un issue «Excluir mi repositorio».
