# Judge Improvement Implementation Checklist

This maps every item from the artifact-level judge review to completed work. A
checked item means addressed and verified; accuracy targets may still be `PARTIAL`.

## Output and forecast calibration

- [x] Emit per-example attribution: opening balance/reserve, streams, dated flows,
  candidates, projected low, evidence trace, mismatches, and selection rank.
- [x] Investigate recommendation-changing public requests 06, 08, 11, 13, and 21.
- [x] Compare category amount statistics without weakening conservative essentials.
- [x] Keep distinct recurring obligations separate by normalized description.
- [x] Record recurrence confidence from evidence count, interval match, and spread.
- [x] Distinguish stable, first, temporary, arrears, permanent, and stale salary states.
- [x] Reconcile only matching scheduled/recurring instances and retain distinct arrears.
- [x] Define and test request-anchored, inclusive 90-day earliest-date semantics.
- [x] Preserve structured conflict provenance and explicit precedence.
- [x] Remove redundant changes and retest selected-plan safety after each removal.
- [x] Expose the exact deterministic ranking key for every public candidate.
- [x] Report label-independent leave-one-out behavior and prohibit ID-specific tuning.
- [x] Publish categorical and 2%/5% safe-amount targets and honest results.

## Code and verification

- [x] Add immutable independent ledger arithmetic that never calls
  `Forecaster.trajectory` or `Forecaster.is_safe`.
- [x] Add monotonic/property tests for balances, reserves, expenses, and payments.
- [x] Add six output mutation checks that must be rejected.
- [x] Add separate-obligation and same-day cash-flow synthetic tests.
- [x] Add month-end/leap, conflict, foreign-currency, retry/lifecycle, and horizon tests.
- [x] Validate image hash, currency, selected label, method, review, and confidence.
- [x] Test malformed/invalid/injected/timeout optional-model output and safe fallback.
- [x] Version input, output, image-cache, diagnostics, calibration, and audit schemas.
- [x] Emit JSON quality results; strict mode exits nonzero on `PARTIAL` or `FAIL`.
- [x] Mark QC-05 `PARTIAL` until every published accuracy threshold passes.

## Explanations and AI evidence

- [x] Name the material projected obligation and date.
- [x] State counted confirmed income and excluded pending income when relevant.
- [x] State installment total/fee/count and why the offer won.
- [x] Name the confirmed inflow that makes waiting safe.
- [x] Quantify authorized change savings and state selected-set minimality.
- [x] Say that passing a forecast is not certainty about future cash flows.
- [x] Exercise guarded extraction with adversarial mocks; record that no live endpoint
  was configured rather than inventing model usage.

## Transcript and submission

- [x] Rebuild the submission transcript in strict chronological order.
- [x] Remove duplicated continuation bookkeeping from that transcript.
- [x] Include alternatives, defects, rejected approaches, and before/after metrics.
- [x] End with final tests, limitations, hashes, and reproduction commands.
- [x] Record exact Python, Tesseract, and Leptonica versions.
- [x] Generate a source checksum manifest and synchronized artifact checksums.
- [x] Regenerate output after the final code change and rebuild both archives.
- [x] Run tests and output generation from a clean archive extraction.
- [x] Verify no caches, credentials, datasets, logs, or unexpected files are packaged.

## Explicit prohibitions

- [x] No request-ID branches or copied public answers in prediction code.
- [x] No minimum-balance relaxation or essential-spend understatement to chase labels.
- [x] No pending income, arbitrary rounding, or invented facts used for calibration.

Evidence files: `public_diagnostics.json`, `calibration_report.json`,
`final_quality.json`, `quality_report.md`, and `source_manifest.sha256`.
