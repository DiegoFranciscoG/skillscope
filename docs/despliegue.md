# Despliegue y auto-actualización

Skillscope es 100 % estático: un workflow de GitHub Actions recolecta, analiza e indexa, y publica
el resultado en GitHub Pages. No hay servidor, base de datos ni costo. Los números entre `#` remiten
a [investigacion.md](investigacion.md).

## 1. Publicar en GitHub Pages (una sola vez)

1. *Settings → Pages → Build and deployment → Source*: **GitHub Actions**.
2. *Settings → Actions → General → Workflow permissions*: dejar **Read repository contents** (cada
   job pide en el YAML solo los permisos que necesita).
3. Lanzar *Actions → Build and deploy → Run workflow*. El primer build tarda unos 6 minutos y
   publica en `https://<usuario>.github.io/skillscope/`.

Límites que aplican (#21, #23): sitio ≤ 1 GB, 100 GB/mes de ancho de banda blando, 10 GB de caché
por repositorio, 6 h por job. El índice completo pesa unos pocos MB.

## 2. Variables y secretos del repositorio

Ninguno es obligatorio: sin ellos el build usa el `GITHUB_TOKEN` del propio workflow y las fuentes
sociales que no piden clave (Hacker News, Stack Exchange sin clave, DEV, Mastodon).

| Nombre | Tipo | Para qué | Cómo obtenerlo |
|---|---|---|---|
| `SKILLSCOPE_GH_TOKEN` | Secreto | Sube el presupuesto de 1.000 a 5.000 llamadas REST/h (#12). | Token *fine-grained* con acceso **Public repositories (read-only)** y **ningún** permiso adicional. |
| `SKILLSCOPE_SITE_URL` | Variable | Solo si usas dominio propio; si no, se toma de `configure-pages`. | — |
| `SKILLSCOPE_STACKEXCHANGE_KEY` | Secreto | Cuota diaria de la app en vez de 300 por IP (#32). | Registrar la app en Stack Apps (#33). |
| `SKILLSCOPE_BLUESKY_HANDLE` / `SKILLSCOPE_BLUESKY_APP_PASSWORD` | Variable / Secreto | Búsqueda de menciones en Bluesky (#38). | *App password* de una cuenta dedicada, nunca la contraseña principal. |
| `SKILLSCOPE_YOUTUBE_API_KEY` | Secreto | Menciones en YouTube (#37). | Clave de API restringida a *YouTube Data API v3*. |
| `SKILLSCOPE_REDDIT_*` | Secreto / Variable | Apagado por defecto (S5). | Solo con acceso aprobado por Reddit (#36). |

El pipeline lee únicamente variables con prefijo `SKILLSCOPE_`, para que una clave global del
equipo de desarrollo nunca entre por accidente. Las claves viajan en cabeceras, no en la URL, y el
log de `httpx` está silenciado.

## 3. Las tres capas de auto-actualización

| Capa | Dónde | Frecuencia | Qué cubre |
|---|---|---|---|
| 1. Cron interno | `build.yml` | Minutos 7, 22, 37 y 52 de cada hora | Caso normal. Fuera del minuto 0 porque GitHub retrasa o descarta trabajos al inicio de la hora (#16). |
| 2. Disparo externo | cron-job.org (#47) | Cada 30 min | Ejecuciones de cron descartadas por GitHub. |
| 3. Vigilante | `keepalive.yml` | Cada hora y el día 1 de cada mes | Si pasan 90 min sin build exitoso lo relanza y abre un issue `keepalive`. Cada mes reactiva los workflows y empuja un commit vacío a la rama `keepalive` (nunca a `main`) para no llegar a los 60 días sin actividad (S1). También borra cachés viejas del estado. |

Peor caso de presupuesto con `GITHUB_TOKEN`: 6 builds/h × 140 llamadas REST = 840 de 1.000 (#12);
GraphQL 6 × 120 = 720 de 1.000 puntos (#15). El cálculo completo está en [fuentes.md](fuentes.md).

### Configurar la capa 2 (cron-job.org)

1. Crear un token *fine-grained* limitado a **este** repositorio con un único permiso:
   **Actions: Read and write** (#20). Ponerle vencimiento (90 días) y anotar la fecha de rotación.
   Con ese permiso solo puede disparar, reactivar o cancelar workflows: no lee código privado,
   no escribe en el repositorio y no accede a los secretos.
2. En cron-job.org crear el trabajo **Disparar build** (cada 30 min):
   - Método `POST`, URL
     `https://api.github.com/repos/<usuario>/skillscope/actions/workflows/build.yml/dispatches`
   - Cabeceras: `Accept: application/vnd.github+json`,
     `Authorization: Bearer <token>`, `X-GitHub-Api-Version: 2026-03-10`
   - Cuerpo: `{"ref":"main"}`. Respuesta esperada: `204` (#19).
3. Crear el trabajo **Reactivar build** (una vez al día), igual pero con método `PUT` y URL
   `…/actions/workflows/build.yml/enable` (sin cuerpo). Respuesta esperada: `204`.
4. Activar los avisos por correo de cron-job.org: desactiva un trabajo tras 25 fallos seguidos.

El token vive solo en cron-job.org. Si se filtra, el daño máximo es lanzar builds de más, que
igualmente respetan los presupuestos por hora porque el pipeline consulta `/rate_limit` antes de
gastar y deja un 10 % de reserva.

## 4. Verificar que todo funciona

- `https://<usuario>.github.io/skillscope/data/index.json` → `built_at` con menos de 30 min.
- La web muestra «Actualizado hace N min» y el estado de cada fuente en el pie.
- *Actions → Build and deploy* → el resumen de cada ejecución trae los repositorios publicados,
  la duración y una tabla con el estado de cada fuente y las llamadas que gastó.
- `feed.xml`, `feed.json`, `sitemap.xml` y `robots.txt` responden en la raíz del sitio.

## 5. Ejecutar en local

Ver la sección «Cómo ejecutar en local» del [README](../README.md): `docker compose up --build`
levanta el sitio con los datos ficticios de `data/samples` en `http://localhost:8080`.
