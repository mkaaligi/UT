# VI Snapshots & VI Browser

## Overview

VI Snapshots is an automated snapshot gallery system that renders all LabVIEW VIs in your repository to HTML on each commit. The **VI Browser** viewer provides navigation and detailed inspection of front panel and block diagram imagery.

This is a **completely self-contained, dependency-free system** with no external repository calls.

## How It Works

### 1. VI Snapshots Workflow (`vi-snapshots.yml`)

Triggered automatically on:
- Push to files matching `**.vi`, `**.ctl`, `**.lvproj`, `**.lvlib`, `**.lvclass` (excluding `.github/**`)
- Manual dispatch via `workflow_dispatch`

**What it does:**
- Detects changed commits in the push
- For each commit, finds all changed VIs
- Content-addresses VIs by git blob SHA (skips already-rendered unchanged VIs)
- Renders via LabVIEW inside the stock NI Windows container: `nationalinstruments/labview:latest-windows`
- Generates per-commit `manifest.json` (VI name → HTML path mapping)
- Publishes rolling `commits.json` (most recent 200 commits)
- Uploads `vi-snapshots/` artifact to GitHub Actions
- Stores rendered HTML in content-addressed structure: `by-blob/<blob[:2]>/<blob>.html`

**Key features:**
- **Incremental rendering**: Only new/changed blobs render; unchanged VIs reuse cached HTML
- **No git history pollution**: All renders stored in single flat `by-blob/` directory
- **Accessible**: Renders deploy to GitHub Pages at `/vi-snapshots/`

### 2. VI Browser 1.0 (Flat Gallery View)

Deployed to GitHub Pages at `https://<user>.github.io/<repo>/vi-snapshots/`

**Features:**
- Tree-based navigation (mirrors source folder hierarchy)
- Revision selector dropdown (newest first; limited to last 200 commits)
- Full-text search by VI name or path
- Dual-pane viewer:
  - Front panel image in left iframe
  - Block diagram image in right iframe
  - Side-by-side comparison or sequential viewing

**Implementation:** `vi-browser.html` (single self-contained file; reads `commits.json` + per-commit `manifest.json`)

### 3. VI Browser 2.0 (Position-Aware In-Place Renderer) — Optional

*Requires additional workflows; adds significant infrastructure.*

When enabled via configuration, the `vi-snapshots-json-windows.yml` and `vi-snapshots-json.yml` workflows generate **position-aware frames JSON**. This enables in-place block diagram navigation:

- **Windows workflow** (`vi-snapshots-json-windows.yml`):
  - Runs after each snapshot build (auto-trigger via `workflow_run`)
  - Builds Go render engine (lvctl.exe) inside Windows container
  - Renders to `<blob>.windows.json`
  - Skips unchanged VIs (reuses cached `.windows.json`)
  - Gated by VI Browser config (`positionAware: windows`)

- **Linux workflow** (`vi-snapshots-json.yml`):
  - Alternative platform (experimental)
  - Builds custom Linux image with VI Server transport
  - Renders to `<blob>.json`
  - Gated by VI Browser config (`positionAware: linux`)

**Features (when enabled):**
- Diagram navigation in-place (pan/zoom/structure traversal)
- Case/Event structure jumping
- Keyboard shortcuts for fast navigation
- Fallback to 1.0 flat view if 2.0 not available

---

## File Structure

```
.github/
├── workflows/
│   ├── vi-snapshots.yml                    # Primary workflow: renders 1.0 HTML
│   ├── vi-snapshots-json-windows.yml       # Optional: 2.0 Windows frames (auto-trigger)
│   └── vi-snapshots-json.yml               # Optional: 2.0 Linux frames (auto-trigger)
│
├── actions/
│   └── snapshots/
│       ├── action.yml                      # Composite action wrapper
│       ├── build-snapshots.ps1             # Orchestrates rendering (per-commit)
│       ├── render-snapshots.ps1            # Calls LabVIEW HTML render (per-VI)
│       ├── build-gallery.py                # Generates manifest.json + commits.json
│       ├── vi-browser.html                 # Gallery viewer (1.0 flat view)
│       ├── vi-interactive.html             # Single-VI viewer (optional 2.0)
│       └── vi-render.js                    # In-place block diagram renderer (2.0)
│
├── labview/                                # Infrastructure for 2.0 rendering
│   ├── toimages/                           # Go render engine + LabVIEW toolkit
│   ├── build-json-worklist.sh              # Content-addressed worklist builder
│   ├── wait-for-worker-image.sh            # Container readiness
│   ├── ensure-docker.ps1                   # Docker availability check
│   ├── windows-render.ps1                  # Windows COM/ActiveX render script
│   └── [other support files]
│
├── pages/
│   └── vi-snapshots.md                     # This documentation
│
└── labview-ci.yml                          # VI Browser configuration
```

---

## Configuration

Edit `.github/labview-ci.yml` to control VI Browser behavior:

```yaml
config:
  labviewVersion: "2026"
  os: [windows, linux]
  activities:
    - snapshots            # Enable 1.0 rendering
    - snapshots-2          # Enable 2.0 frame generation
  viBrowser:
    positionAware: windows # or "linux" or "windows+linux" for both
```

**Position-aware modes:**
- `windows` (default): Generate `.windows.json` for in-place navigation
- `linux`: Generate `.json` for alternative platform
- `windows+linux`: Generate both (separate workflows, coexist side-by-side)
- Omit or leave unset: Only 1.0 rendering (flat gallery)

---

## Workflow Triggers & Outputs

### VI Snapshots (1.0)

| Trigger | Condition |
|---------|-----------|
| Push | Files matching `**.vi`, `**.ctl`, `**.lvproj`, `**.lvlib`, `**.lvclass` (exclude `.github/**`) |
| Manual | `workflow_dispatch` |

**Artifact:** `vi-snapshots` (compressed)  
**Deployment:** GitHub Pages to `/vi-snapshots/`  
**GitHub Page:** `https://<user>.github.io/<repo>/vi-snapshots/`

### VI Browser 2.0 — Windows (`vi-snapshots-json-windows.yml`)

| Trigger | Condition |
|---------|-----------|
| Auto | `workflow_run` on "VI Snapshots and VI Browser" success (if config enables) |
| Manual | `workflow_dispatch` with optional `--vi <path>` for smoke test |

**Parameters (manual dispatch):**
- `vi`: Single VI path for smoke test (default: all)
- `target_sha`: Commit SHA to render (default: current HEAD)
- `force`: Re-render even if cached (default: false)
- `render_timeout`: Per-VI render timeout, Go duration format (default: 5m)

**Artifact:** `json-blobs.windows` (compressed frames)  
**Output:** `.windows.json` files published to `/vi-snapshots/by-blob/`

### VI Browser 2.0 — Linux (`vi-snapshots-json.yml`)

Same structure as Windows; outputs `.json` files (no `.windows` suffix).

---

## GitHub Pages Deployment

Deployed via `.github/workflows/deploy-pages.yml`, which:
1. Listens for either "VI Snapshots and VI Browser" or "VIDiff Report" completion
2. Downloads artifacts from GitHub Actions
3. Publishes to `gh-pages` branch
4. Updates GitHub Pages site

**Result:** Gallery live at `https://<user>.github.io/<repo>/vi-snapshots/`

---

## Important Notes

### 1. Content Addressing

All renders are stored by **git blob SHA**:
- Path: `vi-snapshots/by-blob/<blob[:2]>/<blob>.html`
- Unchanged files (same SHA) reuse existing renders
- Massive speed boost for large repos after first run

### 2. Incremental Rendering

The workflows use content-addressed worklists to skip already-rendered VIs:
- 1.0 workflow skips VIs with existing `<blob>.html`
- 2.0 Windows workflow skips VIs with existing `<blob>.windows.json`
- 2.0 Linux workflow skips VIs with existing `<blob>.json`

### 3. No External Dependencies

All files are **locally present**:
- Workflows call `./.github/actions/snapshots` (local composite action)
- Render engine is built from local Go source (`.github/labview/toimages/`)
- No external API calls or dependency on other repositories
- Works in **completely private repos** with no public git integrations

### 4. Container Images

- **Windows rendering:** Stock NI LabVIEW image (`nationalinstruments/labview:latest-windows`)
- **Linux rendering (2.0):** Custom image built from Dockerfile in `.github/labview/`
- Both use the **exact same render engine** (Go `lvctl`), only transport differs

---

## Troubleshooting

### VI Browser shows "No Windows VI Browser 2.0 render yet"

**Cause:** 2.0 workflows are available but haven't run yet.  
**Fix:** The `vi-snapshots-json-windows.yml` workflow auto-triggers after the next VI Snapshots run. Or manually dispatch it:
```
gh workflow run vi-snapshots-json-windows.yml
```

### Renders are slow on first run

**Expected:** The worker container image may take 20–60 minutes to build/pull on first run.  
**Normal:** Subsequent runs are much faster (seconds to minutes) because the image is cached.

### Some VIs fail to render

**Expected:** Large, complex VIs or those with unsupported features may timeout.  
**Workaround:** Increase `render_timeout` in manual dispatch (default: `5m`).

### Deployment to GitHub Pages fails

**Check:**
1. Repository settings: Ensure GitHub Pages is enabled and set to `gh-pages` branch
2. Permissions: The GITHUB_TOKEN must have `contents: write` permissions
3. `.github/workflows/deploy-pages.yml` exists and is active

---

## Reference

- **Workflows:**
  - `.github/workflows/vi-snapshots.yml` — Main snapshot build
  - `.github/workflows/vi-snapshots-json-windows.yml` — 2.0 Windows frames
  - `.github/workflows/vi-snapshots-json.yml` — 2.0 Linux frames
  - `.github/workflows/deploy-pages.yml` — Artifact deployment

- **Actions:**
  - `.github/actions/snapshots/` — Composite action (snapshots orchestration)

- **Configuration:**
  - `.github/labview-ci.yml` — VI Browser + container settings

- **Live Gallery:**
  - `https://<user>.github.io/<repo>/vi-snapshots/`
