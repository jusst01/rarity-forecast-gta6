# Refresh-Aware Rarity Forecaster — GTA VI trophy earn rates

[![Competition Badge](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/c/gta6-trophy-rarity-forecast-01)
[![Rank Badge](https://make.fun/badge/gta6-trophy-rarity-forecast-01/jusst01/rarity-forecast-gta6/rank.svg)](https://make.fun/c/gta6-trophy-rarity-forecast-01)
[![Reward Badge](https://make.fun/badge/gta6-trophy-rarity-forecast-01/jusst01/rarity-forecast-gta6/reward.svg)](https://make.fun/c/gta6-trophy-rarity-forecast-01)

[Competition Page](https://make.fun/c/gta6-trophy-rarity-forecast-01)

## Model Overview

This forecaster implements an eventized, structurally rigorous rarity forecasting pipeline for Grand Theft Auto VI trophy earn rates, designed specifically to outperform house persistence baselines across transient launch regimes and stable horizons.

Key innovations and architecture:
- **Eventized Refresh Staircase (S0–S1):** Filters out duplicate 10-minute poll reads to isolate actual Exophase/PSN scraping refresh events, maintaining clean time-series dynamics up to 150 recent events.
- **Earners / Players Decomposition (S2–S5):** Separates total player base tracking ($N$) growth from individual trophy earner counts ($E_i$). This prevents temporary post-launch dilution drag from being misconstrued as permanent rate decay, using Theil-Sen trend fits with dampening and group shrinkage.
- **Tier $\times$ Band Shrinkage (S4):** Stabilizes noisy or sparse trophy trends by shrinking individual slopes toward group medians ($w = n/(n+6)$).
- **$h^2$ Drift & Uncertainty Spread (S6):** Models forecast variance on the logit scale using event residual standard deviations, logarithmic player count uncertainty, and an $h^2$ shared logit drift dilution-decay term that properly prices long-horizon uncertainty.
- **Runtime Self-Calibration (S9):** Holds out recent events to dynamically measure prediction error, calibrating spread multipliers in real time during grading.
