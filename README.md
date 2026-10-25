# Free real Apple Silicon Mac test — Gold support/resistance strategy

**Scope:** This ZIP contains a stand-alone historical XAU/USD simulation (October 1–23, 2026, $1,000 start, 5% risk budget per trade). It DOES NOT contain a trading bot that can connect to MT5 or send orders. Do not treat a successful backtest as proof that an MT5 bot works on a Mac.

## How to run the actual Mac test, free subject to GitHub plan/quotas

1. Create a GitHub account and new repository. This non-secret sample may be hosted **publicly** for no-cost standard GitHub-hosted runs. Do not include live account credentials or your proprietary trading bot in a public repository. A private repo may consume included Actions minutes or incur a charge if quota is exceeded.
2. Upload the **contents** of this ZIP including `.github/workflows/mac-real-apple-silicon.yml` to the root of the repository, not inside an extra folder. Be sure the hidden `.github` directory is included. Alternatively use `git add -A` and push from your own PC.
3. The workflow runs automatically when the files are committed or pushed to the `main` branch (or use **Actions** → **Gold SR - Real Apple Silicon M1 verification** → **Run workflow**).
4. Open the run and verify `gold-on-mac` completes. Download `REAL_MAC_RESULTS` and open `mac_verification.json`. The actual Mac test requires `runtime_os = Darwin`, `runtime_architecture = arm64`, `real_apple_silicon_macos = true`, `offline_tests = PASS`.
5. Check the **Attempt third-party MT5 Python bridge import** step separately. Even if it succeeds, this confirms only the beta package imports, NOT that MT5 launches, connects, sends orders, or runs reliably on Apple Silicon.

You can also connect GitHub to ChatGPT and authorize repository actions, where supported, instead of handling the upload manually. GitHub access must include a writable repository; connecting an account without granting repository access is not sufficient to start the remote Mac run.

## What the Mac runner actually tests

- Apple Silicon `macos-15` (`Darwin`/`arm64`), Python 3.12
- 11 unit tests on a historical gold breakout strategy
- Historical October backtest; *entire JSON output* compared to the original Linux reference
- `mt5_mac==0.3.0` installation + import and presence of a few functions
- It does not install/launch the MetaTrader 5 Wine terminal or connect to a demo broker.

## Reproduce on any Python 3.12+ system

```sh
python -m unittest discover -s tests -v
python run.py
python mac_verify.py
```

The `mac_verify.py` output is marked real Apple Silicon only when it actually executes on `Darwin`/`arm64`. Linux cannot produce a real Mac pass.

## Limitations

- Historical data and cost/lot assumptions remain those documented in `RESULTS.md`.
- Nothing here certifies your separate 25-file, five-engine Windows trading bot.
- Full MT5 integration needs a real MT5 installation and at least demo-account testing on a Mac, including operation across disconnects and duplicate-order prevention.
- The `mt5_mac` dependency is a third-party beta; importing it does not guarantee production reliability.

Official runner matrix: https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job

GitHub Actions billing: https://docs.github.com/en/billing/concepts/product-billing/github-actions
