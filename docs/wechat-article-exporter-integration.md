# WeChat Article Exporter Integration

## Why this project fits

`wechat-article-exporter` is built around the same workflow we need here: discover Official Account articles, cache article metadata, and export content as `html`, `json`, `excel`, `txt`, `md`, `docx`, or `pdf`. Its README calls out HTML fidelity and an open API surface, plus Docker and Cloudflare deployment options, so this project can point at the hosted service or a private deployment without carrying the whole Nuxt app inside this Python/Vue monitor.

## Relevant upstream surfaces

- Public auth check: `GET /api/public/v1/authkey`
- Account lookup by article URL: `GET /api/public/v1/accountbyurl?url=...`
- Article list by account: `GET /api/public/v1/article?fakeid=...&begin=...&size=...`
- Single article export: `GET /api/public/v1/download?url=...&format=html|markdown|text|json`

The account and article list endpoints require an exporter `X-Auth-Key`, which represents a logged-in exporter session. Direct single-article export is less stateful upstream, but this integration keeps the AuthKey configurable because collection normally starts from an account history, not one URL.

## Integration choice

This repository remains Python-first on the backend and already has a standard-library HTTP server. Instead of adding Nuxt, Deno, or browser-side exporter dependencies, the integration uses a small Python client in `monitor/wechat_collector.py`:

- no new runtime dependency
- configurable exporter base URL
- encrypted/masked AuthKey at rest and in API responses
- background task model aligned with the existing batch-download UI
- local export files under `wechat_collection_output_dir`

## Operational notes

- Default hosted base URL: `https://down.mptext.top`
- Default output directory: `data/wechat-articles`
- Default format: `markdown`
- Collection throttles article downloads with a configurable per-article delay.
- Output paths are constrained under `wechat_collection_output_dir`.
- The task manager is currently in-memory; restarting the monitor server drops task history but leaves exported files intact.

## Follow-up candidates

- Persist collection tasks in SQLite if long-running collection history matters.
- Add a one-click AuthKey acquisition flow only if we decide to embed exporter login behavior.
- Add import from collected Markdown into the existing AI article / WeChat publish pipeline.
