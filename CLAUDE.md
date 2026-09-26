# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

selfoss is a self-hosted RSS reader / feed aggregator: a PHP (≥ 8.2) JSON backend plus a React/TypeScript single-page client built with Parcel.

**Upstream policy:** `CONTRIBUTING.md` bans LLM-generated contributions (code, docs, issues) to the upstream fossar/selfoss project. Keep this in mind for anything intended to be sent upstream.

## Commands

Everything is driven from the root `package.json` (it delegates to `client/` npm scripts and composer scripts). `nix-shell` (or `nix-shell -A ci`) provides the full toolchain; CI runs commands through it.

- Install deps: `npm run install-dependencies` (composer + `npm ci` in `client/`)
- Build client: `npm run build` (outputs to `public/`); watch mode: `npm run dev`
- Run dev server: `php -S 127.0.0.1:8000 run.php` (`run.php` is the router for PHP's built-in server; `index.php` holds the routes)
- Run feed update from CLI: `php cliupdate.php`
- All checks (what CI enforces): `npm run check`; auto-fix formatting: `npm run fix`
- Client only: `npm run check:client` (prettier, eslint, `tsc --noEmit`, stylelint)
- Server only: `npm run check:server` → parallel-lint, php-cs-fixer (`composer cs` / `composer fix`), PHPUnit, PHPStan (`composer phpstan`)
- Rector (checked in CI): `composer rector -- --dry-run`
- PHP unit tests: `composer test`; single test file/filter:
  `vendor/bin/simple-phpunit --bootstrap tests/bootstrap.php tests/Helpers/FilterTest.php`
  `vendor/bin/simple-phpunit --bootstrap tests/bootstrap.php --filter testName tests`
- Integration tests (Python, needs `requests` and `bcrypt`): `npm run test:integration`; choose DB with `SELFOSS_TEST_STORAGE_BACKEND=sqlite|mysql|postgresql`
- Python helpers in `utils/` and `tests/` are formatted with `black` (`npm run check:helpers`).

## Architecture

### Backend (`src/`, PSR-4 namespace `Selfoss\`; spouts use namespace `spouts\`)

- **Bootstrap** — `src/common.php` loads `Configuration`, sets up Tracy error handling, and wires the Slince DI container. Services are non-shared by default; most core ones are explicitly `setShared(true)`. `index.php` then defines all routes on `Bramus\Router` and dispatches each to a controller resolved from the container.
- **Configuration** — `helpers/Configuration.php`: each typed public property is an option. Values come from `config.ini` (snake_case keys), overridable by `SELFOSS_*` env vars (prefix configurable via `env_prefix`); `SELFOSS_CONFIG_PATH` / `SELFOSS_CONFIG_DIR` choose the file. Options are documented by hand in `docs/content/docs/administration/options.md` — update it when adding options.
- **DAOs** (`daos/`) — two layers. `daos/Items|Sources|Tags.php` are thin, backend-agnostic wrappers (adding auth checks, etc.) around an `*Interface` implementation. The concrete backend is picked at runtime from `dbType`: `daos/{sqlite,mysql,pgsql}/…`. `mysql` is the base implementation; `sqlite` and `pgsql` Items/Sources/Tags/Statements extend it and override dialect-specific SQL (`Statements.php`). Schema migrations are hand-written, versioned steps in each backend's `Database.php` (`migrate()`), so a schema change must be added to all three backends.
- **Spouts** (`spouts/`) — source-type plug-ins extending `spouts\spout`, discovered by `helpers/SpoutLoader.php` scanning `src/spouts/*/*.php`. A spout's class name (e.g. `spouts\rss\feed`) is what's stored as the source type and sent by the API. Spouts declare their UI parameters via `Parameter`.
- **Update pipeline** — `helpers/ContentLoader.php` fetches each source via its spout, applies filters (`helpers/Filters/`), sanitizes HTML (htmLawed), stores thumbnails/icons (`ThumbnailStore`, `IconStore`) and inserts items; triggered by `/update`, `cliupdate.php`, or the client.
- **Controllers** (`controllers/`) mostly return JSON consumed by the client; the HTTP API is described in `docs/api-description.json` (OpenAPI).

### Client (`client/`)

- Entry `client/index.html` → `js/index.ts` → `js/selfoss-base.ts` (global app object) → React tree in `js/templates/App.tsx` (react-router).
- Server calls go through `js/requests/*` built on `js/helpers/ajax.ts`.
- Offline mode: Dexie/IndexedDB (`selfoss-db-offline.ts`, `model/OfflineDb.ts`) synced via `/items/sync` (`selfoss-db.ts`, `selfoss-db-online.ts`), plus a service worker (`selfoss-sw-offline.ts`).
- Translations are JSON in `client/locale/`; `en.json` is the source, others are maintained through Weblate.
- Keyboard shortcuts live in `js/shortcuts.ts` and are documented in `docs/content/docs/usage/shortcuts.md`.

### Other

- `docs/` is the project website (Zola), including user/admin docs.
- `NEWS.md` is the changelog; user-visible changes get an entry under the unreleased version.
- `data/` holds runtime data (SQLite DB, cache, favicons, thumbnails, logs).
