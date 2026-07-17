# S0-2 COV Characterisation

This report is generated from the same measured tables and code used by the CLI and Colab runner. It characterises change-of-value reporting only; it builds no forecasting model or baseline.

## Executive decision

- S0-2 acceptance status: **YELLOW**
- Source-integrity strict status: **passed**
- Data-backed `canonical_freq`: **1min**
- Decision statistic (slowest five-channel median active p50): **26.401 seconds**
- Supported instantaneous tags in the decision: **18**
- Supported tags slower than the selected grid: **1**

Remaining acceptance blockers:

- configured historian max-report-time is not confirmed
- historian timestamp timezone is not independently confirmed

Gate M0 and Phase 1 are separate decisions. This report does not authorize modelling.

## Source reconciliation and integrity

- Local ZIP files: **145**
- ZIPs matched to the reference inventory: **145**
- CSV entries: **170**
- Populated CSV entries: **163**
- Empty CSV entries: **7**
- Events after integrity handling: **2640992**
- Exact duplicates removed: **15239**
- Conflicting tag/timestamps quarantined: **0**
- Strict errors: **0**

The Drive connector reconciliation proves filename and byte-size equality. Content equality is established when the notebook copies mounted Drive files to VM-local storage and verifies SHA-256.

## Actual CSV schema correction

The second CSV **header name** is the full SCADA tag. The second field in each data row is the numeric observation. The third field is preserved as `object_caeid_raw`; no quality semantics are assigned without a source-system record. ZIP and CSV filenames are never used to infer the parameter.

## Timestamp semantics

Observed timestamp shapes: **naive**.

Naive timestamps are preserved as recorded. No UTC conversion is applied. Hour-of-day irradiance activity is used only to assess consistency with the site clock (Asia/Makassar/WITA); it does not substitute for historian clock/configuration evidence.

Substantial non-flat irradiance occurs from 06:00-18:00 as recorded (hour count at least max(20, 1% of the peak)); there are 21 non-flat events outside that window. The distribution is consistent with naive WITA; interpreting the same clock as UTC would move the window to 14:00-02:00 WITA, and the UTC interpretation places observed activity into local night hours. This is consistency evidence, not a historian clock/configuration record.

## Methods

All tags retain source provenance. Exact duplicates are removed before statistics and conflicting tag/timestamps are quarantined. Deadband is the first supported lower-edge cluster of positive `|delta value|` using `isclose(rtol=5e-4, atol=1e-6)`. Active instantaneous intervals use `max(5 * deadband, 5 W/m2)`; lower intervals are labelled `flat_or_night`, not automatically outage. Inter-arrival p50/p90/p99 and maximum gaps remain in seconds.

Measured parameter-class counts: `{"instantaneous_irradiance": 26, "irradiance_accumulation": 76, "meteorological": 34}`.

## Canonical-frequency evidence

Only instantaneous irradiance tags enter this decision. Accumulation and meteorological tags remain characterised but cannot select the grid.

| channel_group | median_active_p50_s |
|---|---|
| GHI | 23.12 |
| DHI | 21.5345 |
| DNIcosZ | 23.136 |
| POA | 18.1915 |
| RSI | 26.401 |

The approved candidate sequence is 1min, 5min, then 15min. The first grid no finer than the slowest channel median is selected. Sub-minute reporting is evidence supporting 1min, not a new product requirement.

## Heartbeat and configured max-report-time

Supported observed repeated-value heartbeat candidates: **0 of 136 tags**.

An empirical candidate is never labelled the configured historian max-report-time. `configured_max_report_time_status` remains `unknown` until source-system configuration evidence is available.

## Exceptions and caveats

- Empty CSVs are explicit source artifacts and are not silently ignored.
- `flat_or_night` preserves ambiguity between night and other flat conditions.
- Maximum observed gaps over this extract are observations, not future guarantees.
- The raw extract supports COV cadence characterisation, not seasonal historical-coverage acceptance.

## Complete per-tag appendix

| full_tag | emi | canonical_parameter | parameter_class | event_count_before_integrity | event_count | deadband_estimate | deadband_confidence | interarrival_p50_s | interarrival_p90_s | interarrival_p99_s | max_gap_s | observed_heartbeat_candidate_s | heartbeat_confidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PLTS IKN / STS02 / WB02_EMI05 / MEAS / Daily radiation | EMI05 | GHI Daily Acummulation | irradiance_accumulation | 319949 | 319949 | 0.000278 | high | 3.031 | 6.077 | 22.761 | 22938.269 | — | unresolved |
| PLTS IKN / STS02 / WB02_EMI05 / MEAS / Total Irradiance | EMI05 | Global Horizontal Irradiance (GHI) | instantaneous_irradiance | 533171 | 533171 | 0.1 | high | 1.531 | 4.484 | 10.654 | 42682.023 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / AMBIENT AIR HUMIDITY | EMI04 | AMBIENT AIR HUMIDITY | meteorological | 51921 | 51921 | 0.099999 | high | 19.824 | 42.882 | 95.544 | 59351.962 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / AMBIENT AIR TEMP | EMI04 | AMBIENT AIR TEMP | meteorological | 15738 | 15738 | 0.1 | high | 115.477 | 324.5422 | 686.05024 | 1626.257 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / DAILY RAINFALL | EMI04 | DAILY RAINFALL | meteorological | 213 | 213 | 0.2 | high | 125.327 | 20178.8259 | 222209.453 | 602274.953 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / DHI DAILY ACCUM | EMI04 | DHI Daily Acummulation | irradiance_accumulation | 16352 | 16352 | 0.002778 | high | 62.754 | 121.992 | 372.653 | 29375.871 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / DHI MONTHLY ACCUM | EMI04 | DHI Monthly Acummulation | irradiance_accumulation | 346 | 346 | 0.277778 | high | 2596.428 | 7357.6608 | 59434.7246 | 60683.174 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / DHI YEARLY ACCUM | EMI04 | DHI Yearly Acummulation | irradiance_accumulation | 343 | 343 | 0.277771 | high | 2583.436 | 6898.9636 | 60729.8595 | 62059.775 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / DIFFUSE HORIZONTAL IRRADIANCE (DHI) | EMI04 | Diffuse Horizontal Irradiance (DHI) | instantaneous_irradiance | 51722 | 51722 | 1 | high | 19.825 | 39.617 | 98.9968 | 48089.112 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / DIRECT HORIZONTAL IRRADIANCE (DNI*cosZ) | EMI04 | Direct Horizontal Irradiance (DNIcosZ) | instantaneous_irradiance | 5875 | 5875 | 1 | high | 19.825 | 46.2097 | 2212.08314 | 82717.517 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / DNI*cosZ DAILY ACCUM | EMI04 | DNIcosZ Daily Acummulation | irradiance_accumulation | 1253 | 1253 | 0.002778 | high | 65.94 | 371.824 | 42753.6774 | 126349.684 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / DNI*cosZ MONTHLY ACCUM | EMI04 | DNIcosZ Monthly Acummulation | irradiance_accumulation | 20 | 20 | — | unresolved | 88098.858 | 241250.763 | 411651.951 | 426971.651 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / DNI*cosZ YEARLY ACCUM | EMI04 | DNIcosZ Yearly Acummulation | irradiance_accumulation | 20 | 20 | — | unresolved | 86611.426 | 256793.113 | 329103.734 | 344666.816 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / GHI DAILY ACCUM | EMI04 | GHI Daily Acummulation | irradiance_accumulation | 16962 | 16962 | 0.002778 | high | 62.738 | 75.922 | 362.9628 | 29184.534 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / GHI MONTHLY ACCUM | EMI04 | GHI Monthly Acummulation | irradiance_accumulation | 464 | 464 | 0.277778 | high | 1857.078 | 4970.7254 | 57813.7002 | 59813.046 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / GHI YEARLY ACCUM | EMI04 | GHI Yearly Acummulation | irradiance_accumulation | 457 | 457 | 0.277771 | high | 1798.3875 | 4115.6095 | 59940.9245 | 65946.664 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / GLOBAL HORIZONTAL IRRADIANCE (GHI) | EMI04 | Global Horizontal Irradiance (GHI) | instantaneous_irradiance | 53445 | 53445 | 1 | high | 19.824 | 39.523 | 89.092 | 47907.648 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / IN-PLANE REAR-SIDE IRRADIANCE (RSI) 03 | EMI04 | In-Plane Rear-Side Irradiance (RSI) 03 | instantaneous_irradiance | 12359 | 12359 | 1 | high | 23.12 | 128.74 | 808.44776 | 72799.671 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / PEAK OF SUN HOURS | EMI04 | PEAK OF SUN HOURS | meteorological | 10904 | 10904 | 0.01 | high | 66.033 | 191.321 | 749.17238 | 30431.413 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / RSI DAILY ACCUM 03 | EMI04 | RSI 03 Daily Acummulation | irradiance_accumulation | 758 | 758 | 0.002778 | high | 811.73 | 3393.4408 | 33885.0848 | 41938.108 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / RSI MONTHLY ACCUM 03 | EMI04 | RSI 03 Monthly Acummulation | irradiance_accumulation | 8 | 8 | — | unresolved | 336852.26 | 426349.308 | 435017.075 | 435980.16 | — | unresolved |
| PLTS IKN / STS04 / WB04_EMI04 / MEAS / RSI YEARLY ACCUM 03 | EMI04 | RSI 03 Yearly Acummulation | irradiance_accumulation | 7 | 7 | — | unresolved | 348587.3 | 429934.285 | 438107.208 | 439015.31 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / AMBIENT AIR HUMIDITY | EMI02 | AMBIENT AIR HUMIDITY | meteorological | 49887 | 49887 | 0.099999 | high | 23.104 | 49.522 | 181.4194 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / AMBIENT AIR TEMP | EMI02 | AMBIENT AIR TEMP | meteorological | 9545 | 9545 | 0.1 | high | 132.06 | 379.6705 | 861.80678 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / DAILY RAINFALL | EMI02 | DAILY RAINFALL | meteorological | 413 | 413 | 0.2 | high | 69.3695 | 18790.1281 | 75913.1552 | 100644.469 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / DHI DAILY ACCUM | EMI02 | DHI Daily Acummulation | irradiance_accumulation | 11533 | 11533 | 0.002778 | high | 69.267 | 72.7811 | 529.92013 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / DHI MONTHLY ACCUM | EMI02 | DHI Monthly Acummulation | irradiance_accumulation | 579 | 579 | 0.277778 | high | 1358.6615 | 6437.0079 | 56059.0159 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / DHI YEARLY ACCUM | EMI02 | DHI Yearly Acummulation | irradiance_accumulation | 578 | 578 | 0.277771 | high | 1351.015 | 6097.4952 | 56194.1022 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / DIFFUSE HORIZONTAL IRRADIANCE (DHI) | EMI02 | Diffuse Horizontal Irradiance (DHI) | instantaneous_irradiance | 31683 | 31683 | 1 | high | 23.12 | 39.617 | 105.68219 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / DIRECT HORIZONTAL IRRADIANCE (DNI*cosZ) | EMI02 | Direct Horizontal Irradiance (DNIcosZ) | instantaneous_irradiance | 714 | 714 | 1 | high | 69.315 | 7686.694 | 67402.4088 | 100644.469 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / DNI*cosZ DAILY ACCUM | EMI02 | DNIcosZ Daily Acummulation | irradiance_accumulation | 363 | 363 | 0.002778 | high | 428.966 | 24614.0417 | 77989.0295 | 100644.469 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / DNI*cosZ MONTHLY ACCUM | EMI02 | DNIcosZ Monthly Acummulation | irradiance_accumulation | 273 | 273 | — | unresolved | 16.2685 | 37802.9838 | 83072.574 | 100644.469 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / DNI*cosZ YEARLY ACCUM | EMI02 | DNIcosZ Yearly Acummulation | irradiance_accumulation | 274 | 274 | — | unresolved | 16.299 | 37636.6496 | 82985.6707 | 100644.469 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / GHI DAILY ACCUM | EMI02 | GHI Daily Acummulation | irradiance_accumulation | 11610 | 11610 | 0.002778 | high | 69.252 | 72.752 | 492.14052 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / GHI MONTHLY ACCUM | EMI02 | GHI Monthly Acummulation | irradiance_accumulation | 603 | 603 | 0.277778 | high | 1291.1835 | 6084.3402 | 54708.5203 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / GHI YEARLY ACCUM | EMI02 | GHI Yearly Acummulation | irradiance_accumulation | 603 | 603 | 0.277771 | high | 1254.776 | 5291.8915 | 54326.8238 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / GLOBAL HORIZONTAL IRRADIANCE (GHI) | EMI02 | Global Horizontal Irradiance (GHI) | instantaneous_irradiance | 32023 | 32023 | 1 | high | 23.12 | 39.555 | 99.07874 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / GLOBAL INCLINED IRRADIANCE (POA) | EMI02 | Global Inclined Irradiance (POA) | instantaneous_irradiance | 32510 | 32510 | 1 | high | 23.12 | 32.994 | 99.00988 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / IN-PLANE REAR-SIDE IRRADIANCE (RSI) 01 | EMI02 | In-Plane Rear-Side Irradiance (RSI) 01 | instantaneous_irradiance | 9374 | 9374 | 1 | high | 26.416 | 135.379 | 926.59416 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / IN-PLANE REAR-SIDE IRRADIANCE (RSI) 02 | EMI02 | In-Plane Rear-Side Irradiance (RSI) 02 | instantaneous_irradiance | 9152 | 9152 | 1 | high | 26.401 | 122.069 | 1198.5605 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / IN-PLANE REAR-SIDE IRRADIANCE (RSI) 03 | EMI02 | In-Plane Rear-Side Irradiance (RSI) 03 | instantaneous_irradiance | 9514 | 9514 | 1 | high | 26.401 | 121.0852 | 1095.59596 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / PEAK OF SUN HOURS | EMI02 | PEAK OF SUN HOURS | meteorological | 7890 | 7890 | 0.01 | high | 69.424 | 184.745 | 2485.32424 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / POA DAILY ACCUM | EMI02 | POA Daily Acummulation | irradiance_accumulation | 11780 | 11780 | 0.002778 | high | 69.236 | 72.72 | 484.94184 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / POA MONTHLY ACCUM | EMI02 | POA Monthly Acummulation | irradiance_accumulation | 632 | 632 | 0.277778 | high | 1175.143 | 4822.736 | 53681.3769 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / POA YEARLY ACCUM | EMI02 | POA Yearly Acummulation | irradiance_accumulation | 632 | 632 | 0.277771 | high | 1185.282 | 5035.089 | 54240.7637 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / PRESSURE | EMI02 | PRESSURE | meteorological | 272 | 272 | — | unresolved | 16.238 | 37969.318 | 83159.4772 | 100644.469 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / PV MODUL TEMP 01 | EMI02 | PV MODUL TEMP 01 | meteorological | 10431 | 10431 | 0.1 | high | 72.673 | 313.4101 | 1831.89615 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / PV MODUL TEMP 02 | EMI02 | PV MODUL TEMP 02 | meteorological | 10589 | 10589 | 0.1 | high | 72.673 | 310.2594 | 1673.70682 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / PV MODUL TEMP 03 | EMI02 | PV MODUL TEMP 03 | meteorological | 10294 | 10294 | 0.1 | high | 72.689 | 297.1568 | 1907.84092 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / RSI DAILY ACCUM 01 | EMI02 | RSI 01 Daily Acummulation | irradiance_accumulation | 1038 | 1038 | 0.002778 | high | 551.703 | 2136.766 | 36709.3061 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / RSI DAILY ACCUM 02 | EMI02 | RSI 02 Daily Acummulation | irradiance_accumulation | 936 | 936 | 0.002778 | high | 575.48 | 3650.0178 | 38202.945 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / RSI DAILY ACCUM 03 | EMI02 | RSI 03 Daily Acummulation | irradiance_accumulation | 1010 | 1010 | 0.002778 | high | 561.467 | 2475.0248 | 37700.1617 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / RSI MONTHLY ACCUM 01 | EMI02 | RSI 01 Monthly Acummulation | irradiance_accumulation | 280 | 280 | — | unresolved | 16.879 | 36638.6444 | 82464.2513 | 100644.469 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / RSI MONTHLY ACCUM 02 | EMI02 | RSI 02 Monthly Acummulation | irradiance_accumulation | 279 | 279 | — | unresolved | 16.722 | 36804.9834 | 82551.1545 | 100644.469 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / RSI MONTHLY ACCUM 03 | EMI02 | RSI 03 Monthly Acummulation | irradiance_accumulation | 280 | 280 | — | unresolved | 16.879 | 36638.6476 | 82464.2513 | 100644.469 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / RSI YEARLY ACCUM 01 | EMI02 | RSI 01 Yearly Acummulation | irradiance_accumulation | 280 | 280 | — | unresolved | 16.879 | 36638.6476 | 82464.2513 | 93287.737 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / RSI YEARLY ACCUM 02 | EMI02 | RSI 02 Yearly Acummulation | irradiance_accumulation | 279 | 279 | — | unresolved | 16.722 | 34068.0788 | 82551.1545 | 100644.469 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / RSI YEARLY ACCUM 03 | EMI02 | RSI 03 Yearly Acummulation | irradiance_accumulation | 280 | 280 | — | unresolved | 16.879 | 36638.6476 | 82464.2513 | 100644.469 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / WIND DIRECTION | EMI02 | WIND DIRECTION | meteorological | 141994 | 141994 | 1 | high | 6.623 | 23.136 | 52.74 | 89597.825 | — | unresolved |
| PLTS IKN / STS05 / WB05_EMI02 / MEAS / WIND SPEED | EMI02 | WIND SPEED | meteorological | 66903 | 66903 | 0.1 | high | 16.512 | 26.401 | 89.17 | 89597.825 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / AMBIENT AIR HUMIDITY | EMI03 | AMBIENT AIR HUMIDITY | meteorological | 81362 | 81362 | 0.099999 | high | 23.105 | 46.21 | 148.446 | 30382.751 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / AMBIENT AIR TEMP | EMI03 | AMBIENT AIR TEMP | meteorological | 15671 | 15671 | 0.1 | high | 99.059 | 336.4355 | 825.98476 | 3284.802 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / DAILY RAINFALL | EMI03 | DAILY RAINFALL | meteorological | 474 | 474 | 0.2 | high | 72.595 | 17834.1598 | 63347.56 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / DHI DAILY ACCUM | EMI03 | DHI Daily Acummulation | irradiance_accumulation | 17637 | 17637 | 0.002778 | high | 69.299 | 75.876 | 363.37495 | 26657.246 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / DHI MONTHLY ACCUM | EMI03 | DHI Monthly Acummulation | irradiance_accumulation | 800 | 800 | 0.277779 | high | 1251.143 | 3901.8604 | 50928.7355 | 58639.521 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / DHI YEARLY ACCUM | EMI03 | DHI Yearly Acummulation | irradiance_accumulation | 774 | 774 | 0.277832 | high | 1186.928 | 3580.6154 | 53862.3728 | 72547.971 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / DIFFUSE HORIZONTAL IRRADIANCE (DHI) | EMI03 | Diffuse Horizontal Irradiance (DHI) | instantaneous_irradiance | 46968 | 46968 | 1 | high | 23.121 | 39.664 | 92.466 | 44627.472 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / DIRECT HORIZONTAL IRRADIANCE (DNI*cosZ) | EMI03 | Direct Horizontal Irradiance (DNIcosZ) | instantaneous_irradiance | 403 | 403 | 1 | high | 23.12 | 18800.6729 | 76313.9849 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / DNI*cosZ DAILY ACCUM | EMI03 | DNIcosZ Daily Acummulation | irradiance_accumulation | 279 | 279 | — | unresolved | 17.5525 | 36804.5677 | 82552.035 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / DNI*cosZ MONTHLY ACCUM | EMI03 | DNIcosZ Monthly Acummulation | irradiance_accumulation | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / DNI*cosZ YEARLY ACCUM | EMI03 | DNIcosZ Yearly Acummulation | irradiance_accumulation | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / GHI DAILY ACCUM | EMI03 | GHI Daily Acummulation | irradiance_accumulation | 16943 | 16943 | 0.002778 | high | 69.299 | 76.079 | 374.97373 | 26597.851 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / GHI MONTHLY ACCUM | EMI03 | GHI Monthly Acummulation | irradiance_accumulation | 736 | 736 | 0.277778 | high | 1363.465 | 4427.5182 | 52945.6112 | 59623.999 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / GHI YEARLY ACCUM | EMI03 | GHI Yearly Acummulation | irradiance_accumulation | 722 | 722 | 0.277832 | high | 1239.631 | 3828.979 | 54812.4118 | 73716.225 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / GLOBAL HORIZONTAL IRRADIANCE (GHI) | EMI03 | Global Horizontal Irradiance (GHI) | instantaneous_irradiance | 45025 | 45025 | 1 | high | 23.121 | 46.147 | 109.041 | 44861.848 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / GLOBAL INCLINED IRRADIANCE (POA) | EMI03 | Global Inclined Irradiance (POA) | instantaneous_irradiance | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / IN-PLANE REAR-SIDE IRRADIANCE (RSI) 01 | EMI03 | In-Plane Rear-Side Irradiance (RSI) 01 | instantaneous_irradiance | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / IN-PLANE REAR-SIDE IRRADIANCE (RSI) 02 | EMI03 | In-Plane Rear-Side Irradiance (RSI) 02 | instantaneous_irradiance | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / IN-PLANE REAR-SIDE IRRADIANCE (RSI) 03 | EMI03 | In-Plane Rear-Side Irradiance (RSI) 03 | instantaneous_irradiance | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / PEAK OF SUN HOURS | EMI03 | PEAK OF SUN HOURS | meteorological | 11185 | 11185 | 0.01 | high | 69.408 | 188.213 | 997.34301 | 27521.41 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / POA DAILY ACCUM | EMI03 | POA Daily Acummulation | irradiance_accumulation | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / POA MONTHLY ACCUM | EMI03 | POA Monthly Acummulation | irradiance_accumulation | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / POA YEARLY ACCUM | EMI03 | POA Yearly Acummulation | irradiance_accumulation | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / PRESSURE | EMI03 | PRESSURE | meteorological | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / PV MODUL TEMP 01 | EMI03 | PV MODUL TEMP 01 | meteorological | 14539 | 14539 | 0.1 | high | 89.076 | 339.9856 | 1537.91436 | 9068.981 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / PV MODUL TEMP 02 | EMI03 | PV MODUL TEMP 02 | meteorological | 14021 | 14021 | 0.1 | high | 79.2185 | 329.8601 | 1797.30392 | 14910.993 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / PV MODUL TEMP 03 | EMI03 | PV MODUL TEMP 03 | meteorological | 13742 | 13742 | 0.1 | high | 75.97 | 323.03 | 1900.4778 | 14940.753 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / RSI DAILY ACCUM 01 | EMI03 | RSI 01 Daily Acummulation | irradiance_accumulation | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / RSI DAILY ACCUM 02 | EMI03 | RSI 02 Daily Acummulation | irradiance_accumulation | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / RSI DAILY ACCUM 03 | EMI03 | RSI 03 Daily Acummulation | irradiance_accumulation | 542 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / RSI MONTHLY ACCUM 01 | EMI03 | RSI 01 Monthly Acummulation | irradiance_accumulation | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / RSI MONTHLY ACCUM 02 | EMI03 | RSI 02 Monthly Acummulation | irradiance_accumulation | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / RSI MONTHLY ACCUM 03 | EMI03 | RSI 03 Monthly Acummulation | irradiance_accumulation | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / RSI YEARLY ACCUM 01 | EMI03 | RSI 01 Yearly Acummulation | irradiance_accumulation | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / RSI YEARLY ACCUM 02 | EMI03 | RSI 02 Yearly Acummulation | irradiance_accumulation | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / RSI YEARLY ACCUM 03 | EMI03 | RSI 03 Yearly Acummulation | irradiance_accumulation | 271 | 271 | — | unresolved | 16.594 | 38004.4576 | 83247.546 | 100640.454 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / WIND DIRECTION | EMI03 | WIND DIRECTION | meteorological | 140105 | 140105 | 1 | high | 13.232 | 26.354 | 72.627 | 1300.493 | — | unresolved |
| PLTS IKN / STS06 / WB06_EMI03 / MEAS / WIND SPEED | EMI03 | WIND SPEED | meteorological | 81804 | 81804 | 0.1 | high | 19.84 | 26.417 | 135.09914 | 37878.454 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / AMBIENT AIR HUMIDITY | EMI01 | AMBIENT AIR HUMIDITY | meteorological | 79651 | 79651 | 0.099999 | high | 13.248 | 72.877 | 283.96829 | 17334.655 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / AMBIENT AIR TEMP | EMI01 | AMBIENT AIR TEMP | meteorological | 13690 | 13690 | 0.1 | high | 122.585 | 383.2306 | 991.63956 | 3172.983 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / DAILY RAINFALL | EMI01 | DAILY RAINFALL | meteorological | 458 | 458 | 0.2 | high | 66.377 | 18502.2738 | 63970.764 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / DHI DAILY ACCUM | EMI01 | DHI Daily Acummulation | irradiance_accumulation | 5887 | 5887 | 0.002778 | high | 62.7375 | 122.507 | 11640.4964 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / DHI MONTHLY ACCUM | EMI01 | DHI Monthly Acummulation | irradiance_accumulation | 403 | 403 | 0.277778 | high | 1358.254 | 16373.7175 | 67006.8317 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / DHI YEARLY ACCUM | EMI01 | DHI Yearly Acummulation | irradiance_accumulation | 401 | 401 | 0.277771 | high | 1362.0265 | 16438.5914 | 67073.1812 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / DIFFUSE HORIZONTAL IRRADIANCE (DHI) | EMI01 | Diffuse Horizontal Irradiance (DHI) | instantaneous_irradiance | 14342 | 14342 | 1 | high | 19.949 | 59.754 | 192.7026 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / DIRECT HORIZONTAL IRRADIANCE (DNI*cosZ) | EMI01 | Direct Horizontal Irradiance (DNIcosZ) | instantaneous_irradiance | 283 | 283 | — | unresolved | 15.4215 | 35971.7116 | 82206.6688 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / DNI*cosZ DAILY ACCUM | EMI01 | DNIcosZ Daily Acummulation | irradiance_accumulation | 281 | 281 | — | unresolved | 15.4215 | 36470.1622 | 82380.4624 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / DNI*cosZ MONTHLY ACCUM | EMI01 | DNIcosZ Monthly Acummulation | irradiance_accumulation | 281 | 281 | — | unresolved | 15.4215 | 36470.1622 | 82380.4624 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / DNI*cosZ YEARLY ACCUM | EMI01 | DNIcosZ Yearly Acummulation | irradiance_accumulation | 282 | 282 | — | unresolved | 15.467 | 36303.492 | 82293.5656 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / GHI DAILY ACCUM | EMI01 | GHI Daily Acummulation | irradiance_accumulation | 10583 | 10583 | 0.002778 | high | 62.816 | 119.446 | 744.10178 | 89596.529 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / GHI MONTHLY ACCUM | EMI01 | GHI Monthly Acummulation | irradiance_accumulation | 567 | 567 | 0.277778 | high | 1261.9005 | 7435.1755 | 56626.6123 | 89596.529 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / GHI YEARLY ACCUM | EMI01 | GHI Yearly Acummulation | irradiance_accumulation | 566 | 566 | 0.277778 | high | 1263.751 | 7240.2982 | 56649.5424 | 89596.529 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / GLOBAL HORIZONTAL IRRADIANCE (GHI) | EMI01 | Global Horizontal Irradiance (GHI) | instantaneous_irradiance | 24182 | 24182 | 1 | high | 23.167 | 76.11 | 172.3964 | 89596.529 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / GLOBAL INCLINED IRRADIANCE (POA) | EMI01 | Global Inclined Irradiance (POA) | instantaneous_irradiance | 47555 | 47555 | 1 | high | 13.263 | 26.62 | 86.233 | 89596.529 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / IN-PLANE REAR-SIDE IRRADIANCE (RSI) 01 | EMI01 | In-Plane Rear-Side Irradiance (RSI) 01 | instantaneous_irradiance | 281 | 281 | — | unresolved | 15.4215 | 36470.1622 | 82380.4624 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / IN-PLANE REAR-SIDE IRRADIANCE (RSI) 02 | EMI01 | In-Plane Rear-Side Irradiance (RSI) 02 | instantaneous_irradiance | 281 | 281 | — | unresolved | 15.4215 | 36470.1622 | 82380.4624 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / IN-PLANE REAR-SIDE IRRADIANCE (RSI) 03 | EMI01 | In-Plane Rear-Side Irradiance (RSI) 03 | instantaneous_irradiance | 281 | 281 | — | unresolved | 15.4215 | 36470.1622 | 82380.4624 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / PEAK OF SUN HOURS | EMI01 | PEAK OF SUN HOURS | meteorological | 6921 | 6921 | 0.01 | high | 63.082 | 188.9351 | 4761.9207 | 89596.529 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / POA DAILY ACCUM | EMI01 | POA Daily Acummulation | irradiance_accumulation | 11388 | 11388 | 0.002778 | high | 62.769 | 66.456 | 496.12658 | 89596.529 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / POA MONTHLY ACCUM | EMI01 | POA Monthly Acummulation | irradiance_accumulation | 541 | 541 | 0.277778 | high | 1463.641 | 7527.8004 | 56228.1037 | 89596.529 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / POA YEARLY ACCUM | EMI01 | POA Yearly Acummulation | irradiance_accumulation | 542 | 542 | 0.277778 | high | 1426.375 | 7711.197 | 56197.1848 | 89596.529 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / PRESSURE | EMI01 | PRESSURE | meteorological | 281 | 281 | — | unresolved | 15.4215 | 36470.1622 | 82380.4624 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / PV MODUL TEMP 01 | EMI01 | PV MODUL TEMP 01 | meteorological | 29936 | 14968 | 0.1 | high | 79.688 | 350.0514 | 1517.19248 | 4979.533 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / PV MODUL TEMP 02 | EMI01 | PV MODUL TEMP 02 | meteorological | 14430 | 14430 | 0.1 | high | 79.578 | 344.9662 | 1719.26144 | 7986.768 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / PV MODUL TEMP 03 | EMI01 | PV MODUL TEMP 03 | meteorological | 14755 | 14755 | 0.1 | high | 79.671 | 340.2517 | 1581.27503 | 6349.653 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / RSI DAILY ACCUM 01 | EMI01 | RSI 01 Daily Acummulation | irradiance_accumulation | 281 | 281 | — | unresolved | 15.4215 | 36470.1622 | 82380.4624 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / RSI DAILY ACCUM 02 | EMI01 | RSI 02 Daily Acummulation | irradiance_accumulation | 281 | 281 | — | unresolved | 15.4215 | 36470.1622 | 82380.4624 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / RSI DAILY ACCUM 03 | EMI01 | RSI 03 Daily Acummulation | irradiance_accumulation | 281 | 281 | — | unresolved | 15.4215 | 36470.1622 | 82380.4624 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / RSI MONTHLY ACCUM 01 | EMI01 | RSI 01 Monthly Acummulation | irradiance_accumulation | 281 | 281 | — | unresolved | 15.4215 | 36470.1622 | 82380.4624 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / RSI MONTHLY ACCUM 02 | EMI01 | RSI 02 Monthly Acummulation | irradiance_accumulation | 281 | 281 | — | unresolved | 15.4215 | 36470.1622 | 82380.4624 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / RSI MONTHLY ACCUM 03 | EMI01 | RSI 03 Monthly Acummulation | irradiance_accumulation | 281 | 281 | — | unresolved | 15.4215 | 36470.1622 | 82380.4624 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / RSI YEARLY ACCUM 01 | EMI01 | RSI 01 Yearly Acummulation | irradiance_accumulation | 282 | 282 | — | unresolved | 15.467 | 36303.492 | 82293.5656 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / RSI YEARLY ACCUM 02 | EMI01 | RSI 02 Yearly Acummulation | irradiance_accumulation | 282 | 282 | — | unresolved | 15.467 | 36303.492 | 82293.5656 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / RSI YEARLY ACCUM 03 | EMI01 | RSI 03 Yearly Acummulation | irradiance_accumulation | 281 | 281 | — | unresolved | 15.4215 | 36470.1622 | 82380.4624 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / WIND DIRECTION | EMI01 | WIND DIRECTION | meteorological | 281 | 281 | — | unresolved | 15.4215 | 36470.1622 | 82380.4624 | 100641.923 | — | unresolved |
| PLTS IKN / STS09 / WB09_EMI01 / MEAS / WIND SPEED | EMI01 | WIND SPEED | meteorological | 296163 | 296163 | 0.1 | high | 6.576 | 9.951 | 33.165 | 6545.312 | — | unresolved |

## Artifact index

- `source_manifest.csv`
- `inventory_reconciliation.csv`
- `empty_csv_entries.csv`
- `row_exceptions.csv`
- `timestamp_audit.csv`
- `tag_characterisation.csv`
- `canonical_frequency_evidence.csv`
- `canonical_frequency_decision.json`
- `run_manifest.json`
- `figures/` (five approved diagnostic plots)
