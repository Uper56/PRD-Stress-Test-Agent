# HuggingFace Space deployment — 10 steps

This guide walks you through deploying the demo to a public HuggingFace
Space. We use **approach A**: the HF Space is its own git remote, and you
push to it from your local clone whenever you want to refresh the demo.
This keeps GitHub as the source of truth (with tags / branches / CI / etc.)
and HF as a deployment target.

> **Why not GitHub Actions auto-sync?** Approach B (a workflow that
> mirrors `main` to HF on every push) is documented at the bottom — it
> trades complexity for automation and is worth doing once the demo
> is stable enough that you don't want to babysit it.

---

## Step 1 — Sign in to HuggingFace

Open https://huggingface.co and sign in (or create an account — free).

## Step 2 — Create a new Space

- Click your avatar (top right) → **New Space**.
- **Owner**: your username (or an org you control).
- **Space name**: `prd-stress-test` (or whatever — it appears in the URL).
- **License**: MIT (matches this repo).
- **Select the Space SDK**: **Streamlit**.
- **Space hardware**: free CPU basic is fine; the heavy work is OpenAI
  API calls, not local compute.
- **Public** or **Private** — public if you want a recruiter to click.
- Click **Create Space**.

You land on the empty Space page with a "Files" tab. Note the clone URL
shown in the README — looks like
`https://huggingface.co/spaces/<YOUR-USERNAME>/prd-stress-test`.

## Step 3 — Add the OpenAI key as a Space Secret

This is the **only** way to get the key onto the Space without putting
it in source control. Don't push the `.env` file.

- On the Space page, click **Settings** (tab at top).
- Scroll to **Variables and secrets** → **New secret**.
- Name: `OPENAI_API_KEY`
- Value: `sk-...` (your school key)
- Click **Save**.

Optionally also set:
- `LLM_PROVIDER` → `openai`
- `OPENAI_CRITIC_MODEL` → `gpt-4o-mini` (default if unset)
- `OPENAI_SUPERVISOR_MODEL` → `gpt-4o-mini` (set explicitly if you want
  to override the default `gpt-4o` to save money on the demo)
- `RATE_LIMIT_GLOBAL_PER_DAY` → `50` (or lower if you're nervous)
- `RATE_LIMIT_PER_IP_PER_HOUR` → `5`

## Step 4 — Clone the HF Space repo locally

```bash
cd ~/some/work/folder
git clone https://huggingface.co/spaces/<YOUR-USERNAME>/prd-stress-test hf-space
cd hf-space
```

You'll be asked for your HF username + an access token (NOT your password).
Get the token at https://huggingface.co/settings/tokens (scope: write).

## Step 5 — Add the project repo as a second remote, then sync

```bash
# In the hf-space clone:
git remote add github https://github.com/Uper56/PRD-Stress-Test-Agent
git fetch github main
git reset --hard github/main
```

This points the HF clone's working tree at exactly your GitHub `main`
commit. `git remote -v` should show two remotes — `origin` (HF) and
`github`.

## Step 6 — Promote `README_HF.md` to the HF README

HF Space requires the README at root to have the YAML frontmatter
(title / emoji / sdk / app_file). We keep that in `README_HF.md` so it
doesn't fight the GitHub README. On the HF clone only:

```bash
# Still inside hf-space/:
mv README.md README_GH.md
mv README_HF.md README.md
git add README.md README_GH.md
git commit -m "Use HF frontmatter README on the Space remote"
```

This swap only exists on the HF Space — GitHub keeps its `README.md`
untouched.

## Step 7 — Push to HF

```bash
git push origin main
```

If you see `remote: ... password authentication is not supported`, you
need an access token instead of your password — Step 4.

## Step 8 — Watch the build

Back in the HF Space page, click **App** (tab at top). You'll see build
logs streaming: `Installing dependencies → Starting application`. First
build takes ~5–10 minutes (largely pip-installing `streamlit`,
`langgraph`, `openai`, `mcp`).

If the build fails:
- Most common cause: a Python dependency mismatch. Pin the offending
  package in `requirements.txt` on the GitHub side, then redo Step 5–7.
- Second most common: missing `OPENAI_API_KEY` secret → the app will
  load but show a `RuntimeError` at the first Run click. Add the secret
  (Step 3) and the running Space picks it up without a rebuild.

## Step 9 — Smoke test the deployed Space

- Top of the page should show: title, subtitle, the yellow demo banner
  with the remaining-quota numbers.
- Pick `prd_001_ai_support_widget.md` → click **开始评审**.
- Watch the 4 critic tabs populate, then the cross-challenge section,
  then the supervisor verdict streams in.
- Click ✓ Useful / ✗ Not useful — confirm the banner doesn't change
  (those don't burn quota).
- Open `📊 消融实验` tab — confirm the headline numbers + bar charts
  render from the baked-in `latest.json` if you committed one, OR show
  the "尚无消融报告" message.

## Step 10 — Update the GitHub README with the live link

The GitHub README has a `[TBD]` placeholder under **Quick demo**. Edit
it on the GitHub side:

```markdown
🌐 **Live demo**: https://huggingface.co/spaces/<YOUR-USERNAME>/prd-stress-test
```

Then `git push origin main` from the GitHub clone. The HF Space doesn't
need rebuilding for this — it's only the GitHub README that changes.

---

## Approach B — GitHub Action auto-sync (optional, for later)

Once the demo is stable, you can automate `main` → HF Space mirroring
so a `git push origin main` to GitHub triggers an HF rebuild without
your involvement. Sketch:

1. Create a Personal Access Token on HF (scope: write).
2. Add it as a GitHub Actions secret named `HF_TOKEN`.
3. Add `.github/workflows/sync-hf.yml`:

```yaml
name: Sync to HuggingFace Space
on:
  push:
    branches: [main]
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - name: Push to HF
        env: { HF_TOKEN: ${{ secrets.HF_TOKEN }} }
        run: |
          git config user.email "actions@github.com"
          git config user.name "GitHub Actions"
          # Use README_HF.md as the HF README (frontmatter version).
          cp README.md README_GH.md
          cp README_HF.md README.md
          git add README.md README_GH.md
          git commit -m "HF README swap" || true
          git push --force \
            https://$HF_TOKEN@huggingface.co/spaces/<YOUR-USERNAME>/prd-stress-test \
            main
```

The `--force` is OK because the HF Space is a downstream-only mirror.

I'd recommend doing Approach A first to confirm the build works, then
switching to B once you trust it.

---

## Things to NOT push to HF

The `.gitignore` already protects:

- `.env` (your API key)
- `data/results/` (run history, ablation reports, daily_count.json)

If you add anything else with secrets or personal data, extend
`.gitignore` BEFORE the next push.
