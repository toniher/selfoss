# Build context is the repo root: docker compose -f docker/compose.yaml build
# (or: docker build -f docker/Dockerfile ..)
#
# Builds from this checkout instead of a pinned SELFOSS_VERSION zip (as
# https://github.com/toniher/docker-selfoss does), so the image always
# matches the fork's HEAD.

FROM node:22 AS client
WORKDIR /src
COPY client/package.json client/package-lock.json client/
RUN npm ci --include=dev --prefix client/
COPY client/ client/
COPY package.json .
RUN npm run --prefix client/ build

FROM composer:2 AS vendor
WORKDIR /src
COPY composer.json composer.lock ./
RUN composer install --no-dev --no-scripts --optimize-autoloader --ignore-platform-reqs

FROM toniher/nginx-php:nginx-1.27-php-8.2

RUN set -x; \
    apt-get update && apt-get -y upgrade && \
    apt-get install -y --no-install-recommends php8.2-sqlite3 php8.2-mysql && \
    rm -rf /var/lib/apt/lists/*

# src/common.php reads env vars from $_ENV, which stays empty unless "E" is
# in variables_order (the base image ships "GPCS", i.e. no $_ENV at all) -
# see how tests/integration/helpers/selfoss_server.py works around the same
# thing with `-d variables_order=EGPCS`. Without this, every SELFOSS_* env
# var (including SELFOSS_CONFIG_DIR/_PATH) is silently ignored.
RUN sed -i 's/variables_order = "GPCS"/variables_order = "EGPCS"/' \
    /etc/php/8.2/cli/php.ini /etc/php/8.2/fpm/php.ini

# php-fpm defaults to clearing the worker environment, which would silently
# swallow every SELFOSS_* override too. Docker is the only env-passing
# mechanism available here (no shell to export from).
# php-fpm also discards worker stdout/stderr by default, so route it (and
# php-fpm's own error_log) to the container's stdout/stderr, where `docker
# logs` and Docker's own log rotation already handle it.
RUN sed -i \
    -e 's/;clear_env = no/clear_env = no/' \
    -e 's/;catch_workers_output = yes/catch_workers_output = yes/' \
    /etc/php/8.2/fpm/pool.d/www.conf \
 && sed -i 's#^error_log = .*#error_log = /proc/self/fd/2#' /etc/php/8.2/fpm/php-fpm.conf

# .gitignore ignores *.ini, so this is written inline rather than copied.
RUN printf 'max_execution_time = 600\ndefault_socket_timeout = 600\n' > /etc/php/8.2/fpm/conf.d/maxexectime.ini

COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

WORKDIR /var/www/htdocs

# --chown instead of a later `chown -R`, which would duplicate every file
# into another layer.
COPY --chown=www-data:www-data index.php run.php cliupdate.php .htaccess ./
COPY --chown=www-data:www-data src/ src/
COPY --chown=www-data:www-data --from=vendor /src/vendor/ vendor/
COPY --chown=www-data:www-data --from=client /src/public/ public/

RUN mkdir -p /run/php && chown www-data:www-data /var/www/htdocs

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# "error_log" (not a raw stream path - see src/common.php's validation)
# routes through PHP's error_log(), which php-fpm now sends to stdout/stderr
# above, instead of requiring a writable data/logs dir.
ENV SELFOSS_LOGGER_DESTINATION=error_log

VOLUME /var/www/htdocs/data

ENTRYPOINT ["/entrypoint.sh"]
CMD ["/usr/bin/supervisord"]
