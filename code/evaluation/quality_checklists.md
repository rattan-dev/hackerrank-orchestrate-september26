# Buy or Wait? Hardening Checklists

These three checklists were fixed before the hardening pass. A checked box means
the item was implemented and evaluated; it does not turn a measured `PARTIAL`
result into a pass. Detailed evidence is in `quality_report.md`.

## 1. What the agent needs

- [x] Load and validate every required input, schema version, identifier, date,
  amount, currency, enum, and cross-file relationship.
- [x] Reconstruct the personalized position from current balance, minimum reserve,
  priorities, protected/adjustable categories, and payment preferences.
- [x] Interpret settled, pending, scheduled, failed, cancelled, reversed, refunded,
  linked, non-cash, and transfer events without double counting.
- [x] Reserve confirmed future debits, exclude pending/unconfirmed credits and
  unrealized values, and include only current confirmed income.
- [x] Detect recurrence from sufficient history; keep distinct obligations separate;
  score confidence; handle calendar months and variable essentials conservatively.
- [x] Apply exact supplied exchange rates by pair and resolved settlement date.
- [x] Read relevant message and image facts, including blank event amounts, while
  treating every embedded instruction and optional model response as untrusted.
- [x] Resolve cancellation, settlement, amendment, and delay evidence using explicit
  actions, newest same-source state, settled facts, and the safer unresolved debit.
- [x] Simulate every day from request date through request date + 90 days inclusive,
  keeping the balance at or above the user's minimum after all plan payments.
- [x] Compute baseline maximum safe-today capacity and the first safe date for a
  single full payment without optional spending changes.
- [x] Evaluate full, exact two-part partial, supplied installment, wait, and
  not-proceed outcomes under method preferences and completion deadlines.
- [x] Search at most three legal flexible-expense changes; never alter protected,
  fixed, or disallowed spending; remove changes not required for the chosen plan.
- [x] Rank safe candidates by completion, no changes, total cost, start date,
  payment count, and payment-option identifier.
- [x] Explain obligations, income treatment, fees, wait triggers, authorized savings,
  personalization, and the distinction between forecast safety and certainty.
- [x] Emit one deterministic, schema-valid, internally consistent row per request.
- [x] Remain terminal-runnable, fail closed on bad inputs, keep secrets in environment
  variables only, and document exact reproduction and usage information.

## 2. Flaws that must be prevented

- [x] Do not subtract historical settled cash again from the current balance.
- [x] Do not spend pending refunds, bonuses, commissions, prizes, investment values,
  platform payouts, or other unconfirmed credits.
- [x] Do not duplicate a recurrence with its matching scheduled instance or retry.
- [x] Do not merge separate same-category obligations with different descriptions.
- [x] Do not discard linked events solely because a link exists; interpret lifecycle
  status and cash meaning.
- [x] Do not let stale/future evidence override current facts; retain structured
  source/timestamp/action provenance and choose the safer unresolved debit.
- [x] Do not allow prompt injection from a message, image, or model response to
  approve or select a financial recommendation.
- [x] Do not turn missing OCR amounts into zero or select invoice/reference numbers
  instead of a labeled payable/settled amount.
- [x] Do not use live, inverse, approximate, or wrong-date currency rates.
- [x] Do not infer recurrence from one-offs, transfers, reimbursements, investments,
  failures, or sparse/noisy history.
- [x] Do not omit or shift month-end, leap-day, delayed-payroll, or same-day flows.
- [x] Do not project stale salary or overwrite a distinct household salary stream.
- [x] Do not round safe capacity upward at a safety boundary.
- [x] Do not invent installments; exact offer totals/terms/dates and user limits apply.
- [x] Do not recommend malformed partial payment; exactly two positive payments must
  total the request and complete by deadline.
- [x] Do not issue mutually exclusive, unauthorized, insufficient, redundant, or
  unreplayed spending changes.
- [x] Do not allow contradictions among status, method, plan, safe amount, date,
  changes, and explanation.
- [x] Do not accept missing files/images/rates, duplicate IDs, invalid enums,
  negative amounts, impossible dates, or cross-user evidence.
- [x] Do not make optional model/OCR failure nondeterministic or silently unsafe.
- [x] Do not put sample answers, request-ID branches, credentials, datasets, logs,
  caches, or organizer-only data in the prediction path or code archive.

## 3. Quality checks and final evaluation

| Done | Check | Result | Acceptance evidence |
| --- | --- | --- | --- |
| [x] | QC-01 Contract traceability | PASS | Requirements and flaws map to code/tests/reports. |
| [x] | QC-02 Dataset validation | PASS | All supplied inputs pass strict integrity checks. |
| [x] | QC-03 Full-run contract | PASS | 250/250 ordered rows validate. |
| [x] | QC-04 Independent ledger replay | PASS | Separate arithmetic replay validates baseline capacity and selected plans. |
| [x] | QC-05 Public regression | **PARTIAL** | All fields reported, but stated accuracy targets are not yet met. |
| [x] | QC-06 Cash-state handling | PASS | Status and lifecycle tests pass. |
| [x] | QC-07 Forecasting | PASS | Recurrence, salary, calendar, conflict, and horizon tests pass. |
| [x] | QC-08 Plan search/ranking | PASS | All five outcomes and plan invariants pass. |
| [x] | QC-09 Evidence security | PASS | OCR and adversarial extraction tests pass. |
| [x] | QC-10 Currency | PASS | Exact-date conversion and fail-closed tests pass. |
| [x] | QC-11 Output consistency | PASS | Schema, precision, chronology, and cross-fields pass. |
| [x] | QC-12 Determinism | PASS | Repeated full runs are byte-identical. |
| [x] | QC-13 Leakage/security | PASS | Static scan finds no answer/request branches or secrets. |
| [x] | QC-14 Packaging | PASS | CRC/content checks and clean-extraction run pass. |
| [x] | QC-15 Efficiency/usage | PASS | Runtime and zero-call/token/cost evidence recorded. |

Final tally: **14 PASS, 1 PARTIAL, 0 FAIL**. QC-05 remains deliberately partial;
the strict audit exits nonzero until its published targets pass. See
`quality_report.md` for metrics, limitations, and commands.
