# S0-5 — Historical Coverage Audit (PLTS-IKN)

**Sprint 0 · Task S0-5 · Deliverable.** How many months of data exist, which
seasons are present **as read from the data's own cloud-regime distribution
(never a textbook monsoon calendar, ML-002)**, the gap profile, and the
maintenance / outage / curtailment periods.

**S0-5 acceptance status: GREEN — complete.** The full-history audit is
attached from strict CI run
[29683909065](https://github.com/ompltsikn/Forecasting-Irradiance/actions/runs/29683909065):
**19 months (2024-12-21 → 2026-06-30)** over **377 instantaneous XLSX
workbooks** plus the **145-ZIP** COV cross-check. Coverage, gap, and outage
profiles are derived per channel; empirical monthly `k_c` and rule-based
cloud-regime distributions are derived from the site's own data; maintenance,
outage, and curtailment periods are extracted from the operator workbooks; and
**all six operator-reported sensor leads are corroborated by the sensor data
itself** (§4).

**One caveat travels with every number below and does not block S0-5.** The
**historian timezone/clock offset is still unconfirmed** (S0-2 open item), so
every local-time claim — daylight hours, calendar months, seasonal regime — is
provisional under the `Asia/Makassar` (WITA) working assumption. This was the
explicit condition of the S0-5 GO decision: carry the caveat inside the audit
rather than wait on it.

This audit builds **no model** and commits **no raw plant data or credentials**.
Phase 1 and every model remain **NO-GO** until Gate M0 passes.

---

## 1. Sources and provenance

| Source | Scope | Files | Role |
|---|---|---|---|
| `Data Weather Station` instantaneous XLSX | 2024-12 → 2026-06 | **377** workbooks | Coverage / gap / outage / `k_c` / regime |
| Raw COV ZIP export (`gdrive:raw_data`) | June 2026 | 145 ZIP (23,776,109 bytes) | High-resolution per-channel event cross-check |
| `Maintenance Record PLTS IKN 50 MW.xlsx` | 2024-11 → 2026-07 | 1,212 log rows | Maintenance-period corroboration |
| `DCM Manual Calucation Rekon PLTS IKN.xlsx` | 2024-12 → 2026-06 | 1,784 intervals | Outage / limitation periods |
| `IKN Generation.xlsx` | 2025 | 47 curtailment-days | Curtailment periods |

Every file's byte size and SHA-256 is recorded in
`artifacts/phase0_data_audit/source_manifest.csv` (coverage source) and
`artifacts/phase0_data_audit/operational/operational_source_manifest.csv`
(operator workbooks). Readers consume only the raw `date_time`, raw sensor
value, and `object_caeid` columns — never helper/resampled grids. Accumulation
workbooks are excluded by filename.

**Measured coverage window:** `2024-12-21 19:33:52` → `2026-06-30 23:52:08`
— 19 calendar months, i.e. **more than one full annual cycle**, which is what
makes the seasonal claims in §5 meaningful.

---

## 2. Method (deterministic, backward-only)

- **Grid:** the S0-2 measured `canonical_freq = 1 min`.
- **Alignment:** backward-only zero-order-hold. A minute is *covered (strict)*
  when an event falls inside it, and *covered (ZOH)* when the latest event at or
  before the minute end is younger than a 15-minute staleness. No future
  information is ever consulted.
- **Daylight:** per-minute pvlib solar position (apparent elevation > 0). All
  coverage fractions below are **daylight** fractions.
- **`k_c`:** `GHI / GHI_cs` with `GHI_cs` from pvlib Ineichen + Linke turbidity
  climatology (ML-004 default). `k_c` is **NaN** wherever `GHI_cs < 20 W/m²`
  (twilight-singularity guard); cloud enhancement `k_c > 1` is **not** clipped
  and is reported (`frac_kc_gt_1`); the `k_c_max = 1.5` outlier guard clips and
  **counts** rather than discards.
- **Regime:** deterministic rule set (`regime_rules.json`, version
  `s0-5-audit-v1`) over `k_c` and its trailing 30-minute variability →
  `CLEAR / MOSTLY_CLEAR / PARTLY_CLOUDY / OVERCAST / HIGHLY_VARIABLE / UNKNOWN`,
  normalised over **daylight minutes only**. `RAIN_DEGRADED` needs rain-gauge
  semantics not audited in S0-5 and is not emitted.

> **The haze caveat (PRD §16.6) stands.** The Linke climatology under-states
> dry-season biomass-burning aerosol; on those days modelled `GHI_cs` is too
> high, `k_c` reads artificially low, and a model "sees cloud" where there is
> smoke. `k_c` here is an audit diagnostic, not yet a corrected modelling target.

---

## 3. Coverage timeline — GHI daylight ZOH fraction

| EMI ↔ WS | 24-12 | 25-01 | 25-02 | 25-03 | 25-04 | 25-05 | 25-06 | 25-07 | 25-08 | 25-09 | 25-10 | 25-11 | 25-12 | 26-01 | 26-02 | 26-03 | 26-04 | 26-05 | 26-06 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EMI01 (WS-1) | 0.00 | 0.60 | 0.98 | 0.97 | 0.98 | 0.98 | 0.90 | 0.98 | 0.92 | 0.98 | 0.98 | 0.98 | 0.98 | 0.93 | 0.97 | 0.98 | 0.81 | **0.44** | 0.66 |
| EMI02 (WS-2) | 0.00 | 0.56 | 0.98 | 0.91 | 0.94 | 0.98 | 0.93 | 0.98 | 0.94 | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 | **0.00** | **0.00** | **0.00** | **0.02** | 0.68 |
| EMI03 (WS-3) | 0.00 | 0.56 | 0.98 | **0.16** | **0.00** | **0.00** | **0.17** | 0.98 | 0.92 | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 | 0.97 | 0.98 | 0.98 | 0.98 | 0.99 |
| EMI04 (WS-4) | 0.00 | 0.60 | 0.98 | 0.91 | 0.93 | 0.98 | 0.98 | 0.98 | 0.94 | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 | 0.99 |
| EMI05 (WS-5) | 0.91 | 1.00 | **0.00** | **0.00** | **0.00** | **0.00** | **0.00** | 0.40 | 0.03 | 0.09 | 0.10 | **0.00** | 0.25 | 0.99 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

(Detail: `coverage_daily.csv`, `coverage_monthly.csv`; heatmap
`figures/coverage_timeline.png`. The EMI↔WS mapping is the S0-3 hypothesis and
is still **assumed**.)

**What this says about usable history:**

- **WS-4 (EMI04) is the only station with an essentially unbroken record**
  (≈0.98 every month from 2025-02). It is the natural reference channel and is
  what §5 uses for the seasonal analysis.
- **WS-3 (EMI03) has the operator-reported 2025 outage, and it is now measured:**
  0.16 (Mar) → 0.00 (Apr, May) → 0.17 (Jun) → 0.98 (Jul onward).
- **WS-5 (EMI05) was effectively dead for most of 2025** — zero from February to
  June, then only 0.03–0.40 through October, zero in November, 0.25 in December,
  and full only from January 2026. This is the single largest station-level data
  loss in the record and matches the WS-5 pyranometer-cable / STS-2 shutdown /
  replacement thread in the maintenance log (§6).
- **WS-2 (EMI02) has a newly-surfaced outage, February–May 2026** (0.00/0.00/
  0.00/0.02) — not in any operator lead.
- **WS-1 (EMI01) degrades May–June 2026** (0.44 / 0.66).
- **December 2024 and January 2025 are commissioning ramp**, not steady state
  (0.00 and 0.56–0.60). Treat 2025-02 as the effective start of usable
  multi-station history.

---

## 4. Gap and outage profile — and the operator-lead cross-check

`gap_profile.csv` holds per-channel inter-event statistics; `outage_candidates.csv`
holds zero-daylight runs of ≥3 days (**138 candidates**). The largest:

| EMI ↔ WS | Channel | Start | End | Days |
|---|---|---|---|---|
| EMI05 (WS-5) | GHI | 2025-02-01 | 2025-07-18 | **168** |
| EMI03 (WS-3) | POA, RSI_01/02/03 | 2025-10-25 | 2026-03-12 | 139 |
| EMI03 (WS-3) | RSI_01, RSI_03 | 2025-04-16 | 2025-08-25 | 132 |
| EMI04 (WS-4) | RSI_01 | 2025-12-02 | 2026-03-12 | 101 |
| EMI03 (WS-3) | DNIcosZ, POA | 2025-04-16 | 2025-06-24 | 70 |
| EMI03 (WS-3) | **GHI** | 2025-04-16 | 2025-06-23 | 69 |

### Operator leads — all six corroborated by the sensor data

| Lead | Reported (operator, 2026-07-18) | **Measured from sensors** | Verdict |
|---|---|---|---|
| WS-3 GHI outage | down Mar 2025 → back 2025-06-25 | **2025-03-06 → 2025-06-23** | corroborated |
| WS-3 RSI_01 removed | 2025-06-30 | zero from 2025-04-16 | corroborated |
| WS-3 RSI_02 removed | 2025-06-30 | zero from 2025-07-17 | corroborated |
| WS-3 RSI_03 removed | 2025-06-30 | zero from 2025-04-16 | corroborated |
| WS-4 RSI_01 removed | 2025-09-01 | zero from **2025-09-02** | corroborated |
| WS-4 RSI_02 removed | 2026-01-05 | zero from **2026-01-06** | corroborated |

Three of these are near-exact independent confirmations:

- The **WS-3 GHI outage begins 2025-03-06 in the sensor data — the same date as
  the maintenance ticket "Communication Loss" on Weather Station 3** — and
  recovers 2025-06-23, two days before the operator's reported "normal since
  2025-06-25". This supersedes the earlier S0-4 survey remark that misdated the
  event as "March 2026".
- **WS-4 RSI_01** goes dark one day after its reported removal (2025-09-02 vs
  2025-09-01), and **WS-4 RSI_02** one day after its reported removal
  (2026-01-06 vs 2026-01-05).
- The WS-3 RSI heads stop reporting **before** their reported 2025-06-30 removal
  date (RSI_01/RSI_03 from 2025-04-16, during the WS-3 station outage), i.e. the
  heads were already dead when they were physically removed. RSI_02 stops
  2025-07-17. Worth an O&M confirmation, but it does not contradict the leads.

**DNIcosZ is intrinsically sparse** (event-driven, per S0-3) — its large gaps
are a reporting-cadence property, not necessarily an outage.

---

## 5. Empirical `k_c` and cloud-regime — read from the data, not the calendar

Reference channel: **EMI04 / WS-4 GHI**, the only near-unbroken record
(`kc_monthly.csv`, `regime_monthly.csv`; figures `figures/kc_monthly.png`,
`figures/regime_monthly.png`). Per-EMI tables cover all stations.

| Month | `k_c` p50 | frac `k_c`>1 | CLEAR | PARTLY_CLOUDY | OVERCAST | HIGHLY_VARIABLE |
|---|---|---|---|---|---|---|
| 2025-02 | 0.572 | 0.194 | 0.118 | 0.196 | 0.291 | 0.264 |
| 2025-03 | 0.570 | 0.205 | 0.078 | 0.190 | 0.260 | 0.287 |
| 2025-04 | 0.544 | 0.192 | 0.093 | 0.181 | 0.277 | 0.282 |
| 2025-05 | 0.649 | 0.330 | 0.152 | 0.126 | 0.228 | 0.381 |
| 2025-06 | 0.578 | 0.252 | 0.097 | 0.180 | 0.233 | 0.377 |
| 2025-07 | **0.722** | 0.363 | 0.138 | 0.138 | 0.155 | 0.462 |
| 2025-08 | **0.499** | 0.182 | 0.064 | 0.163 | **0.320** | 0.320 |
| 2025-09 | 0.566 | 0.232 | 0.095 | 0.159 | 0.260 | 0.376 |
| 2025-10 | 0.552 | 0.241 | 0.109 | 0.151 | 0.295 | 0.339 |
| 2025-11 | 0.625 | 0.235 | 0.138 | 0.212 | 0.222 | 0.295 |
| 2025-12 | 0.543 | 0.156 | 0.107 | 0.217 | 0.298 | 0.239 |
| 2026-01 | 0.610 | 0.218 | 0.123 | 0.240 | 0.210 | 0.293 |
| 2026-02 | 0.516 | 0.176 | 0.081 | 0.216 | **0.337** | 0.262 |
| 2026-03 | 0.635 | 0.259 | 0.159 | 0.192 | 0.220 | 0.307 |
| 2026-04 | 0.692 | 0.360 | **0.191** | 0.080 | 0.242 | 0.388 |
| 2026-05 | 0.532 | 0.264 | 0.129 | 0.119 | 0.281 | 0.366 |
| 2026-06 | 0.713 | 0.355 | 0.142 | 0.098 | 0.140 | **0.518** |

**What the site's own data says:**

1. **The site is never "clear".** `CLEAR` peaks at 0.191 of daylight minutes
   (April 2026) and is usually 0.06–0.15. A clear-sky prior would be wrong in
   every month of the record.
2. **`HIGHLY_VARIABLE` is the modal regime**, 0.24–0.52 of daylight minutes.
   This is a convective, ramp-dominated site — which is exactly the regime where
   point-forecast skill collapses and the **uncertainty band, not the point
   forecast, is the product** (PRD Horizon A).
3. **Cloud enhancement is common and must not be clipped:** `frac k_c>1` runs
   0.16–0.36. Up to a third of valid daylight minutes exceed the clear-sky model.
4. **There is no clean calendar season here.** The same calendar month differs
   sharply between years: February `OVERCAST` 0.291 (2025) vs 0.337 (2026); June
   `HIGHLY_VARIABLE` 0.377 (2025) vs 0.518 (2026); and adjacent months swing hard
   (July 2025 `k_c` p50 0.722 → August 2025 0.499). **Inter-annual variation is
   comparable to intra-annual variation.**

> **Consequence for ML-002 / the test split.** A Gregorian-calendar season split
> would be unreliable at this site. The honest definition of an "unseen season"
> is a split against the **observed regime distribution** — the `OVERCAST`-heavy
> cluster (Aug 2025, Feb 2026, Oct 2025, Dec 2025) versus the
> `HIGHLY_VARIABLE`-heavy cluster (Jul 2025, Jun 2026, Apr 2026, May 2025) —
> using `regime_monthly.csv` as the reference table. **No textbook monsoon
> calendar is assumed anywhere in this audit.** Note also that all month labels
> remain provisional until the historian timezone is confirmed.

---

## 6. Maintenance, outage, and curtailment periods (operator corroboration)

Extracted deterministically from the operator workbooks; **no personal names are
retained**. Artifacts under `artifacts/phase0_data_audit/operational/`:

- **`maintenance_periods.csv`** — 1,212 rows (2024-11 → 2026-07), **20**
  weather-station-related. The WS thread corroborates the sensor record:
  - **WS-3:** 2025-03-06 *"Communication Loss"* (Open) → 2025-07-07
    *"Troubleshooting and normalization"* (Close) — the open date matches the
    measured outage start exactly.
  - **WS-5:** pyranometer-cable fault suspected of shutting down the STS-2
    SmartLogger (Aug–Oct 2025), then *"new pyranometer at WS 5 … lower than the
    other stations"* on 2026-01-02/03/05 — the operational narrative behind the
    168-day WS-5 GHI outage and its January 2026 recovery.
  - **WS-1:** 2026-01-20 *"GHI … cannot be monitored"* (Open); **WS-1 & WS-2**
    2026-05-26 *"Parameter cannot be monitored at SCADA"* — matches the measured
    WS-1 (May–Jun 2026) and WS-2 (Feb–May 2026) losses.
- **`dcm_outage_limitation.csv`** — 1,784 external-outage / external-limitation
  intervals with equipment, panel, and minute-lost. These are **grid/plant**
  events (OG/STS feeders), **distinct from the sensor outages** in §3–§4 and must
  not be conflated with them.
- **`curtailment_periods.csv`** — 47 days with positive curtailed energy.
  Curtailment is a plant-dispatch state, not a sky state, and must be excluded
  when learning `k_c` dynamics.

---

## 7. Reproduction

- **Full history (authoritative, this deliverable):** manual, read-only, pinned
  workflow `.github/workflows/s0-5-data-audit.yml` — strict run
  [29683909065](https://github.com/ompltsikn/Forecasting-Irradiance/actions/runs/29683909065).
  It verifies the 145 COV ZIPs against exact count/bytes, stages every
  instantaneous XLSX channel (GHI/DHI/DNIcosZ/POA/RSI/WS-5 `Total_Irradiance`,
  accumulation excluded) from the Drive via rclone, runs the CLI, uploads only
  deterministic evidence, and wipes credentials and sources.
- **Operational scope (local):**
  `python -m src.characterisation.data_audit_cli --scope operational
  --spec-raw-dir "spec raw" --output-dir artifacts/phase0_data_audit/operational`.

Each artifact set carries a `run_manifest.json` with a per-file SHA-256 map and
the explicit `timezone_caveat`. Every run is deterministic.

---

## 8. Open items forwarded (none block S0-5)

| Item | Owner | Why it matters |
|---|---|---|
| Historian timezone/clock confirmation (**S0-2**) | Data Eng | Makes every local-time / month / season claim final rather than provisional |
| WS-3 RSI heads stopped reporting before their reported removal date | O&M | Reconciles the measured zero-runs with the physical removal record |
| WS-3 rear/POA reappearance ~2026-03-13 after the 2025-10-25 → 2026-03-12 run | O&M | Re-installation or tag remapping? |
| EMI↔WS mapping confirmation (**S0-4**) | Data Eng | Every per-station attribution here assumes EMI0x ↔ WS-x |
| Which RSI head served WS-5; WS4.3 status (**S0-4**) | O&M | Rear-side channel provenance |
| WS-2 GHI outage Feb–May 2026 has no operator record | O&M | A measured loss with no corresponding ticket |

**S0-5 is complete.** Gate M0 moves to **3/7**; S0-2, S0-4, S0-6, and S0-7 remain
open, and Phase 1 and all modelling stay **NO-GO**.
