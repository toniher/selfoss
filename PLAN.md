# Plan: MCP server for selfoss

## Context
The goal is to let MCP clients (Claude Code or Claude Desktop) work with a selfoss instance: read newest, unread and starred entries, mark or star them, use tags, and add or edit sources. The fork has to stay easy to rebase on upstream fossar/selfoss. Upstream also bans AI-generated contributions, so this will never be merged upstream.

Decision (confirmed with the user): build a **standalone Python MCP server** in a new top-level `mcp/` directory. It is a thin client of selfoss's **documented, semver-versioned REST API** (`docs/api-description.json`, apiversion 8.0.0, reported at `GET /api/about`). It needs no changes to selfoss PHP, composer or client files, so rebases never conflict. It runs over **stdio** for local use and **Streamable HTTP** for exposure next to the website behind the same reverse proxy (e.g. `https://host/mcp`).

## Relevant existing API (all routes in `index.php`)
- Auth: `POST /login` (form `username`, `password`) → session cookie. `DELETE /api/session/current` to log out. `RequestOrSession` (`src/helpers/Authentication/Services/RequestOrSession.php`) also accepts credentials on any request, but a cookie session avoids putting passwords in query strings. Selfoss trusts localhost/CLI or runs with no credentials when `username`/`password` are unset (`AuthenticationFactory`).
- Items: `GET /items`, with params `type` (unread|starred|omitted = newest), `search`, `tag`, `source`, `offset`, `items` (max 200) and `updatedsince`. These are parsed in `src/daos/ItemOptions.php`. `GET /stats` returns counts.
- Status: `POST /mark` (JSON array of ids), `POST /unmark/{id}`, `POST /starr/{id}`, `POST /unstarr/{id}`.
- Tags: `GET /tags` returns name and colors; `POST /tags/color` sets `tag`, `color`. Tags belong to **sources**, and items inherit them.
- Sources: `GET /sources/list`, `GET /sources/spouts` (spout classes and their params), `POST /source` (add; JSON `SourceRequest`: `title`, `spout`, `tags`, `filter`, plus spout params such as `url`), `POST /source/{id}` (full replace), `DELETE /source/{id}`. `POST /source/{id}/update` refreshes a source, but it is undocumented, so treat it as best-effort.
- Version: `GET /api/about` → `version`, `apiversion`.

## Layout (all new files)
```
mcp/
  pyproject.toml          # deps: mcp (official SDK, FastMCP), httpx; entry point `selfoss-mcp`
  README.md               # setup, env vars, Claude Code config, reverse-proxy snippet
  selfoss_mcp/
    __init__.py
    client.py             # SelfossClient: httpx.Client, login, re-login once on 403
    server.py             # FastMCP tools + main(): --transport stdio|http, --host, --port
  tests/
    test_e2e.py           # drives tools against a real selfoss via the existing integration harness
  Dockerfile              # python:3.12-slim, pip install ., CMD selfoss-mcp --transport http --host 0.0.0.0
docker/                   # see "Docker" below
  Dockerfile              # multi-stage, build context = repo root
  Dockerfile.dockerignore # BuildKit per-Dockerfile ignore, so no root .dockerignore is needed
  nginx.conf              # from docker-selfoss nginx-default.conf, with the X-Real-IP fix and tightened deny rules
  supervisord.conf        # copied as is (php-fpm8.2 + nginx)
  entrypoint.sh           # mkdir -p data/{cache,sqlite,favicons,thumbnails} + chown, then exec "$@"
  compose.yaml            # services: selfoss + mcp
  nginx-proxy.conf        # generic host reverse proxy for / and /mcp (goes in the host's nginx, not the image)
.github/workflows/mcp.yaml     # separate workflow file, so no conflict with upstream main.yaml
.github/workflows/docker.yaml  # builds both images
```

## Implementation
1. **`client.py`**: one small class wrapping the REST calls listed above. It is configured from env vars `SELFOSS_URL`, `SELFOSS_USERNAME` and `SELFOSS_PASSWORD` (credentials optional). It logs in lazily, raises for HTTP errors, and surfaces selfoss `jsonError` payloads (for example filter syntax errors from `Sources\Write`) as tool errors. The session cookie is tracked by hand instead of relying on httpx's cookie jar: found by testing against the real compose network, where PHP sets the `PHPSESSID` cookie's `Domain` to the bare service name (`selfoss`), and stdlib `http.cookiejar` silently refuses to resend cookies for a domain with no dot in it — every authenticated call was otherwise a silent 403.
2. **API version guard**: on first use, read `/api/about`. If the `apiversion` major is not 8, fail with a clear message. This is how upstream breaking changes get caught. Minor bumps are fine because semver covers the documented endpoints.
3. **Tools in `server.py`** (with MCP annotations: read-only hint on getters, destructive hint on delete):
   - `get_stats`: total, unread and starred counts.
   - `list_items(type="unread"|"starred"|"newest", tag?, source_id?, search?, offset=0, limit=50, updated_since?, include_content=False)`: by default returns compact items (id, title as plain text, source, tags, datetime, link, unread, starred). Content (HTML → plain text via stdlib `html.parser`, truncated) is included only when asked, to keep token use low.
   - `mark_read(ids: list[int])`, `mark_unread(id)`, `star(id)`, `unstar(id)`.
   - `list_tags()`, `set_tag_color(tag, color)`.
   - `list_sources()`, `list_spouts()` (lets the model find the required params for non-RSS spouts).
   - `add_source(url?, title?, spout="spouts\\rss\\feed", tags=[], filter?, params={})`. Selfoss fetches the title itself when it is empty.
   - `update_source(id, title?, tags?, filter?, params?)`: fetches the current source from `/sources/list`, merges the changes and POSTs the full payload, because the endpoint replaces the whole record. This is also how tags are added to or removed from a source.
   - `delete_source(id)`, `refresh_source(id)` (undocumented endpoint; noted in the docstring).
   - Skipped for now: OPML import/export and password hashing. Add them if needed.
4. **Transports**: `selfoss-mcp` (stdio, default) and `selfoss-mcp --transport http --host 127.0.0.1 --port 8765`. In HTTP mode, a small Starlette middleware requires `Authorization: Bearer $SELFOSS_MCP_TOKEN` and refuses to start without the token. The default bind is localhost, so the reverse proxy decides what is exposed. The README points to `docker/nginx-proxy.conf` for the `location /mcp` proxy setup.
5. **CI** (`.github/workflows/mcp.yaml`): runs on changes to `mcp/**`, `docs/api-description.json` or `index.php`. It installs selfoss the same way `main.yaml` does (nix-shell `-A ci`, `npm run install-dependencies`) and runs `mcp/tests`. Triggering on upstream API or route changes is the early warning when rebasing.

## Docker
This is based on https://github.com/toniher/docker-selfoss. That repo builds on `toniher/nginx-php:nginx-1.27-php-8.2`, downloads a prebuilt selfoss zip from cloudsmith, adds `nginx-default.conf`, `supervisord.conf` (php-fpm + nginx) and `maxexectime.ini`, exposes `-p 10025:80`, and mounts `config.ini` and `data/`. The same rule applies as for the MCP server: add only new paths.

### `docker/Dockerfile`: build from this checkout, not from the cloudsmith zip
Implemented and verified (built both images, ran the full stack, drove a real
MCP client end to end — see "Verification" below).
- Stage `client`: `node:22`, `npm ci --include=dev --prefix client/`, then `npm run --prefix client/ build`. This produces `public/`.
- Stage `vendor`: `composer:2`, `composer install --no-dev --optimize-autoloader --ignore-platform-reqs`.
- Final stage: `FROM toniher/nginx-php:nginx-1.27-php-8.2` with the same apt packages (`php8.2-sqlite3`, `php8.2-mysql`). Copy the runtime files (`index.php`, `run.php`, `cliupdate.php`, `src/`, `.htaccess`) plus `public/` and `vendor/` from the build stages. Keep `VOLUME /var/www/htdocs/data`, owned by www-data, and keep the supervisord CMD.
- Write `maxexectime.ini` inline with `RUN printf … > /etc/php/8.2/fpm/conf.d/maxexectime.ini`. The repo's `.gitignore` ignores `*.ini`, so a separate file would be silently left untracked.
- Why build from source: the image always matches the fork's HEAD, and there is no `SELFOSS_VERSION` pin to bump by hand.
- **Env vars need three fixes to actually reach the app, found by testing against a real container, not just reading the code:**
  - `src/common.php` reads config from `$_ENV`, which stays empty unless `variables_order` includes `E`. The base image ships `"GPCS"` (no `E`), so every `SELFOSS_*` override — including `SELFOSS_CONFIG_DIR`/`_PATH` — was silently ignored. Fixed with `sed` on both `/etc/php/8.2/cli/php.ini` and `.../fpm/php.ini`, matching the `-d variables_order=EGPCS` the existing integration harness (`tests/integration/helpers/selfoss_server.py`) already uses for the same reason.
  - php-fpm's pool config defaults to `clear_env = yes`, which also drops env vars for the worker regardless of `variables_order`. Set `clear_env = no` in `www.conf`.
  - `logger_destination` must be the literal string `error_log` or `file:<path>` (`src/common.php` validates this); `php://stderr` is rejected with a 500. Combined with `catch_workers_output = yes` (php-fpm otherwise discards worker stdout/stderr) and php-fpm's own `error_log` pointed at `/proc/self/fd/2`, `SELFOSS_LOGGER_DESTINATION=error_log` (set as the image's `ENV` default) makes `docker logs` show application errors without needing a writable `data/logs`.
- `docker/entrypoint.sh` runs before supervisord: selfoss never creates `data/{cache,sqlite,favicons,thumbnails}` itself, and a freshly mounted `data/` volume is empty, so the entrypoint `mkdir -p`s them and `chown`s to `www-data` on every start.

### Security fix carried into `docker/nginx.conf`
Selfoss skips auth for `REMOTE_ADDR` 127.0.0.1/::1 (`src/helpers/Authentication/AuthenticationFactory.php`). docker-selfoss sets `fastcgi_param REMOTE_ADDR $http_x_real_ip`, so anyone who reaches port 10025 directly can send `X-Real-IP: 127.0.0.1` and bypass login. Delete that line and do **not** use the realip module instead: any trusted range has to include the Docker gateway, which is where every local host process connects from, so a local user could still spoof loopback. REMOTE_ADDR stays as the real TCP peer, which is never loopback inside the container. The host proxy logs the real client IPs. The deny rule also covers `src/`, `vendor/` and `data/cache`, so their PHP files are never executed directly. In compose, publish the port as `127.0.0.1:10025:80`.

### `docker/compose.yaml`
```yaml
# Put SELFOSS_USERNAME, SELFOSS_PASSWORD and SELFOSS_MCP_TOKEN in docker/.env, then
#   docker compose -f docker/compose.yaml up -d --build
services:
  selfoss:
    build: { context: .., dockerfile: docker/Dockerfile }
    image: ${SELFOSS_IMAGE:-selfoss:local}
    restart: unless-stopped
    volumes:
      - ${SELFOSS_CONFIG:-./config.ini}:/var/www/htdocs/config.ini:ro
      - ${SELFOSS_DATA:-./data}:/var/www/htdocs/data
    ports:
      - 127.0.0.1:10025:80

  mcp:
    build: ../mcp
    image: ${SELFOSS_MCP_IMAGE:-selfoss-mcp:local}
    restart: unless-stopped
    depends_on: [selfoss]
    environment:
      SELFOSS_URL: http://selfoss
      SELFOSS_USERNAME: ${SELFOSS_USERNAME:?set in docker/.env}
      SELFOSS_PASSWORD: ${SELFOSS_PASSWORD:?set in docker/.env}
      SELFOSS_MCP_TOKEN: ${SELFOSS_MCP_TOKEN:?set in docker/.env}
    ports:
      - 127.0.0.1:8765:8765
```
- Secrets go in `docker/.env`. The `.gitignore` already ignores `.env`, so it is never committed. `:?` makes compose fail fast if a secret is missing.
- `SELFOSS_CONFIG` / `SELFOSS_DATA` point at existing host paths (e.g. `/var/www/rsscau/conf/config.docker.ini`, `/var/www/rsscau/data`), so the file is never edited per host.
- Both ports bind to `127.0.0.1`, which closes the X-Real-IP spoof. The current live `10025:80` binds to all interfaces.
- The default compose network replaces the external `selfoss` network. The MCP server reaches `http://selfoss` from a container IP, so real auth is exercised.
- Feed updates: a host cron runs `docker compose -f docker/compose.yaml exec selfoss php /var/www/htdocs/cliupdate.php`, as in docker-selfoss. Skipped: an in-container cron; add it if needed.

### `docker/nginx-proxy.conf` (generic host reverse proxy; replace `rss.example.org` and the paths)
This is based on the live `rss.cau.cat` config, with `/mcp` added.
```nginx
upstream selfoss     { server 127.0.0.1:10025; }
upstream selfoss_mcp { server 127.0.0.1:8765; }

map $http_user_agent $bad_bot {
    default 0;
    ~*(Amazonbot|anthropic-ai|Applebot|AwarioRssBot|AwarioSmartBot|AwarioBot|Baiduspider|Bytespider|CCBot|ChatGPT|Claude|ClaudeBot|cohere-ai|DataForSeoBot|Diffbot|FacebookBot|Google-Extended|GPTBot|ImagesiftBot|magpie-crawler|omgili|peer39_crawler|PerplexityBot|SemrushBot|YouBot|Yandex) 1;
}
# Empty key = request not limited; only bad bots are throttled, per IP.
map $bad_bot $bot_limit_key {
    default "";
    1       $binary_remote_addr;
}
# Needs the http {} context, e.g. /etc/nginx/conf.d/bad-bots-ratelimit.conf:
#   limit_req_zone $bot_limit_key zone=bad_bots_rss:10m rate=10r/m;

server {
    listen 80;
    server_name rss.example.org;

    location /.well-known/acme-challenge {
        default_type text/plain;
        root /var/www/letsencrypt;
    }
    location / {
        return 301 https://$server_name$request_uri;
    }
}

server {
    # The combined form is deprecated since nginx 1.25.1 in favor of a
    # separate "http2 on;" directive, but distro-packaged nginx (Ubuntu,
    # Debian stable) is commonly older than that, and only the combined
    # form works there; confirmed with `nginx -t` on a 1.24 build, which
    # rejects "http2 on;" as an unknown directive. Split it once your
    # nginx is 1.25.1+.
    listen 443 ssl http2;
    server_name rss.example.org;

    ssl_certificate     /etc/letsencrypt/live/rss.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/rss.example.org/privkey.pem;
    # No OCSP stapling: Let's Encrypt dropped OCSP in 2025.
    add_header Strict-Transport-Security "max-age=31536000; includeSubdomains";

    access_log /var/log/nginx/selfoss.access.log;
    error_log  /var/log/nginx/selfoss.error.log;

    client_max_body_size 100M;
    proxy_connect_timeout 600;
    proxy_send_timeout    600;
    proxy_read_timeout    600;
    send_timeout          600;
    large_client_header_buffers 4 16k;

    # Always overwrite X-Real-IP so clients can't inject their own.
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_redirect off;

    location / {
        limit_req zone=bad_bots_rss burst=5;
        limit_req_status 429;
        proxy_pass http://selfoss;
    }

    # MCP Streamable HTTP: Bearer token checked by the server. No bot limit,
    # because the UA regex above matches Claude clients. SSE needs no buffering.
    location /mcp {
        proxy_pass http://selfoss_mcp;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 1h;
    }
}
```
- The headers are set inline instead of with `include proxy_params`, which only exists on Debian/Ubuntu.
- The MCP README links to this file instead of carrying its own nginx snippet.
- Verified with `nginx -t` against a config skeleton providing the `limit_req_zone` line and a self-signed cert.

### CI (`.github/workflows/docker.yaml`, separate from upstream's `main.yaml`)
Build both images on changes to `docker/**`, `mcp/**`, `client/**`, `composer.lock` or `src/**`, which catches upstream changes that break the build. Push to a registry only on tags or manual dispatch, with registry secrets; it is not in the default path.

## Keeping up with upstream
- The fork adds only new paths (`mcp/`, `docker/`, `.github/workflows/mcp.yaml`, `.github/workflows/docker.yaml`, and the already-created `CLAUDE.md`), so a rebase on upstream is conflict-free.
- The server depends only on the documented API, and the apiversion guard catches major bumps.
- After each rebase: `git diff <old>..<new> -- docs/api-description.json index.php`, then run the e2e tests.
- Docker risk: upstream could rename runtime files or change the PHP or node version. The Dockerfile's explicit COPY list and the CI build catch this. After each rebase, check `composer.json` `require.php` and the node version (`client/package.json` engines / `flake.nix`).
- Once the fork image exists, docker-selfoss can be archived, or it can keep building upstream releases.

## Verification
Steps 5, 6, 7, 8 and 9 have been run for real (not just planned) against this
checkout; findings are folded into the sections above (the cookie-domain fix
in `client.py`, and the `variables_order`/`clear_env`/`catch_workers_output`/
`error_log`/`entrypoint.sh` fixes in `docker/Dockerfile`).

1. Start selfoss locally: `npm run install-dependencies && npm run build && php -S 127.0.0.1:8000 run.php`, with a `config.ini` that sets `username` and a hashed `password` so auth is actually exercised. Note that requests from localhost are trusted anyway. To test real auth, point at a non-local instance or rely on the e2e harness.
2. `cd mcp && uv run selfoss-mcp` together with `npx @modelcontextprotocol/inspector`: call each tool (add an RSS source, `refresh_source`, `list_items(type="unread")`, `mark_read`, `star`, `list_items(type="starred")`, `update_source` tags, `list_items(tag=...)`, `set_tag_color`, `delete_source`).
3. Register it in Claude Code with `claude mcp add selfoss -e SELFOSS_URL=... -- uv run --directory mcp selfoss-mcp` and try natural prompts.
4. HTTP mode: start with `--transport http`. Check that a request without a token gets 401, then connect with the token.
5. **Done.** `mcp/tests/test_e2e.py` reuses `tests/integration/helpers` (`SelfossIntegration` spins up selfoss plus a feed data server, as in `tests/integration/run.py`). It calls the tool functions directly: add the fibonacci feed, update, list, mark, star, tag. Run with `SELFOSS_TEST_STORAGE_BACKEND=sqlite python -m pytest mcp/tests` — passes.
6. **Done.** `docker build -f docker/Dockerfile -t selfoss:local .`, ran standalone with a config.ini/data bind mount: home page and login both work; `/items` correctly 403s when logged out.
7. **Done.** Spoof check: with credentials set, sending `X-Real-IP: 127.0.0.1` to `/items` still returns 403 (REMOTE_ADDR is never taken from headers). `/vendor/autoload.php`, `/src/common.php` and `/config.ini` return 403, and the mcp container runs as `nobody`.
8. **Done**, via `docker compose -f docker/compose.yaml up --build` plus a real `mcp.client.streamable_http` session (not just the inspector): without a token `/mcp` returns 401; with the Bearer token, `list_tools`, `get_stats`, `add_source`, `refresh_source`, `list_items`, `mark_read`, `star`, `update_source` (tags), `set_tag_color`, `list_tags` and `delete_source` all round-trip correctly against the `selfoss` service by its compose hostname.
9. **Done.** `docker compose -f docker/compose.yaml exec selfoss php cliupdate.php` fetches feeds (also exercised indirectly via `refresh_source`).
10. Through the proxy (`nginx -t` first): a request to `/mcp` without a token → 401; with `Authorization: Bearer …` it reaches the server; `/` serves selfoss. Config syntax checked standalone with `nginx -t` (self-signed cert, a `limit_req_zone` stub in the `http {}` context); not yet run against a live TLS host.
