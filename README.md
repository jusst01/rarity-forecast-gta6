# Refresh-Aware Rarity Forecaster — GTA VI trophy earn rates

[![Competition Badge](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/c/gta6-trophy-rarity-forecast-01)
[![Rank Badge](https://make.fun/badge/gta6-trophy-rarity-forecast-01/jusst01/rarity-forecast-gta6/rank.svg)](https://make.fun/c/gta6-trophy-rarity-forecast-01)
[![Reward Badge](https://make.fun/badge/gta6-trophy-rarity-forecast-01/jusst01/rarity-forecast-gta6/reward.svg)](https://make.fun/c/gta6-trophy-rarity-forecast-01)

[Competition Page](https://make.fun/c/gta6-trophy-rarity-forecast-01)

## Model Overview

This forecaster predicts GTA VI trophy earn rates from the 10-minute refresh history. Per trophy it fits a **saturating log-time curve** to the earner trajectory, with **slope damping (0.6)** so short, noisy histories cannot project runaway trends. Estimates are shrunk toward **persistence** (the last observed rate) proportional to how little data supports them, and sparse/noisy trophies borrow strength from their tier group. Global earn-rate levels are diluted by a **count-consistent FLAT model**: the case's own null-rate reads are interpolated to estimate the earner-count denominator, so dilution is applied as a count ratio rather than a guessed factor. If anything in the pipeline fails, `forecast_case` falls back to persistence and finally to a wide-spread last-read row, so it **never crashes** and always returns one valid row per case trophy.
