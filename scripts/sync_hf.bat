@echo off
REM ============================================================
REM Sync the latest GitHub `main` to the HuggingFace Space mirror.
REM
REM Usage: double-click this file, OR from any terminal run:
REM    "D:\AI WOrk\PRD Stress Test Agent\scripts\sync_hf.bat"
REM
REM What it does:
REM   1. cd to the local HF-Space clone
REM   2. fetch latest from GitHub remote (named `github` in that clone)
REM   3. reset HF clone hard to GitHub state
REM   4. swap README.md <-> README_HF.md so HF's frontmatter README wins
REM   5. commit the swap and force-push to HF Space
REM
REM Setup-once requirement: the HF-Space clone at HF_DIR must already
REM have `github` as a remote pointing at the GitHub repo:
REM    git remote add github https://github.com/Uper56/PRD-Stress-Test-Agent
REM ============================================================

setlocal EnableDelayedExpansion

REM Where the HF Space clone lives. Override by setting HF_DIR=...
REM in your environment before running the script.
if "%HF_DIR%"=="" set HF_DIR=D:\Code\hf-space

if not exist "%HF_DIR%\.git" (
  echo [error] HF Space clone not found at "%HF_DIR%"
  echo Expected a clone of:
  echo   https://huggingface.co/spaces/DogTornado/PRD-Stress-Test
  echo See docs\deployment.md for the one-time setup.
  pause
  exit /b 1
)

cd /d "%HF_DIR%"

echo === [1/5] Fetching latest from GitHub ============================
git fetch github main
if errorlevel 1 (
  echo [error] git fetch failed - is the `github` remote configured?
  pause
  exit /b 1
)

echo === [2/5] Resetting HF clone to match GitHub main ================
git reset --hard github/main
if errorlevel 1 (
  echo [error] git reset failed
  pause
  exit /b 1
)

echo === [3/5] Swapping README files (HF needs frontmatter on top) ====
if exist README.md (
  move /Y README.md README_GH.md >nul
)
if exist README_HF.md (
  move /Y README_HF.md README.md >nul
) else (
  echo [warn] README_HF.md missing - HF Space build may fail without frontmatter.
)

echo === [4/5] Committing README swap =================================
git add README.md README_GH.md
git commit -m "Use HF frontmatter README" --allow-empty
if errorlevel 1 (
  echo [info] nothing to commit ^(README swap already in tree^)
)

echo === [5/5] Force-pushing to HF Space ==============================
git push origin main --force
if errorlevel 1 (
  echo [error] git push failed - check your HF access token.
  echo Get one at https://huggingface.co/settings/tokens ^(scope: write^)
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  Sync complete.
echo  Build log: https://huggingface.co/spaces/DogTornado/PRD-Stress-Test
echo  Wait ~3-5 minutes then refresh the Space page.
echo ============================================================
echo.
pause
endlocal
