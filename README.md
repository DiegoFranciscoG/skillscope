# Skillscope

**El buscador que encuentra solo, explica y puntúa cada skill y plugin para agentes de código publicado en GitHub, con análisis de riesgo y comando de instalación exacto. Estático, USD 0 y actualizado cada ~30 minutos.**

[![CI](https://github.com/DiegoFranciscoG/skillscope/actions/workflows/ci.yml/badge.svg)](https://github.com/DiegoFranciscoG/skillscope/actions/workflows/ci.yml)
[![Build and deploy](https://github.com/DiegoFranciscoG/skillscope/actions/workflows/build.yml/badge.svg)](https://github.com/DiegoFranciscoG/skillscope/actions/workflows/build.yml)
![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-7.0-3178C6?logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-8.3-646CFF?logo=vite&logoColor=white)
![Lighthouse](https://img.shields.io/badge/Lighthouse-99%20%2F%20100-0CCE6B?logo=lighthouse&logoColor=white)
[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-green)](LICENSE)
[![Demo](https://img.shields.io/badge/demo-GitHub%20Pages-222?logo=github)](https://diegofranciscog.github.io/skillscope/)

## Demo en vivo

**https://diegofranciscog.github.io/skillscope/** — no necesita usuario ni contraseña: es un sitio
público de solo lectura. Prueba a escribir «revisar pull requests», «migrar COBOL» o abre la
pestaña **Huecos**.

En local, `docker compose up --build` levanta la misma web con 43 repositorios **ficticios** de
ejemplo (marcados como «ejemplo ficticio») en `http://localhost:8080`, sin red ni claves.

![Recorrido: explorar, buscar por necesidad, abrir una ficha y ver los huecos del ecosistema](docs/img/demo.gif)

| Búsqueda por necesidad y ficha | Huecos del ecosistema | Móvil (tema oscuro) |
|---|---|---|
| ![Búsqueda y ficha](docs/img/busqueda-ficha.png) | ![Huecos](docs/img/huecos.png) | ![Móvil](docs/img/movil.png) |

| Riesgos con evidencia (archivo, línea y fragmento) | Página estática por repo (schema.org) |
|---|---|
| ![Banderas de riesgo de un paquete ficticio malicioso](docs/img/riesgos.png) | ![Página estática indexable](docs/img/pagina-estatica.png) |

## Problema que resuelve

Las skills, plugins, marketplaces y servidores MCP para Claude Code se publican a diario en
GitHub, dispersos en miles de repositorios con formatos distintos. Quien quiere usar uno no sabe
**cuál resuelve su tarea, si sigue mantenido, cómo se instala ni qué riesgo corre** al darle a un
agente acceso a su terminal. Y quien quiere crear uno no sabe **qué falta**.

Skillscope descubre esos repositorios por su cuenta, lee sus archivos (sin ejecutar nada), los
clasifica, escribe un resumen propio, calcula un puntaje 0–100 con fórmulas públicas, señala
riesgos con evidencia y recomienda por necesidad. Las redes sociales solo aportan señales de
interés y demanda; nunca son la fuente del catálogo.

## Funcionalidades

- **Descubrimiento autónomo**: búsqueda por código, topics y repositorios en GitHub, con cortes por
  fecha y tamaño para superar el tope de 1.000 resultados, más una semilla de 200 repos reales.
- **Análisis estático** de `SKILL.md`, `plugin.json`, `marketplace.json`, agentes, comandos, hooks y
  servidores MCP: valida el formato, detecta 9 tipos y 14 categorías y redacta «qué hace» y
  «cuándo usarla» sin copiar el README (prueba automática de > 15 palabras seguidas).
- **Puntaje transparente**: calidad 25 + mantenimiento 20 + adopción 20 + interés social 15 +
  utilidad 20 − riesgo 25, con el desglose de cada factor en la ficha ([algoritmo](docs/algoritmo.md)).
- **Riesgo con evidencia**: inyección de instrucciones, exfiltración por red, pedido de credenciales,
  ejecución no explicada, descarga de binarios, código ofuscado, permisos amplios, dependencias sin
  fijar o sin licencia; cada bandera muestra archivo, línea y fragmento (los secretos se redactan).
- **Búsqueda por necesidad** en el navegador: BM25 + embeddings LSA cuantizados, en tres bloques
  («Resuelve exactamente eso», «Se le parece», «Se usan junto con eso») y en < 100 ms con 3.000 repos.
- **Comando de instalación exacto** con botón copiar (`/plugin marketplace add …`, `/plugin install …`,
  `claude mcp add …` o `git clone` + copia a `~/.claude/skills`).
- **Listas**: más usadas, más mencionadas, en tendencia, más útiles, más seguras, más riesgosas y
  más necesarias por categoría.
- **Huecos del ecosistema**: temas que la gente pregunta en Stack Overflow y que ningún repo de
  calidad cubre, con enlace para crear la skill.
- **Actualización en vivo sin recargar**: la web consulta el índice cada 5 min con `ETag`; si hay un
  build nuevo reemplaza el contenido en su sitio y conserva el scroll y el texto de búsqueda.
- **Publicación abierta**: API JSON estática, RSS 2.0, JSON Feed 1.1, página estática por repo con
  schema.org, `sitemap.xml` e insignia SVG para el README de cada repo:
  ![Insignia de ejemplo con puntaje 78](docs/img/insignia-ejemplo.svg)
- **Retiro inmediato**: el dueño de un repo lo excluye con el topic `skillscope-optout` o un issue.

## Arquitectura

```mermaid
flowchart LR
  subgraph Actions["GitHub Actions (cron cada 15 min · disparo externo · vigilante)"]
    C["collector<br/>GitHub REST/GraphQL/Search<br/>npm · HN · Stack Exchange<br/>DEV · Mastodon · Bluesky · YouTube"]
    A["analyzer<br/>frontmatter · tipo · categoría<br/>riesgo · instalación · resumen"]
    I["indexer<br/>puntaje · listas · huecos<br/>LSA + BM25 · feeds · páginas"]
    S[("caché de Actions<br/>ETag · cursores<br/>análisis por commit")]
    C --> A --> I
    S <--> C
    S <--> A
  end
  I -->|"artefacto estático"| P["GitHub Pages<br/>index.json · detail/*.json<br/>embeddings.bin · feeds · s/*"]
  P -->|"ETag cada 5 min"| W["Navegador<br/>TypeScript sin framework<br/>búsqueda local"]
  X["cron-job.org<br/>workflow_dispatch"] -.-> Actions
```

Cada build gasta un presupuesto fijo por API (consulta `/rate_limit` antes y deja 10 % de reserva),
reutiliza respuestas con `ETag` (un `304` no cuesta cuota) y solo reanaliza los repos cuyo commit
cambió. Si una red social falla, el build sigue y la web marca esa fuente como caída.

## Stack y por qué

| Pieza | Elección | Por qué |
|---|---|---|
| Recolección y análisis | Python 3.14, httpx, PyYAML (`safe_load`), numpy | Ecosistema de datos maduro; `httpx` con `MockTransport` permite probar límites de API sin red. |
| Búsqueda semántica | LSA (TF-IDF + SVD aleatorizada) cuantizada a int8 | Sin modelo neuronal ni API de pago: menos de 1 MB aun con 3.000 repos y corre en el navegador. |
| Búsqueda léxica | BM25 (`k1 = 1,2`, `b = 0,75`) | Estándar de recuperación de información, explicable y rápido. |
| Front | TypeScript 7 + Vite 8, sin framework | 36 KB de JS; Lighthouse 99–100; CSP estricta con Trusted Types. |
| Hosting | GitHub Pages | Gratis, CDN global, cero servidores que mantener. |
| Orquestación | GitHub Actions (cron + `workflow_dispatch`) | Gratis en repos públicos; caché para el estado entre builds. |
| Calidad | ruff, mypy estricto, pytest, Vitest, Playwright, Lighthouse | Cada criterio de aceptación es una prueba automática. |
| Local | Docker multi-stage + nginx sin privilegios | Un comando levanta todo con datos de ejemplo y cabeceras de seguridad reales. |

## Modelo de datos

```mermaid
erDiagram
  BUILD ||--o{ REPO : "publica"
  BUILD ||--o{ SOURCE_STATUS : "registra"
  REPO ||--o{ ARTIFACT : "contiene"
  REPO ||--|| SCORE : "tiene"
  SCORE ||--o{ SCORE_FACTOR : "se desglosa en"
  REPO ||--o{ RISK_FLAG : "tiene"
  RISK_FLAG ||--o{ EVIDENCE : "se prueba con"
  REPO ||--o| INSTALL : "se instala con"
  REPO ||--o{ SIGNAL_DAY : "serie diaria"
  REPO ||--o{ MENTION : "es mencionado"
  REPO }o--o{ COLLECTION : "aparece en"
  DEMAND_ITEM }o--|| TOPIC : "se agrupa en"
  TOPIC ||--o| GAP : "si no hay oferta"
  REPO {
    string id PK "owner/repo"
    string type "skill, plugin, marketplace, mcp_server..."
    string category "14 categorías"
    int score "0-100"
    string summary "propio"
  }
  RISK_FLAG {
    string id "catálogo de banderas"
    int penalty "1-10"
  }
  DEMAND_ITEM {
    string source "stackexchange"
    string title "CC BY-SA, con autor y enlace"
    bool answered
  }
```

Catálogos, reglas de validación, restricciones y formato de cada archivo publicado:
[docs/modelo-datos.md](docs/modelo-datos.md).

## Cómo ejecutar en local

### Con Docker

```bash
docker compose up --build
```

Abre `http://localhost:8080`. La imagen ejecuta el pipeline completo en modo sin conexión (43 repos
ficticios de `data/samples`), compila el front, escanea el bundle en busca de claves y lo sirve con
nginx sin privilegios, sistema de archivos de solo lectura y `HEALTHCHECK`.

### Sin Docker

Requisitos: [uv](https://docs.astral.sh/uv/) y Node.js 24 LTS.

```bash
uv sync
uv run python -m pipeline build --offline
cd web
npm ci
npm run build
npm run preview
```

Abre `http://localhost:4173`. Para desarrollar el front con recarga en caliente: `npm run dev`.

### Build en línea (datos reales)

```bash
uv run python -m pipeline build
```

Necesita `SKILLSCOPE_GITHUB_TOKEN` y `SKILLSCOPE_SITE_URL` (ver la tabla); sin ellas no arranca.

## Variables de entorno

Solo las usa el build en línea. El modo sin conexión, Docker y los tests no leen ninguna. Plantilla
en [.env.example](.env.example); en Actions van como *secrets* o *variables* ([despliegue](docs/despliegue.md)).

| Variable | Obligatoria | Uso |
|---|---|---|
| `SKILLSCOPE_GITHUB_TOKEN` | Sí (en línea) | Token de GitHub de solo lectura de repos públicos. |
| `SKILLSCOPE_SITE_URL` | Sí (en línea) | URL pública del sitio, para feeds, sitemap y páginas. |
| `SKILLSCOPE_REPOSITORY` | No | `owner/repo` donde se leen los issues de retiro. |
| `SKILLSCOPE_MAX_SECONDS` | No | Tiempo máximo de recolección (360 s por defecto). |
| `SKILLSCOPE_STACKEXCHANGE_KEY` | No | Cuota de la app de Stack Exchange. |
| `SKILLSCOPE_BLUESKY_HANDLE`, `SKILLSCOPE_BLUESKY_APP_PASSWORD` | No | Menciones en Bluesky. |
| `SKILLSCOPE_YOUTUBE_API_KEY` | No | Menciones en YouTube. |
| `SKILLSCOPE_REDDIT_CLIENT_ID`, `SKILLSCOPE_REDDIT_CLIENT_SECRET`, `SKILLSCOPE_REDDIT_USER_AGENT` | No | Apagado salvo acceso aprobado por Reddit. |

Todas llevan el prefijo `SKILLSCOPE_` para que una clave global del equipo nunca entre por error.

## API

No hay servidor: la API pública son archivos JSON estáticos que cada build regenera, con `ETag` y
caché de CDN. No hay Swagger porque no hay endpoints dinámicos; la colección de ejemplos está en
[docs/api.http](docs/api.http) y el esquema de cada archivo en [docs/modelo-datos.md](docs/modelo-datos.md).

| Recurso | Contenido |
|---|---|
| `GET /data/index.json` | Build, totales, estado de cada fuente, lista ligera de repos y listas derivadas. |
| `GET /data/detail/<categoria>.json` | Ficha completa: artefactos, factores del puntaje, riesgos con evidencia, instalación. |
| `GET /data/demand.json` | Preguntas de demanda con atribución, temas y huecos. |
| `GET /data/signals.json` | Series diarias de estrellas, forks y menciones. |
| `GET /data/embeddings.bin` + `embeddings.json` | Vectores int8 de documentos y términos para la búsqueda local. |
| `GET /feed.xml`, `GET /feed.json` | Boletín semanal (RSS 2.0 y JSON Feed 1.1). |
| `GET /s/<owner>/<repo>/` | Página estática con schema.org `SoftwareSourceCode`. |
| `GET /badge/<owner>/<repo>.svg` | Insignia con el puntaje. |
| `GET /sitemap.xml`, `GET /robots.txt` | Indexación en buscadores. |

Enlaces profundos de la web: `?q=<búsqueda>`, `?tab=<lista>`, `?type=`, `?cat=`, `?risk=`, `?sort=`
y `?r=<owner/repo>` para abrir una ficha.

## Tests y cobertura

```bash
uv run pytest --cov                 # 225 pruebas Python, cobertura 91,6 % (mínimo 70 %)
cd web && npm run test:coverage     # 40 pruebas Vitest, 87 % de sentencias
npm run e2e                         # 14 pruebas Playwright en escritorio y móvil
npm run lighthouse                  # mediana de 3 corridas, falla si < 95
```

| Criterio de aceptación | Cómo se verifica |
|---|---|
| Build < 10 min sin exceder límites de API | `tests/integration/test_collect_github.py` corre la recolección contra una API simulada con cuotas mínimas y exige cero excesos y la reserva del 10 %; `tests/unit/test_http.py` cubre `x-ratelimit-*`, `retry-after` y límites secundarios; `build.yml` corta a los 10 min y el pipeline a los 360 s. |
| Ningún README copiado | `tests/integration/test_analyze_samples.py` falla si un resumen comparte > 15 palabras seguidas con el original. |
| Actualización sin recargar conserva scroll y búsqueda | `web/e2e/site.spec.ts` cambia el `build_id` y comprueba posición y texto. |
| Lighthouse ≥ 95 en rendimiento y accesibilidad | `web/scripts/lighthouse.mjs`: móvil 99 / 100 / 100 / 100 y escritorio 100 / 100 / 100 / 100 (rendimiento, accesibilidad, buenas prácticas, SEO). |
| Búsqueda < 100 ms con 3.000 repos | `web/test/search.test.ts` genera 3.000 documentos y mide. |
| Cero claves en el front | `web/scripts/scan-bundle.mjs` escanea todo lo publicado en CI y en Docker; `web/test/scan.test.ts` prueba que detecta un token plantado. |
| El sitio funciona si una red social cae | `tests/integration/test_build_offline.py` tumba una fuente y verifica el build y su estado. |
| Cobertura ≥ 70 % en collector, analyzer e indexer | `fail_under = 70` en `pyproject.toml` (actual 91,6 %). |

## Despliegue

1. *Settings → Pages → Source*: **GitHub Actions**.
2. El workflow `build.yml` corre a los minutos 7, 22, 37 y 52 de cada hora, recolecta, analiza,
   publica en Pages y guarda el estado en la caché de Actions.
3. Cada build agenda el siguiente: de inmediato mientras haya mucha cola y cuota, o tras 20 min de
   espera en el entorno `cadence` (la espera no consume minutos). Funciona aunque GitHub no
   dispare su cron.
4. `keepalive.yml` relanza el build si pasan 90 min sin éxito, abre un issue de alerta y cada mes
   evita la desactivación por 60 días de inactividad.

Paso a paso, presupuesto de llamadas y verificación: [docs/despliegue.md](docs/despliegue.md).

## Seguridad aplicada

- **Sin superficie de servidor**: no hay backend, base de datos, cuentas ni formularios.
- **Contenido de terceros como dato, nunca como código**: la web no usa `innerHTML`; CSP con
  `require-trusted-types-for 'script'`; el JSON-LD escapa `<`, `>` y `&`; rutas de páginas
  validadas contra el juego de caracteres de GitHub.
- **YAML seguro**: `safe_load`, sin anclas ni alias, tamaño acotado.
- **Cero claves en el front** y en el bundle (escaneo en CI); las claves de API viajan en cabeceras y
  nunca se registran.
- **Cadena de suministro**: acciones fijadas por SHA de commit, permisos mínimos por job, gitleaks con
  checksum verificado en cada push, Dependabot semanal para uv, npm, Actions y Docker.
- **Contenedor**: imágenes con versión exacta, usuario no root, `read_only`, `cap_drop: ALL`,
  `no-new-privileges`, CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` y
  `Permissions-Policy`.
- **Buen ciudadano de las APIs**: presupuesto por recurso, reserva del 10 %, `ETag`, back-off con
  *jitter* y respeto de `Retry-After` y `backoff`.
- **Privacidad (LOPDP / minimización)**: solo datos públicos de repos; de las redes, conteos y
  enlaces; retiro inmediato por el dueño. Política completa en [SECURITY.md](SECURITY.md).

## Decisiones técnicas

- **Estático en vez de API con base de datos**: el catálogo cambia cada 30 min, no cada segundo.
  Precalcular todo en CI y servir JSON desde una CDN cuesta USD 0, escala solo y elimina la
  superficie de ataque de un servidor.
- **Búsqueda en el navegador con LSA + BM25**: un modelo de embeddings neuronal pediría una API de
  pago o decenas de MB de pesos. LSA cuantizado a int8 da búsqueda semántica en menos de 1 MB y BM25 asegura que
  las coincidencias literales manden; la *cobertura* de la consulta evita falsos positivos.
- **Análisis por commit en caché**: reanalizar solo lo que cambió mantiene cada build dentro de
  presupuesto aunque el índice crezca a miles de repos.
- **Resumen propio, no copia**: el texto sale de los metadatos y del frontmatter con plantillas, y una
  prueba impide que se cuele una frase del README. Respeta derechos de autor y da un formato uniforme.
- **Riesgo con salvaguardas contra falsos positivos**: se ignoran comentarios, citas, negaciones y
  scripts de build propios del repo; validado a mano sobre 115 repos reales.
- **Redes sociales como señal, no como fuente**: X y Meta se descartaron (sin nivel gratuito útil o
  recolección prohibida); Reddit queda apagado sin aprobación; DEV solo aporta conteos.
- **Tres capas de actualización**: el cron de GitHub se retrasa o descarta en horas pico, así que un
  disparo externo y un vigilante cubren los huecos.

## Roadmap

- Diferencias entre versiones de una skill (qué cambió y si subió el riesgo).
- Detección de duplicados y *forks* casi idénticos.
- Más ecosistemas de agentes con el mismo formato de skills.
- Historial público del puntaje por repo y alertas por feed cuando sube el riesgo.
- Etiquetas de idioma y nivel de madurez sugeridas por la comunidad mediante issues.

## Fuentes de datos y licencias

| Fuente | Uso | Términos |
|---|---|---|
| GitHub REST, GraphQL y Search | Catálogo, archivos y metadatos | [Términos de GitHub](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service): solo repos públicos, sin copiar contenido; cada ficha enlaza al original y muestra su licencia. |
| npm registry (descargas) | Adopción de paquetes MCP | API pública de conteos. |
| Stack Exchange API | Demanda y huecos | Contenido **CC BY-SA 4.0**: se muestran título, autor y enlace al original. |
| Hacker News (Algolia) | Menciones | API pública. |
| DEV (Forem) | Menciones | Solo conteos y enlaces. |
| Mastodon | Menciones | Timelines públicas por etiqueta. |
| Bluesky, YouTube | Menciones (opcionales) | Con credenciales propias y dentro de sus cuotas. |

Investigación completa con 57 fuentes, verificaciones propias y supuestos:
[docs/investigacion.md](docs/investigacion.md) · límites y presupuesto por fuente:
[docs/fuentes.md](docs/fuentes.md). Los datos de `data/samples` son **ficticios**: todos los dueños
llevan el prefijo `demo_` (GitHub no admite `_` en nombres de usuario ni de organización, así que
nunca coinciden con una cuenta real), los autores son inventados y sus enlaces apuntan a `example.com`.

Código bajo licencia [MIT](LICENSE).

## Autor

**Diego Francisco Granda Zhingre** · [GitHub](https://github.com/DiegoFranciscoG) · [LinkedIn](https://www.linkedin.com/in/diego-francisco-g-61b793254/)
