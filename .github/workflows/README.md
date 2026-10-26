# DualBot Mac — Test 14: read-only MQL5 FILE_COMMON bridge

## Objective

Verify that an MQL5 Expert Advisor **running inside MetaTrader 5/Wine on a real macOS 26 Apple Silicon GitHub runner** can publish a heartbeat and read-only market-data snapshot, and that **native macOS Python can read it**, without the MetaTrader5 Windows Python IPC extension.

## What is included

- `MT5_Test_14_File_Bridge_MacOS26.yml` — single GitHub Actions workflow (contains the code needed to run the test; upload this file only).
- `DualBotReadOnlyBridge.mq5` — Expert Advisor source installed and compiled by the workflow.
- `read_bridge.py` — native Python parser for `FILE_COMMON` snapshots.
- `test_reader.py` — six offline tests of reader behavior and read-only safeguards.

The workflow installs the official macOS MT5 app, compiles the EA with MetaEditor under Wine, places the `.ex5` in relevant MQL5 data locations, then attempts to launch the terminal with `[StartUp] Expert=DualBotReadOnlyBridge`. It watches for the MQL5-generated `DUALBOT_TEST14_BRIDGE.csv` file in Wine's MetaQuotes `Terminal/Common/Files` directory. It uses existing `MT5_DEMO_*` GitHub Actions secrets only if present, never prints passwords or account numbers, and **never places a trade**.

## Expected results

1. `MQL5_EX5_COMPILED=YES` — MQL5 EA compiled successfully in MetaEditor on Apple Silicon Wine.
2. `bridge_file_seen: true` and `heartbeat_seq >= 2` — a real running MQL5 EA wrote a shared file that native Python parsed. **This is the minimum success criterion.**
3. `demo_verified: true` — terminal was connected to the disposable demo account. This is a separate result, not implied by file-bridge success.
4. `live_quotes_verified: true` — a quote was retrieved on the chart symbol while demo-connected. This is separate and may fail if the broker has no such symbol or the terminal cannot authorize.

## Limitations

- This is a **read-only transport proof**, not yet a drop-in implementation of all MT5 functions used by the five trading engines.
- The MQL5 code has no trade submission API calls and terminal auto-trading is explicitly disabled.
- A green GitHub job can prove the shared file path, but does **not** prove automatic trading, order validation, historical-data API coverage, or live compatibility of the DualBot engines.
- The compiler and actual Mac/Wine runtime **have not been exercised locally**. GitHub Test 14 will provide that evidence; if compilation or auto-attachment fails, inspect sanitized steps/logs before changing the original bot.
- Don't upload the original trading-bot ZIP or account databases to the public repository.

## Run

1. Upload `MT5_Test_14_File_Bridge_MacOS26.yml` under `.github/workflows/` in `oluwaseyisdx/xauusd-mac-test` and commit on `main`.
2. Workflow should start automatically. If not, use Actions → Test 14 → Run workflow.
3. Examine `MT5_TEST14_MQL5_FILE_BRIDGE` artifact and job log.

## Offline tests

```bash
python -m unittest -v test_reader.py
```
