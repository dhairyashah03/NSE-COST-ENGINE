# Changelog

All notable changes to the NSE Cost Engine are documented here.

## [0.1.0] - 2026-05-19

### Added
- **Core engine** with 9 cost components: brokerage, STT, exchange charges, SEBI fee, IPFT, stamp duty, GST, DP charges, MTF interest + pledge charges
- **5 brokerage models**: zero, flat, percentage, min_of, slab — configurable per broker via YAML
- **STT calculation** with segment-specific rates (revised Oct 2024): equity delivery 0.1% both sides, intraday 0.025% sell, futures 0.05% sell, options 0.15% sell on premium
- **Exchange transaction charges** for NSE and BSE with segment-specific rates
- **SEBI turnover fee** (0.0001%) and **IPFT** (0.0000001%) — negligible but part of GST base
- **Stamp duty** with buy-side-only logic (post-2020 reform) and per-segment rates
- **GST** at 18% on (brokerage + exchange + SEBI + IPFT), correctly excluding STT and stamp duty
- **DP charges** with broker-specific rates (₹12.50 for Dhan vs ₹15.93 CDSL default)
- **MTF interest** with 5-slab flat structure, leverage-based input, buy-side-only accrual
- **MTF pledge/unpledge charges** at ₹15 + GST per ISIN per transaction
- **Market impact models**: square-root (default) and Almgren-Chriss (advanced)
- **Dhan API integration** for live volatility and volume data (data_feed.py)
- **Config-driven architecture**: all rates in YAML, broker profiles with deep merge
- **Contract note rounding**: STT and stamp duty rounded to nearest rupee, matching actual broker charges
- **Multi-broker support**: Dhan, Zerodha profiles + custom template
- **CostEngine API**: calculate(), round_trip(), breakeven(), what_if()
- **Streamlit dashboard** with 5 tabs: cost calculator, round trip P&L, market impact visualiser, broker comparison, breakeven
- **Excel report generator** (6 sheets, 4 charts) with live Dhan API data
- **PDF project overview** (7 pages, 4 charts)
- **47 automated tests** covering all components, segments, edge cases

### Validated
- **Contract note**: 6/6 exact match against real Dhan contract note (08-May-2026)
- **MTF calculator**: 9/9 match against Dhan's MTF calculator (interest ₹353.14 exact)
- **MTF cross-validation**: engine ₹102.66 vs Dhan's published example ₹102.60

### Fixed
- YAML `on` keyword parsed as boolean — renamed to `base_on`
- Stamp duty rounding to nearest rupee (discovered from Dhan documentation)
- MTF 5th slab (₹50L+ at 16.49%) missing from original spec
- MTF interest double-counting on sell side — fixed to buy-side only
- MTF funding % hardcoded at 75% — replaced with leverage-based input
- MTF pledge/unpledge charges not modelled — added as separate components