# Legacy crawler replacement

The experimental scripts that used guessed game IDs, sorted pitches out of
source order, or parsed only relay type 13 were removed.

Use the package CLI from the repository root:

```powershell
python -m kbo_crawler init
python -m kbo_crawler sync
python -m kbo_crawler period --from-date 2025-03-01 --to-date 2025-11-30
python -m kbo_crawler fetch-game 20260506HHHT02026 --date 2026-05-06
python -m kbo_crawler coverage
python -m kbo_crawler export data/exports/game.csv --game-id 20260506HHHT02026
```

The implementation now lives under `src/kbo_crawler/`; raw responses and
normalized SQLite rows are both retained.
