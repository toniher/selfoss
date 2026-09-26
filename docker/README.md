# Docker

`compose.yaml` builds and runs two containers from this checkout:

| Service | Image | Host port | Contents |
|---------|-------|-----------|----------|
| `selfoss` | `docker/Dockerfile` | `127.0.0.1:10025` | nginx, php-fpm and selfoss under supervisord |
| `mcp` | `mcp/Dockerfile` | `127.0.0.1:8765` | the MCP server in HTTP mode, running as `nobody` |

Both ports bind to loopback. Put the host's own nginx in front of them with
`nginx-proxy.conf`.

## Files

- `Dockerfile`: builds the client with Node and the PHP dependencies with
  Composer, then copies both onto `toniher/nginx-php`. Build context is the
  repo root.
- `Dockerfile.dockerignore`: drops `.git`, `node_modules`, `vendor`, `data`,
  `docs`, `tests` and `mcp` from that context. BuildKit reads it because of
  its name, `<Dockerfile>.dockerignore`.
- `nginx.conf`: the vhost inside the selfoss image.
- `supervisord.conf`: starts php-fpm and nginx.
- `entrypoint.sh`: creates `data/{cache,sqlite,favicons,thumbnails}` on each
  start, since selfoss expects them and an empty volume lacks them.
- `nginx-proxy.conf`: a TLS vhost for the host nginx, serving `/` and `/mcp`.
- `compose.yaml`: the two services above.

## Setup

1. Create `docker/config.ini` with a login. selfoss reads it as plain
   `key=value` lines, without sections:

   ```ini
   username=you
   password=<hash>
   ```

   selfoss checks the password with PHP's `password_verify`, so any PHP
   generates the hash:

   ```sh
   docker run --rm php:cli php -r 'echo password_hash("your-password", PASSWORD_DEFAULT), "\n";'
   ```

   The default
   database is SQLite in `data/sqlite/`. See
   `docs/content/docs/administration/options.md` for the other options.

2. Create `docker/.env` with the same login in plain text and a token for
   MCP clients:

   ```sh
   SELFOSS_USERNAME=you
   SELFOSS_PASSWORD=plain-text-password
   SELFOSS_MCP_TOKEN=$(openssl rand -hex 32)   # paste the output, .env does not run shell
   ```

   Compose refuses to start if one of the three is missing. The root
   `.gitignore` ignores `.env` and `*.ini`, so git skips both files.

3. Start it:

   ```sh
   docker compose -f docker/compose.yaml up -d --build
   ```

4. Fetch feeds from a host cron job:

   ```sh
   docker compose -f docker/compose.yaml exec selfoss php /var/www/htdocs/cliupdate.php
   ```

### Variables

Set these in `docker/.env` to reuse existing paths or prebuilt images:

| Variable | Default | Purpose |
|----------|---------|---------|
| `SELFOSS_CONFIG` | `./config.ini` | host path mounted read-only as `config.ini` |
| `SELFOSS_DATA` | `./data` | host path mounted as `data/` |
| `SELFOSS_IMAGE` | `selfoss:local` | tag for the selfoss image |
| `SELFOSS_MCP_IMAGE` | `selfoss-mcp:local` | tag for the MCP image |

Relative paths resolve against `docker/`. If `SELFOSS_CONFIG` points at a
file that does not exist, Docker creates an empty directory there and
selfoss fails to start.

The selfoss image also honours every `SELFOSS_*` option from
`options.md` as an environment variable. It sets
`SELFOSS_LOGGER_DESTINATION=error_log`, so `docker compose logs selfoss`
shows the PHP log.

## Reverse proxy

Copy `nginx-proxy.conf` to the host, e.g. `/etc/nginx/sites-enabled/`, and
replace `rss.example.org` and the certificate paths. The rate-limit zone
belongs in the `http {}` context, so add this line to a file in
`/etc/nginx/conf.d/`:

```nginx
limit_req_zone $bot_limit_key zone=bad_bots_rss:10m rate=10r/m;
```

`/` throttles known crawler user agents. `/mcp` skips that limit because the
list matches `Claude`, and the MCP server checks the Bearer token itself.
Point MCP clients at `https://rss.example.org/mcp` with the header
`Authorization: Bearer <SELFOSS_MCP_TOKEN>`.

## Security

selfoss skips its login for requests whose `REMOTE_ADDR` is `127.0.0.1` or
`::1`. Keep these settings as they are:

- Leave the realip module out of `nginx.conf`. With it, a client could send
  `X-Real-IP: 127.0.0.1` and log in as you. Inside the container,
  `REMOTE_ADDR` is the Docker gateway, never loopback.
- Keep the `127.0.0.1:` prefix on both ports. Anyone who reaches port 8765
  can call the MCP tools with a valid token, and port 10025 bypasses the
  host proxy's TLS and rate limits.
- The MCP container logs in to `http://selfoss` over the compose network, so
  it needs the real password and cannot rely on the loopback bypass.

## CI images

`.github/workflows/docker.yaml` builds both images when a change touches
`docker/`, `mcp/`, `client/`, `src/` or `composer.lock`. On a git tag it
pushes `ghcr.io/<owner>/selfoss:<tag>` and `ghcr.io/<owner>/selfoss-mcp:<tag>`.
To run those instead of local builds, set `SELFOSS_IMAGE` and
`SELFOSS_MCP_IMAGE` and start with `up -d` without `--build`.
