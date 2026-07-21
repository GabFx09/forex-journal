# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A self-contained financial journaling suite with three standalone HTML applications (no build step, no server required). Each app uses **localStorage** as primary storage with optional **Google Sheets** sync via Apps Script.

- `files-forex/ForexJournal_GoogleSheets.html` — Forex trading journal
- `files-finance/FinanceJournal_Pro.html` — Personal finance & budgeting
- `files stock/StockJournal_Pro.html` — Stock portfolio & dividend tracking
- Companion `.gs` files — Google Apps Script backend (deploy as Web App)

## Running / Testing

Open any `.html` file directly in a browser — no build or install needed.

For Google Sheets sync: paste the matching `.gs` script into Apps Script, deploy as Web App (Execute as: Me, Access: Anyone), copy the `/exec` URL into the app's Settings modal.

## Architecture

**Frontend pattern (identical across all three apps):**
- Single-file HTML: CSS → HTML markup → `<script>` block
- State lives in `localStorage` (`fj_*`, `fj2_*`, `sj_*` key namespaces)
- `renderAll()` rebuilds every section from state on each data change
- Charts use Chart.js 4.4.1 (CDN); chart instances stored in module-level vars and `.destroy()`-ed before re-draw
- Tab switching via `showTab(name, btn)` — adds `on` class to both `.tab` div and `.nb` button
- Dark-theme CSS variables in `:root` — `--bg`, `--surf`, `--card`, `--gold`, `--grn`, `--red`, `--blu`, `--mut`, `--txt`, `--sub`

**Google Sheets sync pattern:**
- `gasGet(params)` → GET request with URLSearchParams
- `gasPost(body)` → POST with JSON body as `text/plain`
- `pullAll()` overwrites local state from Sheets; `pushAll()` sends all local data to Sheets
- `setSync(state, txt)` updates the sync status bar (`'ok'|'busy'|'err'`)

**ForexJournal-specific tabs:** Dashboard · Trade Log · Planning Harian · Planning Mingguan · Risk Manager · Psikologi · Rules · **Analisis**

**Analisis tab** (added): period switcher (Hari Ini / Kemarin / Mingguan), 4-metric summary row, P&L-per-pair bar chart, BUY/SELL doughnut chart, per-pair breakdown cards. Triggered by `renderAnalysis()` — called on `showTab('analisis')` and in `renderAll()`.

## Key Conventions

- All monetary values are `$` USD; P&L stored as strings, parsed with `parseFloat()`.
- Dates stored as `YYYY-MM-DD` strings; comparison uses string ordering.
- `normResult(t)` normalises trade result to `'win' | 'loss' | 'be' | 'open'`.
- Indonesian UI language throughout.
- `toast(msg, dur?)` for transient feedback (bottom-center).

## Deployment

GitHub Actions **only discovers workflow files under the repo-root `.github/workflows/`** — a workflow nested in a subdirectory (e.g. `files stock/.github/workflows/`) is invisible to Actions and will never run. All active workflows must live in `1-repo-main/.github/workflows/`.

All three apps deploy to the same `gh-pages` branch (GitHub Pages project-page root is `/forex-journal/`, not domain root), using `destination_dir` + `keep_files: true` (not `force_orphan`) so they don't wipe each other out:

- Forex: `.github/workflows/forex_digest.yml` (data digest + deploy) and `deploy_only.yml` (redeploy without digest) — deploys to branch root → `https://gabfx09.github.io/forex-journal/`
- Stock: `.github/workflows/stock_digest.yml` — deploys with `destination_dir: stock` → `https://gabfx09.github.io/forex-journal/stock/`
- Finance: `.github/workflows/finance_deploy.yml` (no digest — Finance has no external data) — deploys with `destination_dir: finance` → `https://gabfx09.github.io/forex-journal/finance/`

Each app's HTML has a small cross-nav strip (`#xnav`, right under the topbar) linking to the other two live apps.

All four deploy workflows share `concurrency: {group: gh-pages-deploy, cancel-in-progress: false}` — without it, two workflows triggered by the same push (e.g. Forex + Finance both changed in one commit) race to push to `gh-pages` at once and the second one's push gets rejected (ref moved). The shared group makes GitHub Actions queue them instead of running in parallel.
