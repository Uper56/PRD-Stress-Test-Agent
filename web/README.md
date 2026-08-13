# PIXEL·PRD — web frontend

React 19 + Vite + TypeScript SPA for the PRD Stress Test agent. Self-built 8-bit
design system ("Pixel Studio" direction) — see
`docs/superpowers/specs/2026-08-13-frontend-redesign-design.md` for the full spec.

## Dev

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api → localhost:8000
```

Run the API alongside: `uvicorn api.app:app --reload` from the repo root.

## Structure

```
src/
  styles/        fonts.css (self-hosted woff2) · tokens.css (8-bit design tokens) · base.css
  lib/           api.ts (typed client) · useSSE.ts (SSE hook + parser) · types.ts
  components/    13-piece pixel component library
  pages/         ReviewPage (workspace) · SkillsPage · AblationPage
```

## Test

```bash
npm test          # vitest — SSE parser edge cases
```

## Build

```bash
npm run build     # → dist/, served by api/app.py in production (single origin)
```

## Fonts

Pixelify Sans + Inter (latin, variable) and Zpix 最像素 (CJK subset) are vendored
in `public/fonts/` — no CDN dependency, works in mainland China. Latin glyphs
render in the pixel display font; Chinese falls through to Zpix in display
contexts and to the system font in body text (reading comfort).
