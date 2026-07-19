# MASTER CONTEXT — Irradiance Forecasting System (PLTS)

**File:** `MASTER_CONTEXT_Forecasting_Irradiance_ML.md`
**Revision:** 1.3
**Status:** Normative. **This document is the single source of truth for implementation.**
**Companion:** `PRD_Forecasting_Irradiance_ML.md` (scope, priority, rationale, roadmap, audit)

> ## READ THIS FIRST — for every engineer and every AI coding agent
>
> 1. **Read this entire document before writing a single line of code.**
> 2. Where this document and the PRD disagree on an *implementation detail*, **this document wins.** Where they disagree on *scope or priority*, the PRD wins. Report the contradiction either way — do not silently pick one.
> 3. **Never invent site metadata.** If a value is marked `[TBC]`, it goes in config with a `TODO`, and the code raises at startup if it is unset. **Do not default it. Do not guess it. Do not "reasonably assume" it.**
> 4. Anything labelled **MUST** / **MUST NOT** is not advice. §16 lists the rules an agent is most likely to break, and §Appendix C lists the specific broken patterns from the source document that must never be reproduced.

---

## 1. Project Mission

Build a Python system that forecasts five on-site irradiance channels — **GHI, DHI, DNI·cos(Z), POA (front) and RSI (rear-side)** — across nowcast (5–120 min), intra-day (1–6 h) and day-ahead (up to 48 h) horizons; that emits every forecast as a deterministic P50 with a calibrated P10/P90 interval, full provenance, and an explicit data-quality state; that always has a working fallback and never fails silently; that is fully backtestable and auditable; and that **never promotes a model which has not beaten a dumb baseline on out-of-time data.** The system runs **without any sky camera, satellite dependency, or drone**, using only the site's own sensors, physics, time-series structure, and (from Phase 2) numerical weather prediction.

---

## 2. Canonical Project Facts

**These facts MUST NOT be changed without a formal decision recorded in this document's revision history.** Code, tests, documentation and diagrams must all be consistent with them.

| # | Fact | Status |
|---|---|---|
| CF-01 | The site has irradiance sensors for **GHI, DHI, DNI·cosZ, POA, RSI**. | `[C]` |
| CF-02 | **RSI = Rear-Side Irradiance** (W/m²). It is **not** a Rotating Shadowband Irradiometer, not reflected irradiance, not a reference-cell reading. | `[C]` |
| CF-03 | The site has **no drone**. | `[C]` |
| CF-04 | The site has **no sky-image camera, no all-sky imager, no ground-based cloud image sequence**. | `[C]` |
| CF-05 | The **MVP MUST NOT depend on computer vision** of any kind. No CNN image pipeline. No optical flow on images. | `[C]` |
| CF-06 | **Python** is the primary language. | `[C]` |
| CF-07 | Forecasts **MUST be multi-horizon**, and all three families (nowcast / intra-day / day-ahead) are in scope. | `[C]` |
| CF-08 | Every forecast **MUST be comparable against the actual** that later materialises, and that pairing must be auditable. | `[C]` |
| CF-09 | **Persistence MUST always be available** as both a baseline and a terminal fallback. It must never be able to fail. | `[C]` |
| CF-10 | Source data arrives as **change-of-value (COV) events**, not on a fixed clock. There is **no native timestep**. The canonical grid is something this system *defines*, not something it *receives*. | `[C]` |
| CF-11 | Satellite data is an **optional enhancement**, never an MVP dependency. | `[C]` |
| CF-12 | NWP is permitted and expected as an external input for intra-day and day-ahead. | `[C]` |
| CF-13 | The system is **read-only with respect to OT**. No code path writes to SCADA, PLC or any control system. The site adapter has **no write method**. | `[C]` |
| CF-14 | **No accuracy figure (nRMSE, RMSE, MAE, "% improvement") may be quoted, promised or written down until the Phase-1 site baseline is computed.** | `[C]` |

---

## 3. Known Unknowns

**Every item below is `[TBC]`. Every one MUST live in config, MUST have a `TODO`, and MUST cause a loud, explicit failure or warning at startup if it is required and unset.**

**An AI agent that fills any of these in with a plausible-looking default has broken the project.** A wrong latitude does not crash — it silently biases every solar-position calculation, every clear-sky value, every `k_c`, and therefore every forecast, forever.

| # | Unknown | Where it bites | Startup behaviour if unset |
|---|---|---|---|
| KU-01 | **Site latitude / longitude / altitude** | Solar geometry, clear-sky — i.e. everything | **RAISE.** Do **not** default to `(0, 0, 0)`. |
| KU-02 | **Site timezone** (WIB / WITA / WIT) | Timestamp interpretation, display, daylight filter | **RAISE.** Indonesia has no DST, but the UTC offset is not guessable. |
| KU-03 | **Racking type: fixed-tilt or single-axis tracker** | Transposition, rear-side model, POA sensor interpretation | **RAISE.** These are different physics. |
| KU-04 | **POA `surface_tilt` / `surface_azimuth`**; and whether the POA sensor is **co-planar with the modules** | Transposition; `r_poa` is meaningless if not co-planar | **RAISE.** |
| KU-05 | **RSI sensor mounting**: row, position within row, height, orientation | Rear-side physics; representativeness | **WARN** loudly; degrade RSI to black-box ML and flag it in the API `caveats`. |
| KU-06 | **Array geometry**: GCR, row pitch, module height above ground, bifaciality factor | `infinite_sheds` rear baseline | **WARN**; RSI physics baseline disabled. |
| KU-07 | **Albedo source** — is there an albedometer? | Rear-side physics | **WARN**; fall back to fitting an effective monthly albedo (§ADR-014). |
| KU-08 | **`dni_cosz`: measured, or derived as `GHI − DHI`?** | Whether the BSRN closure check is real or circular | **WARN**; run the residual test (PRD §16.3); record the answer in `sensor_metadata.is_derived_tag`. |
| KU-09 | **Sensor class** (ISO 9060 Class A/B/C, or silicon reference cell) | Uncertainty budget; closure tolerance | **WARN**; use conservative tolerances. |
| KU-10 | **Calibration dates and factors** | Drift detection; DQ state | **WARN**; DQ = `DEGRADED` if calibration status is unknown. |
| KU-11 | **COV deadband** and **max-report-time (heartbeat)** per tag | Honest resolution; staleness detection | **WARN**; measure from data (PRD §20.2a) and write the measured value into `sensor_metadata`. |
| KU-12 | **Historical coverage** — months? full wet + dry season? | Whether *any* generalisation claim is defensible | **WARN**; if <12 months, the evaluation report MUST state that no unseen-monsoon test was possible. |
| KU-13 | **Real-time data path and its latency** | Which horizons are operationally servable | **WARN**; set `served=false` on every horizon whose freshness budget cannot be met. |
| KU-14 | **NWP availability** (does the host have internet egress?) | Day-ahead viability | **WARN**; day-ahead degrades to climatology and the API says so. |
| KU-15 | **Deployment environment** and **data residency policy** | Hosting choice | **WARN**; do not assume cloud is permitted. |
| KU-16 | **Wind speed / direction availability**, mounting height, direction convention | The only advection proxy available | **WARN**; wind features disabled. |
| KU-17 | **Ambient temperature in scope as a target?** | Whether `temp_amb` is a target or only a feature | **Default: NOT a target** (per the brief). Recorded as PRD OD-2. |

---

## 4. Terminology

**These definitions are binding.** Where the source document contradicts them, the source document is wrong (see PRD Appendix A, Finding A-7).

| Term | Definition |
|---|---|
| **Observation time** | The instant a physical quantity was measured. In a COV stream, the `event_time` reported with the value. |
| **Forecast issuance time** (`issuance_time`) | The instant at which the forecast was *made*. **Only data available at or before this instant may be used.** |
| **Forecast valid time** (`valid_time`) | The instant the forecast is *about*. |
| **Lead time** / **Horizon** (`horizon_minutes`) | `valid_time − issuance_time`, in minutes. Used interchangeably in this project; `horizon` is the column name. |
| **GHI** | Global Horizontal Irradiance [W/m²] — total shortwave flux on a horizontal plane. |
| **DHI** | Diffuse Horizontal Irradiance [W/m²] — the scattered (non-beam) part of GHI. |
| **DNI** | Direct Normal Irradiance [W/m²] — beam flux on a plane normal to the sun. |
| **DNI·cosZ** (`dni_cosz`) | The beam component **projected onto the horizontal** [W/m²]; also called BHI. Related by `GHI = DHI + DNI·cosZ`. **Whether the site's channel is measured or derived is KU-08.** |
| **POA** | Plane-of-Array irradiance on the **front** of the modules [W/m²]. |
| **RSI** | **Rear-Side Irradiance** [W/m²] — irradiance on the **back** of the (bifacial) modules, as read by **one sensor at one position**. **Not** the array-average rear irradiance. |
| **Clear-sky irradiance** (`GHI_cs`) | Modelled irradiance under a cloud-free sky, for this site's geometry and atmosphere. |
| **Clear-sky index** (**`k_c`**) | `GHI / GHI_cs`. **This is the primary modelling target.** Range ≈ `[0, 1.5]`. **Values > 1 are physically valid** (cloud enhancement) and MUST NOT be clipped to 1. |
| **Clearness index** (**`k_t`**) | `GHI / GHI_extraterrestrial_horizontal`. **A different quantity.** Secondary feature only. **Do not conflate `k_c` and `k_t`.** |
| **Diffuse fraction** (**`k_d`**) | `DHI / GHI`. Range `[0, 1]`. A modelling primitive. |
| **Rear ratio** (**`ρ`**) | `RSI / POA_front`. A modelling primitive (§ADR-014). |
| **POA ratio** (**`r_poa`**) | `POA_measured / POA_physics`. A modelling primitive (§ADR-011). |
| **P10 / P50 / P90** | The 10th / 50th / 90th percentiles of the predictive distribution. **P50 is the median, not the mean, and not a guarantee.** Ordering `P10 ≤ P50 ≤ P90` is enforced. |
| **Persistence** | `ŷ(t+h) = y(t)`. The last observed value, held. |
| **Smart persistence** | `k̂_c(t+h) = k_c(t)` → `ŷ(t+h) = k̂_c · GHI_cs(t+h)`. **The default benchmark for irradiance.** |
| **Damped / optimal persistence** | `k̂_c(t+h) = α(h)·k_c(t) + (1−α(h))·k̄_c`, with `α(h)` fitted per horizon. Degrades gracefully into climatology as `h` grows. |
| **CH-PeEn** | Complete-History Persistence Ensemble — the **probabilistic** baseline: empirical quantiles of the historical `k_c` distribution conditioned on lead time. |
| **MOS** | Model Output Statistics — statistical correction of NWP output using the site's historical (forecast, actual) pairs. |
| **Data drift** | A change in the *input* distribution. |
| **Model drift** | A change in *forecast skill*. **Not the same thing.** Either can occur without the other. |
| **Fallback** | A lower-tier forecast produced when the preferred path is unavailable. **Always labelled, never silent, always with its own (wider) uncertainty band.** |
| **COV** | Change-of-Value. An event-driven data stream in which a value is reported only when it changes by more than a **deadband**. **A COV stream is an event log describing a time series, not a time series.** |
| **Deadband** | The minimum change that triggers a COV report. **Sets the floor on reconstruction accuracy.** |
| **Canonical grid** | The fixed-frequency timestamp index this system *defines* and resamples the COV stream onto. Governed by `canonical_freq`. |
| **Verification lag** | For horizon `h`, the actual for a forecast issued at `T` is only known at `T + h`. **Any adaptive weighting or online learning must respect this.** |
| **Weather regime** | One of `CLEAR`, `MOSTLY_CLEAR`, `PARTLY_CLOUDY`, `OVERCAST`, `HIGHLY_VARIABLE`, `RAIN_DEGRADED`, `UNKNOWN`. |
| **Servable** | A horizon is *servable* if the end-to-end data-freshness budget for it can actually be met. Non-servable horizons are backtest-only and are marked `served=false`. |

---

## 5. Architecture Decisions (ADRs)

### ADR-001 — Sensor-first architecture
- **Decision:** On-site sensors are the primary information source. NWP and (later) satellite are **augmentations**, never prerequisites.
- **Status:** Accepted.
- **Context:** The site owns high-quality, high-frequency, co-located irradiance measurements. It does not own imagery, and its internet access is unconfirmed (KU-14).
- **Rationale:** The system must produce value on day one, offline, from what exists.
- **Consequences:** Nowcasting relies on temporal structure, physics, and wind — not spatial cloud observation. Day-ahead is weak until NWP lands. **Both facts are stated to stakeholders rather than engineered around.**

### ADR-002 — No image dependency
- **Decision:** No component of the MVP may require a sky camera, all-sky imager, drone, or ground cloud-image sequence. No CNN image pipeline. No optical flow on images.
- **Status:** Accepted. **Binding (CF-05).**
- **Context:** The hardware does not exist at this site.
- **Rationale:** An architecture that cannot run is not an architecture.
- **Consequences:** **Point-forecast skill at 5–30 min under convective conditions is physically capped.** This is a property of the world, not a defect of the code. The response is to (a) invest in *uncertainty calibration* rather than chasing point accuracy, and (b) keep satellite (§ADR-018) as a clearly-scoped optional recovery path.

### ADR-003 — Horizon-specific models
- **Decision:** One model per `(target, horizon, quantile)`. No single model spans all horizons.
- **Status:** Accepted.
- **Context:** The information that predicts 5 minutes ahead (autocorrelation) is not the information that predicts 24 hours ahead (NWP + climatology).
- **Rationale:** Different horizons are different problems. Forcing one model to cover them makes it mediocre at all of them, and makes its failures unattributable.
- **Consequences:** ~144 small models. This is **fine** — each trains in seconds, they parallelise, each is independently debuggable, and each can fall back independently. The alternative is one large model whose failure mode is "everything is wrong at once".

### ADR-004 — Clear-sky-normalised targets
- **Decision:** Model in `k_c` space, not raw W/m². Reconstruct with `GHI = k_c × GHI_cs`.
- **Status:** Accepted.
- **Context:** Raw irradiance is dominated by a deterministic diurnal/seasonal signal the model would waste capacity re-learning.
- **Rationale:** `k_c` isolates the stochastic (atmospheric) part. It generalises across seasons far better.
- **Consequences:**
  - **The clear-sky model is now on the critical path.** A biased `GHI_cs` injects a systematic, seasonally-varying bias into every forecast. It MUST be validated against detected on-site clear-sky periods (§ADR-004a below).
  - `k_c` is undefined at twilight. **Set it to `NaN` where `GHI_cs < k_c_valid_min`. Do not divide by a clipped floor.** (PRD Appendix A, Finding A-7.)
  - **`k_c > 1` is valid. Do not clip to 1.0.** Guard only at `k_c_max = 1.5`.

### ADR-004a — Clear-sky model must be validated, not assumed
- **Decision:** Pin the clear-sky model in config. Detect on-site clear-sky periods (`pvlib.clearsky.detect_clearsky`). Compare measured GHI to modelled `GHI_cs` **on those periods only**. Fit and apply a site correction factor if the residual is material. Monitor it continuously.
- **Status:** Accepted.
- **Context:** Dry-season biomass-burning haze in Kalimantan/Sumatra pushes real aerosol optical depth far above the monthly Linke-turbidity climatology that `pvlib`'s default Ineichen model uses.
- **Rationale:** Under haze, the default model **over-predicts** clear-sky GHI → `k_c` reads artificially low → the model "sees" cloud where there is only smoke. Seasonal, systematic, and invisible unless you look for it.
- **Consequences:** CAMS **McClear** (real-time aerosol) is preferred where internet allows, with Ineichen as the offline fallback. **The divergence between the two is itself a useful haze detector.**

### ADR-005 — Temporal splits only
- **Decision:** Chronological holdout, rolling-origin, walk-forward. **No random split, anywhere, ever.**
- **Status:** Accepted. **Enforced by test.**
- **Context:** Time-series data with strong autocorrelation.
- **Rationale:** A random split places samples from the same cloud event on both sides of the split. The resulting score is a fantasy.
- **Consequences:** **The test set must include an unseen *monsoon phase*, not merely unseen calendar months.** Near the equator, day length barely varies; what varies is the wet/dry cloud regime. Design the split against the observed regime distribution, not the Gregorian calendar.

### ADR-006 — Baseline-first development
- **Decision:** Every Tier-0 baseline (B0–B7) is implemented, backtested, and reported **before** any ML model is trained — and alongside **every** ML result thereafter.
- **Status:** Accepted.
- **Rationale:** At 5–15 minutes, smart persistence is very hard to beat. A team that has not implemented it does not know whether its ML model is good; it only knows the model produced a number.
- **Consequences:** **"The candidate did not beat the baseline" is a valid, reportable, successful outcome.** It must be published, not buried.

### ADR-007 — Probabilistic output is mandatory
- **Decision:** Every forecast carries P10/P50/P90. Ordering is enforced. Coverage is evaluated **per weather regime**, not only marginally.
- **Status:** Accepted.
- **Context:** Without imagery, point accuracy at short horizons is capped (ADR-002). **Honest uncertainty is the product's most defensible value.**
- **Rationale:** A dispatch engineer can act on "P10 = 200 W/m², P90 = 900 W/m²". They cannot act safely on a confident point forecast that is wrong.
- **Consequences:**
  - Compute **more quantiles internally** (9 deciles) than are exposed, so a real CRPS is available.
  - **Marginal coverage is not enough.** Intervals that are too narrow on cloudy days and too wide on clear days can produce perfect marginal coverage — and be useless. **Report conditional coverage per regime.**
  - A probabilistic **baseline** (CH-PeEn) is mandatory, or "our quantiles are calibrated" is unfalsifiable.

### ADR-008 — Physical reconciliation by construction, not by correction
- **Decision:** Forecast **primitives**; **derive** the remaining targets from them (see ADR-011). The closure `GHI = DHI + DNI·cosZ` then holds **identically**.
- **Status:** Accepted.
- **Rationale:** Forecasting five channels independently and then "reconciling" them afterwards is patching a problem you created. Structuring the targets so the constraint cannot be violated is strictly better.
- **Consequences:** The reconciliation step becomes an **assertion in a test**, not a runtime correction. A violation is a *code bug*, and is logged as one.

### ADR-009 — Human-gated model promotion
- **Decision:** No model reaches production without (a) passing the acceptance gate, **and** (b) a recorded human approval. **There is no automatic promotion path in this system.**
- **Status:** Accepted.
- **Rationale:** This forecast feeds BESS dispatch decisions. An automatically-promoted model with a subtle regression on convective days is an operational hazard.
- **Consequences:** Retraining can be automatic; **promotion cannot.** The audit trail records who approved what, when, and why.

### ADR-010 — Locally-deployable MVP
- **Decision:** The MVP runs on a single on-premise server under Docker Compose, with Parquet on disk. No cloud dependency on the core path.
- **Status:** Accepted.
- **Context:** OT/IT segmentation; unresolved data residency (KU-15); ~0.5M rows/channel/year is small.
- **Rationale:** Every production component must be justified by a **specific, observed** MVP limitation — not by popularity.
- **Consequences:** No Kubernetes, no TimescaleDB, no Airflow, no Redis in the MVP. Each is added later **only** when a named bottleneck is measured, and the ADR that adds it must name that bottleneck.

---

### ADR-011 — Primitive decomposition (the core modelling decision)

- **Decision:** Forecast **four primitives** and derive the five targets:

  ```
  PRIMITIVES (forecast these)            DERIVED (compute these)
  ───────────────────────────            ────────────────────────
  k_c   = GHI / GHI_cs          ──┐
                                   ├──►  GHI      = k_c × GHI_cs
  k_d   = DHI / GHI              ──┤     DHI      = k_d × GHI
                                   └──►  DNI·cosZ = GHI − DHI     ← closure by construction
                                         DNI      = (GHI − DHI) / cos(θz)   [guard θz → 90°]

  r_poa = POA_meas / POA_physics ──►     POA      = r_poa × Perez(GHI, DHI, DNI, geometry)

  ρ     = RSI / POA_front        ──►     RSI      = ρ × POA
  ```

- **Status:** Accepted.
- **Rationale:**
  1. Physical consistency is **structural**, not patched (ADR-008).
  2. Each primitive is bounded and well-conditioned: `k_c ∈ [0, 1.5]`, `k_d ∈ [0, 1]`, `ρ` and `r_poa` are slowly-varying ratios.
  3. Errors become **attributable**: a bad POA is either a bad GHI forecast *or* a bad transposition, and `r_poa` separates them.
- **Consequences — stated honestly:**
  - Errors **couple**: a `k_c` error propagates to every derived target.
  - **Quantiles do not compose** (`P90(GHI) × P90(k_d) ≠ P90(DHI)`). This is handled by ADR-015, and it is not optional.
  - **Mitigation:** an independent **direct-forecast** path per target is retained as a comparator. If the direct path wins on a given `(target, horizon)`, the ensemble uses it. **Physics earns its place; it is not granted it.**

### ADR-012 — COV-aware canonical grid with time-weighted reconstruction

- **Decision:**
  1. Bronze stores COV events **exactly as received**, immutably.
  2. Silver resamples to a **canonical grid** using **zero-order-hold (step) time-weighted averaging** by default; trapezoidal is available per-tag via config.
  3. `canonical_freq` is **chosen from measured COV inter-arrival statistics**, not assumed.
  4. Every canonical interval carries `n_cov_samples`, `max_gap_s`, and `last_valid_age_s` as first-class columns.
- **Status:** Accepted. **This is the highest-risk area of the codebase.**
- **Context:** CF-10. There is no native timestep.
- **Rationale:**
  - **`df.resample('1min').mean()` on raw COV records is WRONG.** COV emits samples preferentially when the signal is *changing*, so a plain mean **over-weights transitions** and produces a biased interval mean. It biases hardest during exactly the ramp events the product exists to forecast.
  - The **deadband bounds the reconstruction error** regardless of method. If the deadband is 15 W/m², a 1-minute grid is a comfortable fiction and must not be claimed.
  - ZOH matches COV *semantics* ("the value is within ±deadband of the last report"). Historians such as PI expose a per-tag `step` attribute for exactly this reason — **read it**.
- **Consequences:**
  - Phase 0 MUST produce `docs/phase0_cov_characterisation.md`: per tag, the deadband (recovered from the floor of the `|Δvalue|` distribution), inter-arrival p50/p90/p99, max gap, and a **justified** `canonical_freq`.
  - **Silence is ambiguous.** "No new value" can mean *nothing changed* or *the link died*. Resolve with a heartbeat/max-report-time **and** a cross-channel liveness check (if GHI reported 30 s ago but DHI has been silent for 20 min while `GHI_cs > 200 W/m²`, DHI is **dead**, not quiet).
  - Property tests (hypothesis) MUST assert both that the reconstruction is within ~deadband of truth **and** that a naive `.mean()` is demonstrably worse. If the second assertion does not hold, the resampler is decoration.

### ADR-013 — ECMWF Open Data as primary NWP; archive from day zero

- **Decision:**
  1. **ECMWF Open Data (IFS HRES + AIFS)** is the primary NWP source.
  2. **The NWP archiver starts in Phase 0** — before any modelling, before anything consumes it.
  3. `issue_time`, `valid_time` and `retrieved_at` are **three separate columns**. Never collapse them.
- **Status:** Accepted. **Time-critical.**
- **Context:**
  - ECMWF Open Data is **CC-BY-4.0 — commercial use permitted with attribution**. Free aggregator APIs typically are **not** licensed for commercial use; a utility-scale PLTS is a commercial operation. **Verify the licence of every other source before production.**
  - **ECMWF Open Data keeps only a rolling archive of ~12 forecast runs (≈2–3 days).**
- **Rationale:** Training an NWP→site MOS requires **months** of matched (forecast, actual) pairs. **Those pairs cannot be obtained retroactively.** Every week the archiver is not running is a week of training data lost **permanently**. The archiver costs a cron job and a disk.
- **Consequences:**
  - Practical notes for the implementer:
    - `ssrd` (surface solar radiation downwards) **is** in the free subset. **`fdir` (direct radiation) is NOT.** DNI/DHI must therefore be derived from the forecast GHI via a **separation model** (Erbs / DISC / DIRINT / Engerer2).
    - `ssrd` is **accumulated, in J/m²**. Convert to a mean flux over the step, and record the conversion.
    - IFS open-data steps are **3-hourly**; under IFS Cycle 50r1 the 00/12 UTC runs extend to +144 h, while the 06/18 UTC runs extend to +90 h. The archive request inventory must therefore be selected from the actual issue cycle. **Do NOT linearly interpolate W/m² across a 3-hour gap** — it flattens the diurnal curve. Interpolate the **clear-sky index**, then multiply by the high-resolution clear-sky curve.
    - **AIFS** additionally offers `lcc` / `mcc` / `hcc` (low/mid/high cloud) and `cp` (convective precipitation) — **more useful for solar** than IFS's single `tcc`. Ingest both.
    - `mucape` (most-unstable CAPE) is available and is a genuinely useful convective-risk feature for Indonesia.
  - **Never train a MOS on ERA5 reanalysis and deploy it on forecasts.** Reanalysis has assimilated the observations it is being scored against; the resulting MOS coefficients will not transfer. ERA5 is for climatology and non-forecast backfill only.

### ADR-014 — RSI: forecast the rear ratio; declare the representativeness limit

- **Decision:**
  1. The RSI modelling target is the **rear ratio `ρ = RSI / POA_front`**, not raw RSI. Reconstruct `RSI = ρ × POA_forecast`.
  2. The RSI Tier-0 baseline is a **physics-informed linear regression**: `RSI ≈ a·GHI + b·DHI + c·POA + d`, fitted per month or as a smooth function of solar geometry. **Fit this before touching a neural network.**
  3. The RSI physics baseline is **`pvlib.bifacial.infinite_sheds.get_irradiance()`**, with `shade_factor` **fitted to the site** rather than left at its default.
  4. If no albedometer exists, **fit an effective monthly albedo by inverting the physics model against measured RSI on clear-sky periods.**
  5. **Every RSI forecast, in the API and on the dashboard, carries the caveat `rsi_single_point_sensor_not_array_representative`.**
- **Status:** Accepted.
- **Rationale:**
  - `ρ` strips out the fast, cloud-driven variability (already handled by the POA forecast) and leaves a slow signal driven by geometry, season and ground condition.
  - **Honest caveat:** `ρ` is *not* constant. Under cloud, POA_front collapses faster than the ground-reflected component, so `ρ` **rises**. It is still far more learnable than raw RSI — but **validate this on real data in Phase 1 before committing.** If `ρ` proves as noisy as RSI itself, fall back to direct RSI forecasting **and say so in the report.**
  - Albedo in Indonesia swings with rainfall (wet vegetation/soil ≈ 0.15–0.20; dry ≈ 0.20–0.25; standing water is near-specular and breaks the isotropic assumption outright). **A single fixed albedo is a modelling error, not a simplification.**
- **Consequences:**
  - **Rear irradiance across a real bifacial array is strongly non-uniform** — edge vs centre rows, module top vs bottom, torque-tube shadows. **A single rear sensor is not an unbiased estimate of the array average.** This system forecasts **the sensor**. Using that as a proxy for array-average bifacial gain requires a separate spatial-calibration study, which is **out of scope**. Downstream consumers are told this **in the payload**, not left to discover it.
  - **Dependency note:** if the full 2-D `pvfactors` model is wanted, install it as **`solarfactors`** (`pip install solarfactors`) — the pvlib community's maintained drop-in; the original package became difficult to install in modern Python environments, and pvlib has routed through it since v0.10.1. The **import name remains `pvfactors`**. `infinite_sheds` is native to pvlib, faster, and dependency-free — **start there**.

### ADR-015 — Monte-Carlo propagation for coherent quantiles

- **Decision:** Do **not** compute quantiles independently per derived target. Instead:
  1. Sample from the **joint** predictive distribution of the primitives (`k_c`, `k_d`, `r_poa`, `ρ`) — via an empirical residual copula, or (simpler and effective) by **block-bootstrapping historical joint residual vectors**, which preserves the cross-target dependence for free.
  2. Push each sample through the **deterministic** reconstruction of ADR-011.
  3. Take **empirical quantiles of the reconstructed samples.**
- **Status:** Accepted.
- **Rationale:** `P90(GHI) × P90(k_d) ≠ P90(DHI)`. **Quantiles do not survive a nonlinear reconstruction.** Fitting each target's quantiles independently yields intervals that are neither individually calibrated nor mutually consistent.
- **Consequences:** The output is P10/P50/P90 for all five targets that are **individually calibrated *and* physically coherent**. Slightly more compute; a correct answer instead of a plausible-looking wrong one.

### ADR-016 — The fallback chain is normative and always terminates

- **Decision:** The chain below is the **only** fallback order. Every step down MUST set `fallback_used=true`, record `fallback_reason`, lower `confidence`, and **widen the P10–P90 band to the empirically-measured error distribution of *that fallback***.

  ```
  1. Ensemble                        [all members healthy]
  2. Best single ML model for this (target, horizon)
  3. NWP-MOS                         [if NWP fresh]
  4. Two-state model (B6)            [if sensors fresh]
  5. Optimal/damped persistence (B2) [if last valid obs within max_persist_age]
  6. Smart persistence (B1)
  7. Diurnal climatology (B3)        ← ALWAYS AVAILABLE. Needs nothing but a clock.
  ```

- **Status:** Accepted. **Verified by the chaos suite.**
- **Rationale:** The chain **must terminate in something that cannot fail.** Climatology needs only the site coordinates and the current time.
- **Consequences:** **Reporting the model's uncertainty while serving the fallback's forecast is lying about uncertainty.** Each fallback carries its own, wider, measured band. **The API never returns a stale `200`.**

### ADR-017 — Inverse-error ensemble weights for the MVP; verification lag is binding

- **Decision:**
  1. MVP ensemble weights are **inverse-error weights** from rolling validation. No fitted meta-model.
  2. If fitted stacking is later adopted, it MUST solve the **constrained** problem — `minimise ‖Xw − y‖²  s.t.  w ≥ 0, Σw = 1`, **no intercept** — and the object that predicts MUST be the object that was fitted.
  3. **Verification lag is binding.** For horizon `h`, a weight update at time `T` may only use forecasts issued **at or before `T − h`**. Unit-tested.
- **Status:** Accepted.
- **Rationale:** The source document's ensemble fits a `Ridge` **with an intercept**, discards the intercept, and renormalises the coefficients to sum to 1 — so the predicting object is **not** the fitted object (PRD Appendix A, Finding A-4). Inverse-error weighting has no intercept, no leakage surface, no bug, and is competitive on this class of problem.
- **Consequences:** Weights differ **per horizon** and **per regime**. Weights are logged with every forecast run (`ensemble_weights_json`).

### ADR-018 — Deferred optional enhancements: satellite, and array-as-sensor-network

- **Decision:** Both are **explicitly deferred to Phase 3**, each with its own business case and its own decision. Neither is an MVP dependency. Neither is silently dropped.
- **Status:** Proposed — **awaiting a decision** (PRD OD-6, OD-7).
- **Context:**
  - **Satellite (Himawari-9).** Indonesia sits under a geostationary satellite at 140.7°E delivering a **full-disk scan every 10 minutes** at 0.5–2 km, free via JAXA P-Tree and NOAA/AWS mirrors. **This is the only realistic path to recovering the 15–120 min skill that the missing sky camera costs us.** *Caveat:* aggregated APIs typically return **1-hourly** satellite radiation — far too coarse for nowcasting. Native 10-minute processing is required, and cloud-motion advection (Level 2) **is optical flow on images** — hence Phase 3, separately scoped, and **explicitly outside the MVP per CF-05.**
  - **Array-as-sensor-network.** A large PLTS has hundreds of spatially separated inverters. **DC power across them is a coarse, distributed irradiance field.** Cross-correlating inverter DC power with known inverter coordinates yields **cloud motion vectors — with no camera and no satellite.** This idea is absent from the source document and is the most interesting camera-free option available. Preconditions: inverter coordinates, sub-minute DC power, clean curtailment/clipping exclusion (**a clipped inverter is blind to irradiance — this is the main pitfall**), and a data path.
- **Consequences:** Recorded here so they are **decided, not forgotten**.

---

### ADR Revision Log

| ADR | Status | Date | Note |
|---|---|---|---|
| 001–018 | Accepted (018: Proposed) | — | Initial issue |

---

## 6. Data Contracts

**Canonical column names. These MUST NOT be changed without a schema migration and an entry in the revision log.**

### 6.1 Silver — `irradiance_canonical`

| Column | Type | Unit | Nullable | Note |
|---|---|---|---|---|
| `site_id` | `str` | — | No | PK |
| `timestamp_utc` | `datetime64[ns, UTC]` | — | No | PK. **Canonical grid. Always tz-aware. Always UTC.** |
| `ghi_wm2` | `float64` | W/m² | Yes | |
| `dhi_wm2` | `float64` | W/m² | Yes | |
| `dni_cosz_wm2` | `float64` | W/m² | Yes | **Verify measured vs derived (KU-08)** |
| `poa_wm2` | `float64` | W/m² | Yes | Front |
| `rsi_wm2` | `float64` | W/m² | Yes | **Rear-side. Single sensor.** |
| `temp_amb_c` | `float64` | °C | Yes | |
| `temp_mod_c` | `float64` | °C | Yes | |
| `rh_pct` | `float64` | % | Yes | |
| `wind_speed_ms` | `float64` | m/s | Yes | |
| `wind_dir_deg` | `float64` | ° | Yes | **Meteorological: the direction the wind blows FROM, clockwise from true north** |
| `rain_mm` | `float64` | mm | Yes | |
| `pressure_hpa` | `float64` | hPa | Yes | |
| `quality_flag` | `str` | — | No | Row-level roll-up |
| `qflag_<channel>` | `str` | — | No | Per channel: `GOOD` / `DEGRADED` / `BAD` / `MISSING` / `IMPUTED` |
| `n_cov_samples_<channel>` | `int32` | — | No | **COV provenance** |
| `max_gap_s_<channel>` | `float64` | s | No | **COV honesty metric** |
| `last_valid_age_s_<channel>` | `float64` | s | No | **Staleness** |
| `resample_method` | `str` | — | No | `zoh` / `trapezoid` |
| `source` | `str` | — | No | Lineage |
| `ingestion_time_utc` | `datetime64[ns, UTC]` | — | No | Lineage |

### 6.2 Derived primitives (Gold)

| Column | Unit | Definition | Valid range | Undefined when |
|---|---|---|---|---|
| `k_c` | — | `ghi_wm2 / ghi_cs_wm2` | `[0, 1.5]` | `ghi_cs_wm2 < k_c_valid_min` → **`NaN`** |
| `k_t` | — | `ghi_wm2 / ghi_extra_horizontal_wm2` | `[0, 1.0]` | `cos(θz) ≤ 0` → `NaN` |
| `k_d` | — | `dhi_wm2 / ghi_wm2` | `[0, 1]` | `ghi_wm2 < k_d_valid_min` → `NaN` |
| `r_poa` | — | `poa_wm2 / poa_physics_wm2` | `[0.5, 1.5]` | `poa_physics_wm2 < poa_valid_min` → `NaN` |
| `rho_rear` | — | `rsi_wm2 / poa_wm2` | `[0, 0.5]` `[A]` | `poa_wm2 < poa_valid_min` → `NaN` |
| `balance_residual_wm2` | W/m² | `ghi_wm2 − dhi_wm2 − dni_cosz_wm2` | — | any input `NaN` |

> **`NaN` is the correct value for "undefined".**
> **A large number is a lie. A zero is a different lie.** Do not clip a denominator to avoid a `NaN` — that is exactly the bug in the source document (PRD Appendix A, Finding A-7).

### 6.3 Forecast

See §11 (Forecast Contract).

### 6.4 Naming rules

- **Every physical column ends in its unit**: `_wm2`, `_c`, `_ms`, `_deg`, `_pct`, `_hpa`, `_mm`, `_s`, `_jkg`.
- **Every timestamp column ends in `_utc`** and is tz-aware.
- Dimensionless ratios carry no unit suffix (`k_c`, `k_d`, `rho_rear`, `r_poa`).
- **A unit change is a schema migration.** Not a patch. Not a quiet fix.

---

## 7. Unit Conventions

| Quantity | Unit | Notes |
|---|---|---|
| Irradiance | **W/m²** | Always. Never kW/m². Never J/m². |
| Irradiation (energy) | Wh/m² or kWh/m² | Only where explicitly needed downstream. State which. |
| Temperature | **°C** | Never K, never °F. |
| Wind speed | **m/s** | Never km/h, never knots. |
| Wind direction | **degrees, meteorological** | **The direction the wind blows FROM**, clockwise from true north. `0°` = from the north. `90°` = from the east. |
| Angles (solar) | degrees | pvlib convention |
| Pressure | hPa | |
| Precipitation | mm | |
| CAPE | J/kg | |
| **Timestamp storage** | **UTC, tz-aware** | **Non-negotiable.** A naive timestamp entering the system MUST raise, not be assumed. |
| **Timestamp display** | Site timezone | From config (KU-02). Indonesia has **no DST**. |

### 7.1 Unit-conversion traps that MUST be handled explicitly

| Trap | Handling |
|---|---|
| **ECMWF `ssrd` is accumulated, in J/m²** | Convert to a mean flux over the accumulation step: `W/m² = ΔJ/m² / Δt_seconds`. **Record the conversion in the column name and in a test.** |
| **`ssrd` is a *cumulative* field** | The value at step `t` is the accumulation since the run start. **Difference consecutive steps** before converting. Getting this wrong produces a monotonically increasing "irradiance" — which is obviously wrong, and which people ship anyway. |
| **Wind u/v** | See §8.3. The source document's formula is wrong. |
| **Solar azimuth near the zenith** | Near the equator, azimuth swings rapidly as `θz → 0`. **Use `sin`/`cos` of azimuth, never raw degrees.** Never differentiate azimuth. |

---

## 8. Data Leakage Rules

**Every rule below is enforced by an automated test. A violation fails the build.**

### 8.1 Absolute prohibitions

| # | Rule |
|---|---|
| L-01 | **No random split.** No `KFold`, no `train_test_split`, no shuffling. Temporal splitters only. |
| L-02 | **No future interpolation.** Imputation at inference is **backward-fill only**. |
| L-03 | **No future rolling windows.** No centred windows. `closed='left'` semantics; the label's own timestamp is excluded from its features. |
| L-04 | **No revised NWP.** Only NWP runs with `issue_time + measured_dissemination_latency ≤ issuance_time`. **Latency is measured from `retrieved_at_utc`, not assumed.** |
| L-05 | **No scaler/encoder fit on validation or test.** Fit on train only. |
| L-06 | **No target-derived feature from the future.** |
| L-07 | **No post-event label leakage.** A maintenance annotation entered *after* an event MUST NOT become a feature available *during* it. |
| L-08 | **No `np.roll` in a baseline.** It wraps: the end of the array becomes the start. **This is future data inside the baseline** — and a leak in the baseline flatters the model just as effectively as a leak in the model. Use `.shift()`. |
| L-09 | **No adaptive weight update that violates the verification lag.** At time `T`, for horizon `h`, use only forecasts issued at or before `T − h`. |

### 8.2 The canonical leakage test — implement this **before** implementing features

```python
def test_no_future_leakage(feature_fn, df, cutoff):
    """
    Feed the feature builder a dataframe in which EVERYTHING after `cutoff`
    is NaN. Every feature value at or before `cutoff` must be identical to
    the value produced from the full dataframe.

    If any feature changes, it is reading the future. Fail the build.

    This single test catches: centred rolling windows, bfill/interpolate
    across the boundary, scalers fit on the full series, and target-derived
    features. It is the cheapest high-value test in the entire repository.

    WRITE THIS TEST FIRST. Then write the features.
    """
    full = feature_fn(df)

    truncated = df.copy()
    truncated.loc[truncated.index > cutoff, :] = np.nan
    partial = feature_fn(truncated)

    pd.testing.assert_frame_equal(
        full.loc[full.index <= cutoff],
        partial.loc[partial.index <= cutoff],
        check_exact=False,
        rtol=1e-9,
    )
```

### 8.3 The wind u/v conversion — CORRECT version

```python
import numpy as np

def wind_uv(wind_speed_ms: np.ndarray, wind_dir_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Meteorological convention:
        wind_dir_deg = the direction the wind blows FROM,
                       measured CLOCKWISE from TRUE NORTH.

    Returns (u, v) = (eastward, northward) components.

    Reference cases (these are the unit test):
        10 m/s FROM north (000 deg)  ->  u =   0.0,  v = -10.0
        10 m/s FROM east  (090 deg)  ->  u = -10.0,  v =   0.0
        10 m/s FROM south (180 deg)  ->  u =   0.0,  v = +10.0
        10 m/s FROM west  (270 deg)  ->  u = +10.0,  v =   0.0
    """
    rad = np.deg2rad(wind_dir_deg)
    u = -wind_speed_ms * np.sin(rad)   # eastward
    v = -wind_speed_ms * np.cos(rad)   # northward
    return u, v
```

> **DO NOT** use `u = ws*cos(dir)`, `v = ws*sin(dir)`. That is the formula in the source document, and it is wrong in **both the axis convention and the sign** — a 90° rotation *and* a reflection. It does not crash. It does not look wrong. It silently makes every wind-advection feature meaningless. (PRD Appendix A, Finding A-2.)

---

## 9. Model Contracts

Every model — **including every baseline** — MUST implement this interface. No exceptions, and no special cases for "it's just persistence".

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ModelMetadata:
    model_name: str
    model_version: str
    tier: int                       # 0 = baseline, 1 = tabular, 2 = sequence, 3 = multi-horizon, 4 = ensemble
    target: str                     # a PRIMITIVE: 'k_c' | 'k_d' | 'r_poa' | 'rho_rear'
    horizon_minutes: int
    quantile: float | None          # None => deterministic
    feature_schema: list[str]       # exact ordered column names
    target_schema: str
    training_period_start: datetime
    training_period_end: datetime
    dataset_version: str
    code_sha: str
    config_hash: str
    hyperparams: dict
    artifact_sha256: str


class ForecastModel(ABC):
    """
    Contract for every model in the system, baselines included.

    INVARIANTS
    ----------
    * predict() MUST be a pure function of (features, metadata). No hidden state,
      no reading from disk, no wall-clock lookups.
    * predict() MUST NOT read any column outside `metadata.feature_schema`.
    * The feature columns MUST arrive in the exact order given by feature_schema;
      the implementation MUST assert this rather than silently reindexing.
    * save()/load() MUST round-trip exactly: load(save(m)).predict(X) == m.predict(X).
    """

    metadata: ModelMetadata

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series, sample_weight: np.ndarray | None = None) -> "ForecastModel":
        ...

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Deterministic / median prediction, in PRIMITIVE space."""
        ...

    def predict_quantiles(self, X: pd.DataFrame, quantiles: list[float]) -> pd.DataFrame:
        """
        Probabilistic prediction, in PRIMITIVE space.
        Columns are named 'q10', 'q50', 'q90', ...
        MUST guarantee monotonicity across quantiles.
        Raise NotImplementedError if the model is deterministic-only.
        """
        raise NotImplementedError

    @abstractmethod
    def save(self, path: Path) -> str:
        """Persist the artifact. RETURNS the sha256 of the written file."""
        ...

    @classmethod
    @abstractmethod
    def load(cls, path: Path, expected_sha256: str) -> "ForecastModel":
        """
        Load an artifact.
        MUST verify the sha256 and RAISE on mismatch — never load a
        checksum-mismatched artifact (this triggers the fallback chain).
        """
        ...
```

### 9.1 Baseline contract

Baselines implement the **same** interface. They are first-class models, not helper functions.

| ID | Class | Notes |
|---|---|---|
| B0 | `NaivePersistence` | `ŷ(t+h) = y(t)`. `fit()` is a no-op. |
| B1 | `SmartPersistence` | `k̂_c(t+h) = k_c(t)`. **The headline benchmark.** |
| B2 | `DampedPersistence` | `k̂_c(t+h) = α(h)·k_c(t) + (1−α(h))·k̄_c`. `fit()` estimates `α(h)`. **The baseline most ML models quietly fail to beat.** |
| B3 | `DiurnalClimatology` | Mean `k_c` by (month × elevation bin). **Must never fail** — it is the terminal fallback (ADR-016). |
| B4 | `ClearSkyBaseline` | `k_c ≡ 1`. |
| B5 | `NWPRaw` | Interpolated `ssrd`, uncorrected. Phase 2. |
| B6 | `TwoStateModel` | Clear-sky × binary sunshine state, atmospheric parameter updated online. **Physics-informed, camera-free, adaptive.** Phase 1. |
| B7 | `CHPeEn` | **Probabilistic baseline.** Empirical `k_c` quantiles by lead time. Implements `predict_quantiles`. |

---

## 10. Evaluation Contract

**Every experiment MUST report every field below. An experiment missing any of them is not a result; it is an anecdote.**

| Field | Requirement |
|---|---|
| `target` | Which of the five, **and** which primitive it was forecast in |
| `horizon_minutes` | Per horizon. **Never aggregate across horizons in a headline.** |
| `test_period_start` / `_end` | Explicit dates. Out-of-time. |
| `split_strategy` | Named temporal splitter. **A random split fails the build.** |
| `monsoon_phase_coverage` | Does the test set include an unseen wet **and** dry phase? **If not, say so explicitly** and do not claim generalisation. |
| `baseline_name` / `baseline_value` | **At minimum: B0 *and* B1.** The headline skill is **vs B1 (smart persistence)**. |
| `skill_score` | `1 − metric_model / metric_baseline`. Positive = better. |
| `p_value` | **Diebold–Mariano** (or a block-bootstrap CI). **A skill score without a significance test is not evidence.** |
| `weather_regime` | Metrics **sliced by regime**. An aggregate hides exactly the failure that matters. |
| `daylight_filter` | Which filter was applied (`elev > X` or `GHI_cs > Y`). **Daylight-filtered is the DEFAULT.** |
| `all_hours_metrics` | Reported **separately**, never as the headline. |
| `nrmse_denominator` | **Explicitly stated.** Default: mean of daylight-filtered actuals over the test period. **This choice changes the number by a factor of 2–3.** |
| `n_samples` / `n_excluded` | How many rows scored, how many dropped, and why |
| `data_quality_exclusions` | Only `actual_qflag == GOOD` counts. `IMPUTED` actuals are **excluded from denominators** — scoring against an imputed actual measures the imputer, not the forecast. |
| `model_version` / `dataset_version` / `code_sha` / `config_hash` | Full provenance |
| **`failure_cells`** | **MANDATORY.** Every `(horizon, regime)` cell where the candidate **LOSES** to the baseline. A model that wins on average and loses on convective days is a hazard, not a win. |

### 10.1 Metric definitions (binding)

| Metric | Definition | Notes |
|---|---|---|
| MAE | `mean(|ŷ − y|)` | |
| RMSE | `sqrt(mean((ŷ − y)²))` | |
| MBE | `mean(ŷ − y)` | **Positive = over-forecast.** |
| nMAE | `MAE / denominator × 100` | Denominator from config |
| nRMSE | `RMSE / denominator × 100` | Denominator from config, **stated in the report** |
| **MAPE** | — | **FORBIDDEN on irradiance.** No denominator guard makes it meaningful near sunrise. |
| R² | — | **Secondary only.** Never a headline. |
| Skill score | `1 − RMSE_model / RMSE_baseline` | **Headline: vs B1.** |
| Pinball loss | Standard, per quantile | |
| **CRPS** | Computed from the **internal decile set** (ML-015), not a 3-point approximation | |
| Coverage | `P(y ∈ [P10, P90])` — target 0.80 | **Report per regime, not only marginally.** |
| Sharpness | `mean(P90 − P10)` | Meaningless without coverage. Report both. |
| PIT / reliability | Histogram / diagram | Per regime |
| Quantile-crossing rate | Fraction of rows repaired by post-processing | **A rising rate is a model-health signal.** |
| Ramp precision / recall / F1 | Event = `|Δk_c| > ramp_threshold` over the horizon | `k_c`-based, not W/m²-based — this removes the diurnal cycle |

---

## 11. Forecast Contract

**Every forecast row MUST carry every field below. A row missing any of them MUST be rejected at write time.**
**A forecast without provenance is not a forecast. It is a number of unknown origin, and it will eventually be trusted by someone who should not trust it.**

| Field | Type | Mandatory | Note |
|---|---|---|---|
| `site_id` | str | ✅ | |
| `target` | enum | ✅ | `ghi` \| `dhi` \| `dni_cosz` \| `poa` \| `rsi` |
| `issuance_time` | datetime UTC | ✅ | |
| `valid_time` | datetime UTC | ✅ | |
| `horizon_minutes` | int | ✅ | |
| `p10`, `p50`, `p90` | float | ✅ | **`P10 ≤ P50 ≤ P90` enforced** |
| `deterministic_forecast` | float | ✅ | |
| `unit` | literal | ✅ | Always `"W/m2"` |
| `model_name` | str | ✅ | |
| `model_version` | str | ✅ | |
| `dataset_version` | str | ✅ | |
| `fallback_used` | bool | ✅ | |
| `fallback_reason` | str \| null | ✅ | Non-null whenever `fallback_used` |
| `data_quality` | enum | ✅ | `GOOD`\|`DEGRADED`\|`BAD`\|`MISSING`\|`IMPUTED` |
| `confidence` | enum | ✅ | `HIGH`\|`MEDIUM`\|`LOW` |
| `source_data_freshness_seconds` | float | ✅ | |
| `weather_regime_at_issuance` | enum | ✅ | |
| `ramp_probability` | float \| null | — | If FR-027 is enabled |
| **`served`** | bool | ✅ | `false` ⇒ **backtest-only**, the data-path latency budget for this horizon is not met |
| **`caveats`** | list[str] | ✅ | **RSI ALWAYS carries `rsi_single_point_sensor_not_array_representative`** |

### 11.1 Immutability

A forecast row, once written, **is never updated**. A correction is a **new row** with a new `run_id`. The historical record of what the system believed, and when, is not editable.

---

## 12. Coding Standards

| # | Rule |
|---|---|
| C-01 | **Type hints everywhere.** `mypy --strict` on `physics/`, `features/`, `quality/` — the three modules where a silent unit error is most expensive. |
| C-02 | **Docstrings on every public function.** State units. State the convention. State what `NaN` means. |
| C-03 | **Configuration-driven.** See §13. |
| C-04 | **ZERO hard-coded site values.** No latitude. No tilt. No timestep. No threshold. A grep for numeric literals in `src/` should return only mathematical constants. |
| C-05 | **Structured logging** (JSON). Every fallback, every clip, every QC failure, every quantile repair is logged with enough context to reconstruct it. |
| C-06 | **Explicit exceptions.** No bare `except:`. No swallowing. A caught exception either recovers *and logs*, or re-raises. |
| C-07 | **A test ships with every feature.** Not after. With. |
| C-08 | **Deterministic seeds.** Set `random_state` / `seed` everywhere; record it in the metadata. |
| C-09 | **Deterministic artifacts** where practical. Same seed + same data ⇒ same `artifact_sha256`. |
| C-10 | **No production logic in notebooks.** Notebooks explore. `src/` decides. If a notebook cell matters, it moves to `src/` with a test. |
| C-11 | **The training and inference feature code MUST be literally the same function.** Not "the same logic". Not "a port". **The same function object.** This is the single most common source of train/serve skew, and it is entirely preventable. |
| C-12 | **`NaN` is a legitimate value.** Do not fill it to make a warning go away. Do not clip a denominator to avoid it. If a quantity is undefined, it is `NaN`, and the downstream code handles it. |
| C-13 | **Time-based windows only.** `rolling('30min')`, never `rolling(6)`. Lags in **minutes**, converted to steps from config. |
| C-14 | Ruff for lint and format. Pre-commit hooks. CI blocks on failure. |
| C-15 | **Every `TODO` has an owner and a linked open decision.** `# TODO(OD-4): tilt/azimuth unknown — see MASTER_CONTEXT KU-04` |

---

## 13. Configuration Rules

**Every site-specific value lives in config. The code contains none of them.**

`configs/site_<site_id>.yaml`:

```yaml
# ============================================================================
#  SITE CONFIGURATION
#  Values marked TBC MUST be filled before the physics layer will start.
#  DO NOT invent a plausible default. The code raises on a missing REQUIRED value.
# ============================================================================
site:
  id: "PLTS-XXX"                      # TBC
  name: "TBC"
  latitude_deg: null                  # TBC — REQUIRED. Startup RAISES if null. Never default to 0.
  longitude_deg: null                 # TBC — REQUIRED. Startup RAISES if null.
  altitude_m: null                    # TBC — REQUIRED. Startup RAISES if null.
  timezone: null                      # TBC — REQUIRED. e.g. "Asia/Jakarta" | "Asia/Makassar" | "Asia/Jayapura"
                                      #       Indonesia has NO daylight saving time.

array:
  racking_type: null                  # TBC — REQUIRED: "fixed" | "single_axis"
  surface_tilt_deg: null              # TBC — REQUIRED if racking_type == "fixed"
  surface_azimuth_deg: null           # TBC — REQUIRED if racking_type == "fixed"
  axis_tilt_deg: null                 # required if single_axis
  axis_azimuth_deg: null              # required if single_axis
  max_angle_deg: null                 # required if single_axis
  backtrack: null                     # required if single_axis
  gcr: null                           # TBC — needed for infinite_sheds
  row_pitch_m: null                   # TBC
  module_height_m: null               # TBC — ground clearance
  bifaciality_factor: null            # TBC — e.g. 0.70-0.85 for typical bifacial modules
  albedo_default: null                # TBC — used ONLY if no albedometer and no fitted albedo

sensors:
  poa_is_coplanar_with_modules: null  # TBC — if false, r_poa is MEANINGLESS
  rsi_mounting:
    row: null                         # TBC
    position_in_row: null             # TBC
    height_m: null                    # TBC
  has_albedometer: null               # TBC
  dni_cosz_is_derived: null           # TBC — run the residual test (PRD 16.3) to answer this
  has_wind: null                      # TBC
  wind_height_m: null                 # TBC

# ----------------------------------------------------------------------------
#  COV — every value here MUST be MEASURED in Phase 0, not guessed.
#  See docs/phase0_cov_characterisation.md
# ----------------------------------------------------------------------------
cov:
  canonical_freq: "1min"              # S0-2 measured: slowest five-channel median active p50 = 26.401 s.
                                      # Evidence: docs/phase0_cov_characterisation.md
  resample_method: "zoh"              # "zoh" (default, matches COV semantics) | "trapezoid"
  deadband_wm2:                       # TBC — MEASURED per tag, from the floor of the |delta| distribution
    ghi: null
    dhi: null
    dni_cosz: null
    poa: null
    rsi: null
  max_report_time_s: null             # TBC — the COV heartbeat, if configured
  stale_threshold_s: 300              # after this, DQ -> MISSING
  gap_interp_limit_steps: 2           # interpolate for FEATURE continuity only. NEVER for labels.

physics:
  clearsky_model: "ineichen"          # "ineichen" | "mcclear" | "simplified_solis"
  clearsky_fallback: "ineichen"       # used when mcclear is unreachable
  clearsky_site_correction: null      # fitted in Phase 1 (ADR-004a); null = not yet fitted
  transposition_model: "perez"        # decided by the Phase-1 bake-off against the MEASURED POA sensor
  separation_model: "erbs"            # used to split forecast GHI into DNI/DHI (ECMWF has no fdir)
  bifacial_model: "infinite_sheds"    # "infinite_sheds" (native pvlib) | "pvfactors" (pip install solarfactors)
  shade_factor: -0.02                 # FIT THIS to the site; do not ship the default
  k_c_valid_min_wm2: 20.0             # below this clear-sky GHI, k_c := NaN (NOT a clipped denominator)
  k_c_max: 1.5                        # outlier guard ONLY. DO NOT CLIP TO 1.0 — cloud enhancement is real.
  night_threshold_wm2: 5.0

horizons:
  # served=false => BACKTEST ONLY. The data-path latency budget cannot be met (CON-4 / KU-13).
  - {minutes: 5,    family: nowcast,   served: false}   # TBC — depends on OD-1
  - {minutes: 10,   family: nowcast,   served: false}   # TBC — depends on OD-1
  - {minutes: 15,   family: nowcast,   served: true}
  - {minutes: 30,   family: nowcast,   served: true}
  - {minutes: 60,   family: nowcast,   served: true}
  - {minutes: 120,  family: nowcast,   served: true}
  - {minutes: 180,  family: intraday,  served: true}
  - {minutes: 360,  family: intraday,  served: true}
  - {minutes: 1440, family: dayahead,  served: true}
  - {minutes: 2880, family: dayahead,  served: true}

evaluation:
  daylight_filter: "solar_elevation"  # "solar_elevation" | "clearsky_ghi"
  daylight_elev_threshold_deg: 5.0
  daylight_cs_threshold_wm2: 10.0
  nrmse_denominator: "mean_daylight_actual"   # STATE THIS IN EVERY REPORT. It changes the number by 2-3x.
  ramp_threshold_kc: 0.3
  significance_test: "diebold_mariano"
  significance_alpha: 0.05

quantiles:
  exposed: [0.10, 0.50, 0.90]
  internal: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]   # for a REAL CRPS
  n_mc_samples: 1000                                        # for coherent-quantile propagation (ADR-015)

nwp:
  enabled: null                       # TBC — depends on internet egress (KU-14 / OD-11)
  primary_source: "ecmwf_opendata"    # CC-BY-4.0, commercial use permitted with attribution
  models: ["ifs", "aifs"]
  archive_dir: "data/bronze/nwp"      # ARCHIVE FROM DAY ZERO. The upstream rolling window is ~2-3 days.
  measured_latency_min: null          # TBC — MEASURE from retrieved_at_utc. Do not assume.
  downscale_method: "clearsky_index"  # NOT linear interpolation of W/m2 across a 3-hour step.

deployment:
  data_residency_approved: null       # TBC — legal (OD-10)
  free_tier_no_sla_disclosed: null    # TBC — must be disclosed in writing if free-tier infra is used
```

### 13.1 Config rules

| # | Rule |
|---|---|
| CR-01 | Config is validated against a **Pydantic schema** at startup. |
| CR-02 | A `null` on a **REQUIRED** field ⇒ **raise, with a message naming the KU number.** Do not warn. Do not default. **Raise.** |
| CR-03 | A `null` on an **optional** field ⇒ **warn loudly**, disable the dependent feature, and surface the degradation in the API. |
| CR-04 | `config_hash` is recorded with every forecast run and every model artifact. |
| CR-05 | Site configuration is a **slowly-changing dimension**. A change to tilt, sensor position, or geometry creates a **new row with a new `valid_from`** — never an in-place update. Historical forecasts must remain reproducible against the geometry that existed **when they were issued**. |

---

## 14. Model Selection Rules

| # | Rule |
|---|---|
| MS-01 | **Complexity must earn its place.** Every tier up must be justified by a measured, significant improvement. |
| MS-02 | **A model must beat the baseline.** Specifically: **positive, statistically significant skill vs B1 (smart persistence)** on the primary target/horizon set. |
| MS-03 | **Evaluate per horizon.** A model that wins at 6 h and loses at 15 min is not "better". |
| MS-04 | **Evaluate per regime.** A model that wins on clear days and loses on convective days is a **hazard**, and the gate report must say so (see §10, `failure_cells`). |
| MS-05 | **Reject unstable improvement.** If the skill score flips sign across rolling-origin folds, it is noise. |
| MS-06 | **Prefer the simpler model when performance is statistically equivalent.** A LightGBM that ties a TFT wins — it is faster, interpretable, and cheaper to operate. |
| MS-07 | **Never promote on training or validation performance.** Out-of-time test only, and only **once** per candidate — repeated peeking at the test set turns it into a validation set. |
| MS-08 | **"Rejected — did not beat Tier 1" is a valid and successful outcome.** Publish it. Do not quietly retry until something wins. |
| MS-09 | **Significance is required, not optional.** Diebold–Mariano, or a block-bootstrap CI. On one site with one test period, a 0.3% RMSE difference is noise. |
| MS-10 | **Sequence and multi-horizon models carry a sceptical prior.** `pytorch-forecasting`'s own documentation states that with only one or very few time series, they must be *very long* for deep learning to work well. This is **one site**, possibly with **~1 year** of history (KU-12). That is the regime where gradient boosting usually wins. **Evaluate honestly; expect "rejected" to be a live possibility, and be willing to say so.** |
| MS-11 | **A multi-horizon model (TFT/NHITS) requires known-future covariates to be worth anything.** Without NWP, the only known futures are solar geometry and the calendar — and a TFT that knows only the time of day is an extremely expensive climatology. **Do not build Tier 3 before NWP ingestion exists.** |

---

## 15. Deployment Rules

| # | Rule |
|---|---|
| D-01 | **A fallback MUST exist and MUST terminate.** The chain (ADR-016) ends in diurnal climatology, which needs nothing but a clock. |
| D-02 | **`GET /health` is required.** It reports liveness, readiness, model-load status, data freshness, and NWP freshness. |
| D-03 | **Model artifacts are checksummed.** SHA-256 verified at load. **A mismatch RAISES and triggers the fallback — it never loads.** |
| D-04 | **Versioned deployment.** Every deployed artifact is registered with its version, dataset version, code SHA and config hash. |
| D-05 | **Rollback is required and must be demonstrated.** Any registered version, restorable in <5 minutes. |
| D-06 | **Stale-data detection is required** — including the **COV silent-death case**: a sensor that stops reporting without erroring. Cross-channel liveness resolves it (ADR-012). |
| D-07 | **Every inference is logged** with full provenance. |
| D-08 | **NO SILENT FAILURE.** Every failure produces: a log line, a metric, an alert, and a **degraded-but-labelled output**. |
| D-09 | **The API NEVER returns a stale `200`.** If it cannot serve fresh, it serves a labelled fallback, or it returns `503` with a machine-readable reason. |
| D-10 | **Shadow deployment** for `shadow_days` (default 14) before a new model takes over. Auto-rollback on underperformance. |
| D-11 | **No write path to OT exists in the codebase.** The site adapter has **no write method**. This is enforced by architecture, not by policy. |
| D-12 | **If free-tier infrastructure is used, its no-SLA status MUST be disclosed in writing** to stakeholders, and backups are mandatory (not optional, not "later"). |

---

## 16. AI Coding Agent Instructions

> **You are Claude Code, or an equivalent agent. Read this section fully. It is the part you are most likely to get wrong.**

### 16.1 The fourteen rules

| # | Rule |
|---|---|
| **1** | **Read this Master Context before writing any code.** Every time. Context does not persist across your sessions; this document does. |
| **2** | **NEVER invent missing sensor metadata.** Not latitude. Not tilt. Not timezone. Not timestep. Not deadband. **A plausible default is worse than a crash**, because a crash gets fixed and a plausible default silently corrupts every downstream number forever. |
| **3** | **For any unknown site configuration, add a `TODO` and raise or warn per §13.1.** Link the KU number: `# TODO(KU-04): surface_tilt unknown`. |
| **4** | **Preserve the data contracts (§6).** A column rename is a migration, not a refactor. |
| **5** | **Avoid computer-vision dependencies.** No OpenCV for cloud motion. No CNN on images. No optical flow. Not "just as an option". Not "behind a flag". (CF-05.) |
| **6** | **Write the test with the feature.** Not after. **For features specifically: write the leakage test (§8.2) FIRST.** |
| **7** | **NEVER use a random split.** No `KFold`. No `train_test_split`. No `shuffle=True`. Temporal splitters only. |
| **8** | **Implement the baselines before the advanced models.** All of B0–B7. If you are asked for "a LightGBM model" and the baselines do not exist yet, **build the baselines first and say why.** |
| **9** | **Training and inference transformations MUST be the identical function object.** Not a port. Not "the same logic". If you find yourself writing a second copy of the feature code for the serving path, **stop** — you are creating train/serve skew. |
| **10** | **Update the documentation when the architecture changes.** A new dependency needs an ADR. A new column needs a data-contract entry. |
| **11** | **NEVER silently alter units.** If you convert, name the column for its unit and add a test. ECMWF `ssrd` in J/m² is the trap that catches everyone. |
| **12** | **NEVER use future data in a feature.** Not in a rolling window. Not in an imputation. Not in a scaler. Not in a baseline (`np.roll` wraps — use `.shift()`). |
| **13** | **Surface uncertainty and data-quality state.** Every output carries provenance. A number without provenance is not an output. |
| **14** | **Keep business logic out of notebooks.** Notebooks explore; `src/` decides. |

### 16.2 Additional rules specific to this project

| # | Rule |
|---|---|
| **15** | **`canonical_freq` is not 15 minutes.** It is whatever Phase 0 measured. If you find yourself writing `rolling(4)  # 4 x 15min`, **you have imported a bug from the source document.** Use `rolling('60min')`. |
| **16** | **`k_c` is NOT bounded by 1.** Cloud enhancement is real and common in the tropics. **Never `clip(upper=1.0)`.** The guard is `k_c_max = 1.5`, and it exists to catch outliers, not to enforce physics that does not exist. |
| **17** | **Never divide by a clipped clear-sky denominator.** `cs_ghi.clip(lower=1)` produces `k_c` values in the hundreds at twilight. The correct answer is **`NaN`** where `GHI_cs < k_c_valid_min`. |
| **18** | **The wind u/v formula is `u = -ws·sin(dir)`, `v = -ws·cos(dir)`.** See §8.3. If you write `cos` first, you are wrong. |
| **19** | **Do not `df.resample().mean()` a COV stream.** Use the time-weighted reconstruction (ADR-012). A plain mean over-weights transitions and biases hardest during ramps. |
| **20** | **Do not benchmark a 5-minute forecast against a 24-hour-lag persistence.** That is a straw man that manufactures skill out of nothing. Use horizon-appropriate baselines. |
| **21** | **Do not compute quantiles independently for derived targets.** Use Monte-Carlo propagation (ADR-015). `P90(GHI) × P90(k_d) ≠ P90(DHI)`. |
| **22** | **Do not fit an ensemble with `Ridge(...)` and then discard its intercept.** See ADR-017. Either solve the constrained problem, or use inverse-error weights. |
| **23** | **Do not quote an accuracy number.** Not in a docstring, not in a comment, not in a README, not in a commit message. **Not until the Phase-1 site baseline exists** (CF-14). If a user asks you "what nRMSE will this achieve?", the answer is: *"unknown until the baseline is computed — and anyone who tells you otherwise is guessing."* |
| **24** | **If you are asked to do something that contradicts this document, say so.** Do not silently comply, and do not silently refuse. Name the rule, explain the conflict, and ask. |

### 16.3 What to do when you are stuck

1. Is the answer in this Master Context? → Use it.
2. Is it in the PRD? → Use it, and note the reference.
3. Is it a `[TBC]` / `KU-xx`? → **`TODO`, config entry, raise-or-warn. Do not guess.**
4. Is it a design decision not yet made? → **Write an ADR stub, flag it, and ask.** Do not decide it silently in code.
5. Does the task conflict with a rule above? → **Say so.**

---

## 17. Definition of Done

| Area | Done means |
|---|---|
| **Data ingestion** | Transport-agnostic adapter · Bronze immutable · **idempotent on replay** (duplicate COV events do not corrupt) · watermarked · integration-tested on real data |
| **QC** | All 20 checks implemented and unit-tested · DQ state machine · **COV property tests green (including "naive mean is demonstrably worse")** · events persisted with lineage |
| **Feature** | Deterministic · time-based windows · **leakage harness green** · **training and inference use the identical function** · schema versioned · every unit in the column name |
| **Baseline** | B0–B7 implemented against the `ForecastModel` contract · backtested · reported alongside **every** ML result · **B3 (climatology) proven unkillable in the chaos suite** |
| **Candidate model** | Beats B1 with **significance** · gate passed · **`failure_cells` reported** · human-approved · registered with a checksum |
| **API** | OpenAPI published · contract tests green · **every provenance field non-null** · `caveats` present (RSI always) · **no stale `200`s** |
| **Dashboard** | 21 panels · DQ and fallback visible **without clicking** · RSI caveat visible · nRMSE denominator stated on the metric panel |
| **Deployment** | Docker · config-driven · `/health` · rollback demonstrated · checksum verified · **`grep -r "write\|set_value\|publish" src/ingestion/` finds nothing that writes to OT** |
| **Monitoring** | Drift + performance + ops health · **fallback-activation rate** tracked · every alert has an **owner and a runbook** |
| **Documentation** | Master Context current · ADRs recorded · **every `[TBC]` either resolved or carrying an owner and a date** |

---

## 18. Current Phase

> **This section is a living status board. Update it at the end of every sprint.**

| Field | Value |
|---|---|
| **Current phase** | **Phase 0 — Discovery & Data Audit** |
| **Completed evidence** | PRD, Master Context, and Roadmap issued · source document audited · **S0-1 complete** (archiver live; observation 2/2 via post-fix scheduled runs) · S0-2 measured deliverables, deterministic artifacts, report, and data-backed `canonical_freq=1min` complete (the S0-2 task itself remains open pending historian confirmation) · **S0-3 complete** (`dni_cosz` independently measured, `is_derived_tag=false`) · **S0-4 consolidation delivered** (canonical `site_configuration` + `sensor_metadata` populated with provenance; certificate evidence open) · **S0-5 complete** (full 19-month history audited via run 29683909065; coverage/gap/outage, empirical monthly `k_c`/regime read from the data, all six operator leads sensor-corroborated, operational periods extracted) |
| **In progress** | **S0-2** historian configuration confirmation · **S0-4** certificate/mapping evidence collection (consolidation delivered) · **S0-6** general CI/leakage harness completion |
| **Ready next** | **S0-6 general CI + leakage harness** (`tests/leakage/test_no_future_leakage.py` and push/PR CI), in parallel with the S0-2 historian follow-up, S0-4 certificate collection, and the S0-7 OT-security decision |
| **Blocked / unresolved** | **OD-1 / S0-7** (no written OT-security data-path decision or dated commitment) |
| **Next milestone** | **Sprint 0 complete:** NWP archiver running · COV characterised · `dni_cosz` derived-vs-measured settled · site metadata populated · historical coverage audited · CI + leakage harness green |
| **Open decisions** | OD-1 … OD-13 (PRD §39) |

### 18.1 Sprint 0 checklist

> **Snapshot:** 2026-07-17 20:47 UTC. Legend: ✅ complete · 🟡 in progress · ⏭️ ready to start · ⬜ not started. Do not promote 🟡 to ✅ on implementation evidence alone when an operational acceptance gate remains.

| # | Task | Status | Evidence, gap, and next action | Owner |
|---|---|---|---|---|
| **S0-1** | **Start the NWP archiver** (ECMWF Open Data → Parquet, every cycle) | ✅ **Complete — observation 2/2** | Code, schema, active IFS+AIFS workflow, separate UTC timestamps, manual smoke/full/catch-up, and first qualifying run [29560032016](https://github.com/ompltsikn/Forecasting-Irradiance/actions/runs/29560032016) (AIFS 2026-07-17T00:00Z) are verified. Post-fix scheduled run [29592915322](https://github.com/ompltsikn/Forecasting-Irradiance/actions/runs/29592915322) committed and read-back-validated the successive cycle (AIFS 06:00Z plus IFS 00:00Z/06:00Z), [29600290220](https://github.com/ompltsikn/Forecasting-Irradiance/actions/runs/29600290220) added AIFS 12:00Z, and [29607833813](https://github.com/ompltsikn/Forecasting-Irradiance/actions/runs/29607833813) verified no uncommitted cycles remain. The three dependency-collection failures did not count toward the gate. | Data Eng |
| **S0-2** | COV characterisation → `docs/phase0_cov_characterisation.md`; set a **justified** `canonical_freq` | 🟡 **Measured deliverables complete; historian confirmation open** | Strict run matched **145/145 ZIPs** and all **170 CSV entries** (163 populated, 7 empty). The parser confirmed tag-in-header/value-in-row-column-B semantics. **2,656,231** rows became **2,640,992** events after **15,239** exact duplicates; 12 order inversions and no malformed/conflicting rows were retained in evidence. The 136 tags split into **26 instantaneous**, **76 accumulation**, and **34 meteorological**. Five-channel median active p50 values (18 supported tags) give `canonical_freq`: **1min** from a slowest median of 26.401 s; one DNIcosZ tag has active p50 69.416 s. All heartbeat candidates are unresolved and configured max-report-time is `unknown`. Naive fractional timestamps and the substantial 06:00–18:00 window are consistent with naive WITA, not historian proof. Full CLI/notebook hashes match. **Remaining:** obtain historian timestamp and configured max-report-time/deadband evidence. | Data Eng |
| **S0-3** | The `dni_cosz` test: is `GHI − DHI − DNI·cosZ` ≈ 0 to machine precision? → `sensor_metadata.is_derived_tag` | ✅ **Complete — independently measured** | Strict run [29589030480](https://github.com/ompltsikn/Forecasting-Irradiance/actions/runs/29589030480) used 145 ZIPs and 156 instantaneous XLSX files (**8,027,772** historical raw valid rows) for EMI01–EMI04. All **40/40** direct plus backward-only staleness cases are `measured`; historical direct active `n=319,332`, MAE 99.14 W/m², 1.15% within quantization. Canonical `sensor_metadata.is_derived_tag=false`; report, artifacts, plot, and tests are present. Zenith interpretation remains provisional only because historian clock semantics are open. | Perf Eng |
| **S0-4** | Site metadata audit → populate `site_configuration` + `sensor_metadata` | 🟡 **Consolidated; certificate evidence open** | The canonical config ([`configs/site_plts-ikn.yaml`](configs/site_plts-ikn.yaml)) now populates the full site + sensor metadata with per-field provenance: fixed racking, 10° tilt / 0° azimuth, POA co-planarity, survey row geometry (5.00 m collector width, 2.50 m front clear gap), derived `row_pitch=7.424 m` / `gcr=0.6735`, module height 1.46 m (survey mean, 0.97–1.96 m spread), datasheet bifaciality 0.80±0.05, TMY-modelled `albedo_default=0.153` (low confidence), no albedometer, WS-1..WS-4 SR20-D2 + DR20/HQB-TG1 and WS-5 SR30-M2-D1 inventories, and the 12-point RSI mounting survey. Schema validation and unit/integration tests are green. Evidence: [`docs/phase0_site_metadata_audit.md`](docs/phase0_site_metadata_audit.md) + [`artifacts/phase0_site_metadata/`](artifacts/phase0_site_metadata/). **Remaining:** per-unit serials, calibration date/due/factor, RSI model, DHI shading, EMI↔WS mapping, and design-drawing geometry confirmation — all owner/due-dated in `unresolved_metadata`. | Perf Eng / O&M |
| **S0-5** | Historical coverage audit → `docs/phase0_data_audit.md` | ✅ **Complete — full history audited** | Strict run [29683909065](https://github.com/ompltsikn/Forecasting-Irradiance/actions/runs/29683909065) audited **19 months (2024-12-21 → 2026-06-30)**, **377** instantaneous XLSX workbooks + the 145-ZIP COV cross-check, on the `canonical_freq=1min` grid with backward-only ZOH: per-channel coverage/gap profiles, **138 outage candidates**, empirical monthly `k_c`, and rule-based cloud-regime distributions **read from the data** — `HIGHLY_VARIABLE` is modal (0.24–0.52 of daylight), `CLEAR` ≤ 0.19, `k_c>1` up to 0.36, and **no clean calendar season exists** (Feb `OVERCAST` 0.291 in 2025 vs 0.337 in 2026; Jun `HIGHLY_VARIABLE` 0.377 vs 0.518) — **no assumed Indonesian monsoon calendar**. **All six operator leads sensor-corroborated**: WS-3 GHI measured 2025-03-06 → 2025-06-23 (start identical to the maintenance "Communication Loss" ticket); WS-4 RSI_01/RSI_02 dark one day after their reported removals. New findings: **168-day WS-5 GHI outage** (2025-02-01 → 2025-07-18) and a **WS-2 GHI outage Feb–May 2026** with no operator record. Operational corroboration: 1,212 maintenance rows, 1,784 DCM intervals, 47 curtailment-days. Evidence: `docs/phase0_data_audit.md` + `artifacts/phase0_data_audit/`. | Data Eng |
| **S0-6** | Repo skeleton + CI + **the leakage harness** | 🟡 **Partial** | Skeleton plus NWP/COV/DNI·cosZ/site-metadata tests exist; final local target is **228 tests**, and the S0-3 full-history workflow is green. General push/PR CI and required `tests/leakage/test_no_future_leakage.py` remain absent. | ML Eng |
| **S0-7** | Escalate OD-1 (data path) to OT security | ⬜ **Not started / unresolved** | Manual SCADA export is known, but no written production path/cadence/latency decision or dated decision commitment is recorded. | Product |

**M0 remains open: 3/7 tasks are fully accepted. S0-1, S0-3, and S0-5 are complete; S0-2 remains 🟡 on historian confirmation.** **S0-3 decision: COMPLETE.** **S0-5 decision: COMPLETE.** The full 19-month history is audited, all six operator leads are sensor-corroborated, and the site's own regime distribution — not a calendar — now defines seasonality for the ML-002 split. See [`docs/phase0_data_audit.md`](docs/phase0_data_audit.md). **S0-4 decision: consolidation delivered; 🟡 pending serial/calibration certificates and mapping/geometry confirmations.** **S0-6 decision: GO now** — the repository skeleton and 256 passing tests exist, and no part of S0-6 depends on the open S0-2 historian or S0-4 certificate items; deliver general push/PR CI and `tests/leakage/test_no_future_leakage.py`. **NO-GO for Phase 1 and all modelling.**

#### Sprint 0 progress board

> Tick a task green **only** when its acceptance gate is met — never on implementation evidence alone. Sub-items marked ⬜ are the exact remaining work.

| # | Task | Progress | Sub-deliverables |
|---|---|---|---|
| **S0-1** | NWP archiver | ✅ **Done (4/4)** | ✅ code + schema · ✅ IFS/AIFS workflow live · ✅ Shared-Drive read-back · ✅ observation 2/2 |
| **S0-2** | COV characterisation | 🟡 **4/5** | ✅ 145/145 ZIP reconciliation · ✅ per-tag deadband / inter-arrival / max-gap evidence · ✅ `canonical_freq=1min` · ✅ report + deterministic artifacts · ⬜ **source-system historian evidence** (timestamp semantics, configured max-report-time, configured deadband) |
| **S0-3** | DNI·cosZ derived-vs-measured | ✅ **Done (4/4)** | ✅ full-history strict run 29589030480 · ✅ 40/40 cases `measured` · ✅ `sensor_metadata.is_derived_tag=false` · ✅ report + artifacts |
| **S0-4** | Site metadata audit | 🟡 **5/6** | ✅ canonical `site_configuration` · ✅ survey geometry (row pitch / GCR / module height) · ✅ instrument inventory · ✅ 12-point RSI mounting survey · ✅ schema validation + tests · ⬜ **8 owner/due-dated `unresolved_metadata` fields** (serials, calibration certificates, RSI model, DHI shading, DR20 ISO class, EMI↔WS mapping, design geometry, ML defaults) |
| **S0-5** | Historical coverage audit | ✅ **Done (6/6)** | ✅ 19-month coverage/gap profile · ✅ 138 outage candidates · ✅ empirical monthly `k_c` · ✅ data-derived cloud-regime distribution · ✅ all six operator leads sensor-corroborated · ✅ maintenance / outage / curtailment periods |
| **S0-6** | Repo skeleton + CI + leakage harness | 🟡 **2/4** | ✅ repository skeleton · ✅ 256 passing tests (unit / integration / leakage / workflow-contract) · ⬜ **general push/PR CI** · ⬜ **`tests/leakage/test_no_future_leakage.py`** |
| **S0-7** | Escalate OD-1 to OT security | ⬜ **Not started (0/1)** | ⬜ written production data-path / cadence / latency decision, or a named owner and a decision date |

#### Sprint 0 acceptance checklist

| Task | ✅ Verified progress | ⬜ Remaining before parent task is green |
|---|---|---|
| **S0-1** | Archiver code/schema, IFS+AIFS workflow activation, manual smoke/full/catch-up, Shared Drive read-back validation, first qualifying scheduled issue cycle, and the post-fix scheduled runs 29592915322/29600290220 committing and read-back-validating the successive cycles; observation **2/2**. | — Complete. |
| **S0-2** | Local/Drive raw reconciliation; actual CSV schema; tag parser and EMI01–05 aliases; multi-CSV/empty/malformed/duplicate/order handling; per-tag deadband, inter-arrival, max-gap, flat/night, and heartbeat evidence; five plots; deterministic CLI/Colab artifacts; `canonical_freq=1min`; tests and normative report. | Source-system evidence for historian timestamp semantics, configured max-report-time, and configured deadband. Until then the parent remains 🟡 even though the measured deliverables are complete. |
| **S0-3** | Provenance-complete raw COV + historical XLSX analysis; no-future alignment; direct and four staleness cases; 40/40 stable `measured`; plot/report/artifacts; `sensor_metadata.is_derived_tag=false`; strict run 29589030480. | — Complete. Retain the provisional zenith interpretation until historian clock semantics are confirmed. |
| **S0-4** | Canonical `site_configuration` + `sensor_metadata` populated with provenance; GCR/row-pitch/module-height derived from the field survey; bifaciality and instrument inventory from as-built datasheets; RSI mounting survey recorded; schema validation and tests green; every unresolved field has owner/reason/due-date. | Serial numbers and calibration date/due/factor certificates; RSI model, DHI shading, EMI↔WS mapping, and design-drawing geometry confirmation. |
| **S0-5** | Full 19-month history (2024-12 → 2026-06) audited via strict run 29683909065: coverage/gap profiles, 138 outage candidates, empirical monthly `k_c` and rule-based cloud-regime distributions read from the data, all six operator leads sensor-corroborated, and maintenance/outage/curtailment periods extracted. Evidence: `docs/phase0_data_audit.md` + `artifacts/phase0_data_audit/`. | — Complete. Month/season labels stay provisional until the S0-2 historian-timezone item closes; that caveat is carried inside the audit and does not block S0-5. |
| **S0-6** | Repository skeleton and NWP/COV/DNI·cosZ/site-metadata test suites are implemented; **228 tests passed** at this snapshot. | Add general CI and `tests/leakage/test_no_future_leakage.py`, then record a green CI run. |
| **S0-7** | The current offline/manual SCADA export path is identified. | Obtain a written OT-security data-path/cadence/latency decision, or at minimum a named owner and decision date. |

> **No model is built in Sprint 0. Not even persistence.**
> The most common failure mode in projects like this is to start with LightGBM on whatever CSV is lying around, and discover four months later that the timestep was fiction, the DNI channel was derived, and the array is on trackers.

---

## Appendix A — Repository Structure

```
irradiance-forecasting/
├── README.md                      # Quickstart. Links to PRD + Master Context. NO accuracy claims (CF-14).
├── pyproject.toml                 # Pinned deps. Ruff + mypy config.
├── .pre-commit-config.yaml
│
├── configs/
│   ├── site_<site_id>.yaml        # ALL site-specific values. Schema-validated. Nulls RAISE.
│   ├── model_<tier>.yaml          # Hyperparameters per tier
│   └── logging.yaml
│
├── data_contracts/
│   ├── silver_schema.py           # Pydantic/pandera schemas for irradiance_canonical
│   ├── gold_schema.py             # Feature + label schemas
│   ├── forecast_schema.py         # THE forecast contract (§11)
│   └── nwp_schema.py              # issue_time / valid_time / retrieved_at — three columns, always
│
├── docs/
│   ├── PRD_Forecasting_Irradiance_ML.md
│   ├── MASTER_CONTEXT_Forecasting_Irradiance_ML.md
│   ├── adr/                                    # one file per ADR; new decisions get a new file
│   ├── phase0_data_audit.md                    # Sprint 0 deliverable
│   ├── phase0_cov_characterisation.md          # Sprint 0 deliverable — deadband, inter-arrival, canonical_freq
│   ├── site_baseline_report.md                 # Phase 1 deliverable — THE reference for every future claim
│   └── runbooks/                               # one per alert. An alert without a runbook is noise.
│
├── notebooks/                     # EXPLORATION ONLY. No production logic (C-10).
│
├── src/
│   ├── ingestion/
│   │   ├── base.py                # SiteAdapter ABC — NOTE: has NO write method (D-11)
│   │   ├── csv_adapter.py
│   │   ├── sftp_adapter.py        # gated on OD-1
│   │   ├── opcua_adapter.py       # gated on OD-1; READ-ONLY
│   │   └── nwp_archiver.py        # RUNS FROM DAY ZERO (ADR-013)
│   │
│   ├── quality/
│   │   ├── cov_resample.py        # ZOH / trapezoid time-weighted reconstruction (ADR-012)
│   │   ├── cov_characterise.py    # deadband + inter-arrival measurement
│   │   ├── checks.py              # the 20 QC checks; wraps pvanalytics
│   │   ├── liveness.py            # cross-channel COV silent-death detection
│   │   └── state_machine.py       # GOOD / DEGRADED / BAD / MISSING / IMPUTED
│   │
│   ├── physics/
│   │   ├── solar_geometry.py      # pvlib. RAISES if lat/lon/alt/tz unset (KU-01/02)
│   │   ├── clearsky.py            # + detect_clearsky validation + site correction (ADR-004a)
│   │   ├── transposition.py       # Perez et al.; the Phase-1 bake-off lives here
│   │   ├── separation.py          # Erbs/DISC/DIRINT — split forecast GHI (ECMWF has no fdir)
│   │   ├── bifacial.py            # infinite_sheds; optional solarfactors
│   │   └── reconciliation.py      # the primitive decomposition (ADR-011)
│   │
│   ├── features/
│   │   ├── builder.py             # THE feature function. Used by BOTH training and inference (C-11).
│   │   ├── lags.py                # time-based only (C-13)
│   │   ├── rolling.py             # time-based only (C-13)
│   │   ├── wind.py                # the CORRECT u/v (§8.3)
│   │   ├── nwp_features.py        # issue-time discipline (L-04)
│   │   └── regime.py              # rule-based weather regime
│   │
│   ├── models/
│   │   ├── base.py                # ForecastModel ABC (§9)
│   │   ├── baselines/             # B0..B7 — SAME interface as everything else
│   │   ├── tabular/               # LightGBM, XGBoost, HistGB
│   │   ├── sequence/              # LSTM / GRU / TCN — Phase 3, sceptical prior (MS-10)
│   │   └── multihorizon/          # NHITS first, then TFT — Phase 3, needs NWP (MS-11)
│   │
│   ├── ensemble/
│   │   ├── weights.py             # inverse-error (MVP); constrained stacking (later) — ADR-017
│   │   ├── verification_lag.py    # T - h enforcement. Unit-tested.
│   │   └── fallback_chain.py      # ADR-016. Normative order. Terminates in climatology.
│   │
│   ├── evaluation/
│   │   ├── metrics.py             # nRMSE denominator from config. MAPE raises NotImplementedError.
│   │   ├── significance.py        # Diebold-Mariano / block bootstrap
│   │   ├── calibration.py         # coverage, PIT, sharpness — PER REGIME
│   │   ├── backtest.py            # rolling origin
│   │   └── gate.py                # the acceptance gate. Emits failure_cells.
│   │
│   ├── serving/
│   │   ├── api.py                 # FastAPI
│   │   ├── schemas.py             # Pydantic — mirrors data_contracts/forecast_schema.py
│   │   ├── inference.py
│   │   └── provenance.py          # every field, every row, no exceptions
│   │
│   ├── monitoring/
│   │   ├── drift.py               # seasonal-aware: don't cry wolf every monsoon
│   │   ├── performance.py
│   │   └── alerts.py              # every alert links to a runbook
│   │
│   └── pipelines/
│       ├── ingest.py
│       ├── qc.py
│       ├── featurize.py
│       ├── train.py
│       ├── infer.py
│       └── evaluate.py
│
├── tests/
│   ├── unit/
│   │   ├── test_solar_geometry.py       # vs reference SPA, <0.01 deg
│   │   ├── test_clearsky.py
│   │   ├── test_kc_twilight.py          # k_c must be NaN, not 1e6 (rule 17)
│   │   ├── test_wind_uv.py              # the four reference cases in §8.3 (rule 18)
│   │   ├── test_units.py                # incl. ssrd J/m2 -> W/m2, and de-accumulation
│   │   └── test_rolling_freq_invariant.py  # a feature must survive a canonical_freq change
│   ├── leakage/
│   │   ├── test_no_future_leakage.py    # §8.2 — WRITE THIS FIRST
│   │   ├── test_nwp_issue_time.py
│   │   └── test_no_random_split.py      # static guard on src/
│   ├── property/
│   │   └── test_cov_resample.py         # hypothesis: reconstruction beats naive mean
│   ├── model/
│   ├── integration/
│   └── chaos/
│       └── test_fallback.py             # incl. the COV silent-death case
│
├── scripts/
│   ├── start_nwp_archiver.sh            # SPRINT 0, TASK 1. Run this before anything else.
│   ├── characterise_cov.py              # SPRINT 0, TASK 2
│   └── test_dni_cosz_derived.py         # SPRINT 0, TASK 3 — ten minutes, settles OD-3
│
├── docker/
├── dashboards/
├── artifacts/                           # gitignored; MLflow-managed
└── .github/workflows/
```

### Folder responsibilities

| Folder | Owns | Must not |
|---|---|---|
| `ingestion/` | Getting raw data in, unmodified, idempotently | **Write anything to OT.** The ABC has no write method. |
| `quality/` | COV reconstruction, QC checks, DQ state | Silently fill a gap; silently pass a failed check |
| `physics/` | pvlib wrappers; the primitive decomposition | Hard-code any site value; start without lat/lon/alt/tz |
| `features/` | **The one feature function** used by both training and inference | Use a count-based window; read the future |
| `models/` | The `ForecastModel` contract, all tiers | Load a checksum-mismatched artifact |
| `ensemble/` | Weights, verification lag, **the fallback chain** | Violate the verification lag; fail to terminate |
| `evaluation/` | Metrics, significance, calibration, **the gate** | Aggregate away a per-regime failure; use MAPE |
| `serving/` | API, provenance | Return a stale `200` |
| `monitoring/` | Drift, performance, alerts | Alert without a runbook |

---

## Appendix B — Known-Wrong Patterns (do not reproduce)

These are the specific defects found in the source document (`Forecasting_Irradiance.docx`, audited in PRD Appendix A). **An AI agent trained on similar material will reproduce them by default.** They are listed here so you can recognise and refuse them.

| # | Wrong | Right | Why it matters |
|---|---|---|---|
| 1 | `u = ws*cos(dir); v = ws*sin(dir)` | `u = -ws*sin(dir); v = -ws*cos(dir)` | Wrong axis **and** wrong sign. Silently makes every wind feature meaningless. It does not crash. |
| 2 | `GHI / cs_ghi.clip(lower=1)` | `k_c = NaN where cs_ghi < 20` | Produces `k_c` in the hundreds at twilight, twice a day, forever. Dominates any scaler and any squared loss. |
| 3 | `rolling(4)  # 4 x 15min` | `rolling('60min')` | Hard-codes a timestep that **does not exist** on a COV stream. |
| 4 | `np.roll(y, 24*4)` as persistence | `y.shift(h)` | `np.roll` **wraps** — the end of the test set leaks into the start of the baseline. |
| 5 | 24-h-lag persistence as the benchmark for a 5-min forecast | Horizon-appropriate baselines (B0–B7); headline vs **B1** | Manufactures an impressive skill score out of nothing. |
| 6 | `Ridge(positive=True)` → discard intercept → renormalise weights | Constrained NNLS, or inverse-error weights | **The object that predicts is not the object that was fitted.** |
| 7 | Refit ensemble weights on "the last 7 days of actuals" | Respect the **verification lag**: only forecasts issued ≤ `T − h` | For day-ahead, those actuals **do not exist yet**. |
| 8 | `target_normalizer=None  # Kt is already [0,1]` | `k_c ∈ [0, 1.5]` | **Contradicts the same document's own correct point** that `k_c > 1` is valid. |
| 9 | `static_reals=[lat, lon, tilt, ...]` on a single site | Drop them | A constant vector. Zero information. |
| 10 | Daylight filter written in a **comment**, metrics computed over the **whole array** | Daylight filter is the **default code path** | The document's own headline warning, violated twenty lines below it. |
| 11 | `mean_obs = mean(y[y > 0])` as the nRMSE denominator | Pinned in config; **stated in every report** | Changes the headline number by 2–3×. |
| 12 | "nRMSE 11.43% → 8–9% with LSTM"; "10–40% improvement" | **Say nothing until the Phase-1 baseline exists** | Fabricated. Un-sourced. Site-independent. Forbidden by CF-14. |
| 13 | Five independent regressions, "reconcile" afterwards | **Primitive decomposition** (ADR-011) | Guarantees mutually inconsistent output. |
| 14 | `df.resample('1min').mean()` on a COV stream | Time-weighted ZOH/trapezoid (ADR-012) | **Over-weights transitions.** Biases hardest during the ramps you exist to forecast. |
| 15 | `P90(GHI) × P90(k_d)` as `P90(DHI)` | Monte-Carlo propagation (ADR-015) | Quantiles do not compose through a nonlinear reconstruction. |
| 16 | Sky-image / optical-flow / CNN nowcasting | **Not available. CF-04, CF-05.** | The hardware does not exist. |

> **A note on where these came from.** The technically weakest content in the source document — the fabricated accuracy figures, the wrong wind formula — is concentrated in its *most confident, most fluent* passages. The sober sections held up. **Fluency is not evidence.** Treat a confident number with more suspicion than a hedged one.

---

## Revision History

| Ver | Date | Change | Approved by |
|---|---|---|---|
| 1.0 | — | Initial issue. Canonical facts CF-01…CF-14. ADR-001…ADR-018. | *pending* |
| 1.1 | 2026-07-17 | Updated the living Sprint 0 status board with verified repository, GitHub Actions, Shared Drive, raw-data inventory, and remaining gate evidence. No Canonical Fact or ADR changed. | *pending* |
| 1.2 | 2026-07-17 | Added per-task acceptance checklists, refreshed the live S0-1 observation snapshot, and recorded the evidence-backed GO decision for S0-3. No Canonical Fact, ADR, or gate criterion changed. | *pending* |
| 1.3 | 2026-07-17 | Recorded the full-history S0-3 measured decision and metadata boolean, refreshed S0-1 failure/fix evidence, and authorised S0-4 discovery. No Canonical Fact, ADR, or gate criterion changed. | *pending* |
| 1.4 | 2026-07-18 | Recorded the S0-4 consolidation: populated canonical `site_configuration` + `sensor_metadata` with provenance, survey-derived geometry, instrument inventories, RSI mounting survey, and owner/due-dated unresolved certificate evidence. S0-4 stays 🟡. No Canonical Fact, ADR, or gate criterion changed. | *pending* |
| 1.5 | 2026-07-18 | Recorded S0-1 observation-gate completion: post-fix scheduled runs 29592915322/29600290220/29607833813 committed and read-back-validated the successive six-hour cycles; S0-1 → ✅ and M0 count 1/7 → 2/7. No Canonical Fact, ADR, or gate criterion changed. | *pending* |
| 1.6 | 2026-07-18 | Recorded the evidence-backed GO decision for S0-5 (historical coverage audit) and refreshed the living status board fields to the post-S0-4 state. No Canonical Fact, ADR, or gate criterion changed. | *pending* |
| 1.7 | 2026-07-19 | Delivered the S0-5 historical coverage audit (`docs/phase0_data_audit.md` + `artifacts/phase0_data_audit/`): 1-minute backward-only coverage/gap/outage profiles per channel, empirical monthly `k_c` and rule-based cloud-regime distributions derived from the data (no assumed monsoon calendar), and maintenance/outage/curtailment corroboration from the operator workbooks. Corrected the S0-4 operator leads (WS-3 GHI down Mar 2025 → 2025-06-25; RSI WS3.1/3.2/3.3 2025-06-30, WS4.1 2025-09-01, WS4.2 2026-01-05). S0-5 acceptance 🟡 pending the full-history CI refresh and historian-timezone confirmation; M0 stays 2/7. No Canonical Fact, ADR, or gate criterion changed. | *pending* |
| 1.8 | 2026-07-19 | **S0-5 complete.** Attached the strict full-history audit from run 29683909065: 19 months (2024-12-21 → 2026-06-30), 377 instantaneous XLSX workbooks + the 145-ZIP COV cross-check, 138 outage candidates. All six operator-reported sensor leads are corroborated by the sensor data (WS-3 GHI measured 2025-03-06 → 2025-06-23; WS-4 RSI_01/RSI_02 dark one day after their reported removals). New findings: a 168-day WS-5 GHI outage (2025-02-01 → 2025-07-18) and a WS-2 GHI outage Feb–May 2026 with no operator record. The empirical regime distribution shows `HIGHLY_VARIABLE` as the modal regime and **no clean calendar season** — inter-annual variation is comparable to intra-annual — so the §12 unseen-season split must be defined against the observed regime distribution, not the Gregorian calendar. S0-5 → ✅ and M0 count **2/7 → 3/7**; the historian-timezone caveat is carried, not blocking. No Canonical Fact, ADR, or gate criterion changed. | *pending* |
| 1.9 | 2026-07-19 | Added the **Sprint 0 progress board** (per-task progress with explicit ⬜ sub-deliverables) and recorded the **S0-6 GO decision**: the repository skeleton and 256 passing tests exist, and no part of S0-6 depends on the open S0-2 historian or S0-4 certificate items. S0-6's remaining work is exactly two items — general push/PR CI and `tests/leakage/test_no_future_leakage.py`. Gate M0 stays 3/7. No Canonical Fact, ADR, or gate criterion changed. | *pending* |

> **To change a Canonical Fact (§2) or an accepted ADR (§5): open a decision, record the rationale, update this table, and update every affected document, diagram, test and code path in the same change. There is no partial update.**
