# AP Internal Controls — Controller's Reference

This document describes the SOX-style internal controls the AP close engine performs, written for a **controller reviewing a month-end close package**. Every control states its objective, the risk it mitigates, the financial-statement assertion it supports, and the exact flag it raises.

All data is **synthetic** (fictional vendors). The point is the *controls logic*, not the numbers.

---

## How to read this document

- **AUTOMATED** — the engine computes the test and returns **PASS / FAIL**. A FAIL must be resolved before sign-off.
- **EVIDENCED** — the engine produces the **exception population** a human control reviews. It returns **OK** (nothing to review) or **REVIEW** (items for controller judgment). It does not auto-fail, because the judgment is the controller's.
- Financial-statement **assertions**: *completeness* (nothing omitted), *existence/occurrence* (it really happened), *accuracy/valuation* (right amount), *cutoff* (right period), *presentation* (shown correctly).

Run the register with:

```bash
python ap_controls.py
```

## Close package reading order

A controller signs from the bottom up — you cannot trust a reconciliation built on a corrupt ledger. So the engine is ordered:

1. **Data integrity** — is the ledger and subledger feed even clean? (C2, C4, C5)
2. **Reconciliation** — does the subledger tie to the GL, and is every GL posting authorized? (C7, **C8**, C9, C10)
3. **Completeness & cutoff** — are all liabilities recorded in the right period? (C12, GRNI)
4. **AP process** — match, duplicate payments, aging (C11, three-way match, duplicate detection)
5. **Review & segregation of duties** — independent re-performance (C21, the reviewer)

---

## Section 1 — Data integrity controls

These are the bedrock. Every financial figure sits on top of them.

### C2 — GL posting hygiene · *accuracy/valuation* · AUTOMATED
**Objective:** every GL row is structurally valid before any AP figure derived from the ledger is relied upon — unique non-blank `Entry_ID`, exactly one of Debit/Credit populated, a recognized account.
**Risk:** a malformed ledger line silently corrupts every total built from it.
**Flag:** `C2: {n} malformed GL line(s)` — blank/duplicate Entry_ID, both-or-neither Debit/Credit, unknown account. PASS when n = 0.

### C4 — Unique primary keys · *accuracy/valuation* · AUTOMATED
**Objective:** the natural key of each subledger and the GL is unique — no duplicate `Invoice_Number`, `Payment_Number`, `Entry_ID`, or `PO_Number+Line`.
**Risk:** a duplicated key double-counts a transaction — the most common cause of an overstated liability or a double payment.
**Flag:** `DUPLICATE KEY in {table} — {value} appears {n} times`. FAIL on any GL or payment duplicate.

### C5 — Referential integrity · *existence/occurrence* · AUTOMATED
**Objective:** every payment references an existing invoice, every invoice carries a vendor, and every PO reference resolves to the PO master.
**Risk:** an orphan payment (cash out with no invoice behind it) is a fraud and error red flag; a vendorless invoice breaks vendor reporting.
**Flag:** `ORPHAN PAYMENT`, `MISSING VENDOR`, `ORPHAN PO REF`. FAIL on any orphan payment or vendorless invoice.

---

## Section 2 — Reconciliation controls

### C7 — AP subledger-to-GL control account tie · *completeness* · AUTOMATED *(in `ap_close.py`)*
**Objective:** the open-AP subledger ties to the GL AP control account (acct 2000, credit-normal), with any variance fully explained and a **zero unexplained residual** before sign-off.
**Flag:** `AP CONTROL DOES NOT TIE — GL 2000 $X, subledger $Y, unexplained residual $Z`.

### C8 — Manual / top-side JE to the AP control account · *existence/occurrence* · AUTOMATED
> **This is the control most worth reading.** See the deep-dive below.

**Objective:** every posting to acct 2000 must originate from an authorized subledger feed (`Source` ∈ {AP, Payment, Opening}) **and** carry a resolvable invoice reference. Direct manual / top-side journal entries that bypass the subledger are itemized for controller sign-off.
**Risk:** the classic **management-override** red flag. A manual credit straight to the AP control account — no invoice, no vendor, no approval trail — is exactly how a liability is understated or a fictitious payable is parked. External auditors specifically hunt for these.
**Flag (per entry):**
```
MANUAL JE TO AP CONTROL — Entry JE700381 2026-06-15, net +5,000.00;
Source='Manual JE' not a subledger feed; no Invoice_Ref.
Obtain JE approval before sign-off.
```
PASS only when zero manual entries hit acct 2000.

### C9 — Two-way coverage completeness · *completeness* · EVIDENCED
**Objective:** each open invoice has a matching AP-source GL credit, and each AP-source GL credit maps back to an open invoice.
**Risk:** offsetting errors that **net to zero** hide under the single-balance tie (C7) — an invoice missing from the GL plus an unsupported GL credit of equal size cancel out. The two-way population check surfaces them.
**Flag:** `IN SUBLEDGER, NOT GL` / `IN GL, NOT SUBLEDGER` lists for review.

### C10 — Period / cutoff integrity · *cutoff* · AUTOMATED
**Objective:** every GL entry's posting `Date` falls within its stated `Period` and the close window, and no AP-2000 posting falls outside the period.
**Risk:** back-dated or post-period entries push liabilities and disbursements into the wrong month — a cutoff misstatement.
**Flag:** `PERIOD MISMATCH` (Date vs Period) and `OUT-OF-WINDOW` (AP-2000 dated outside the close). FAIL on any out-of-window AP-2000 entry.

---

## Section 3 — Completeness & cutoff

### C12 — GRNI accrual booked to GL 2150 · *completeness* · AUTOMATED
**Objective:** goods received but not invoiced are quantified **and accrued to the GL**. The engine ties its computed GRNI to the GL 2150 credit and fails when the accrual is unbooked.
**Risk:** **completeness of liabilities is the #1 AP audit assertion.** Goods received with no invoice and no accrual = an unrecorded liability and understated expense.
**Flag:**
```
GRNI of 1,500.00 computed from receipts is NOT booked to GL 2150
(GL shows 0.00). Record the accrual before close.
```

---

## Section 4 — AP process controls *(separate modules)*

- **Three-way match** (`ap_match.py`) — PO ↔ receipt ↔ invoice: `NO_PO`, `PO_NOT_APPROVED`, `NO_RECEIPT`, `OVER_BILLED`, `PRICE_VARIANCE`. *Existence/occurrence + accuracy.*
- **Duplicate-payment detection** (`ap_duplicates.py`) — same vendor + amount with normalized invoice number or near payment dates; capped pairwise comparisons, logged never silently truncated. *Existence/occurrence.*
- **Aging schedule foots to subledger** (`ap_close.py` C-row) — buckets sum exactly to the open-AP subledger. *Presentation.*
- **Negative-balance / overpayment** (`ap_close.py`) — open invoice balance below zero = overpaid. *Accuracy/valuation.*
- **Vendor-statement reconciliation** (`ap_vendor_recon.py`) — our open AP vs the vendor's open items, invoice-level, surfacing in-transit and unapplied timing differences. *Completeness.*

## Section 5 — Review & segregation of duties

### C21 — Single-source prepare-and-pay (SoD proxy) · *existence/occurrence* · EVIDENCED
**Objective:** no single source both raises and clears an AP liability.
**Flag:** `SELF-CLEARED` items where one non-subledger source posts both legs to acct 2000.
**Honest limitation:** the only preparer/approver signal in this dataset is the GL `Source` field — it is **not a user ID**. A production control would key on the system user who entered vs. who approved each JE. This ships as EVIDENCED with that limitation stated, not as a hard pass/fail.

### Independent re-performance (`ap_review.py`)
A separate reviewer recomputes the truth from raw data and audits a *prepared* workbook, catching planted preparer errors (doubled subledger, omitted GRNI, missed duplicate) before they reach the GL. **Segregation of duties, in code.**

---

## The manual-JE-to-control-account control, in depth

Why it gets its own section: in a real close, the subledger feeds the GL automatically — AP invoices credit the control account, payments debit it. Those postings carry an invoice reference and a system `Source`. A **manual journal entry posted directly to the AP control account** breaks that chain: it has no invoice behind it and a `Source` that isn't a subledger feed.

That is precisely the entry an auditor circles, because it is how the control account is adjusted *outside the disciplined subledger process* — to hit a target, hide a variance, or park a fictitious payable. The engine's test is deliberately strict:

```python
flag every GL row where Account_Number == "2000"
  AND ( Source not in {"AP", "Payment", "Opening"}
        OR Invoice_Ref is blank
        OR Invoice_Ref not found in the AP subledger )
```

The included synthetic data seeds one such entry (a $5,000 top-side credit, `Source='Manual JE'`, no reference) so the control demonstrably fires. Remove it and C8 passes.

---

## Assertion coverage map

| Assertion | Controls |
|---|---|
| Completeness | C7 (tie), C9 (two-way), C12 (GRNI), vendor-statement recon |
| Existence / occurrence | C5 (referential), **C8 (manual JE)**, C21 (SoD), three-way match |
| Accuracy / valuation | C2 (hygiene), C4 (keys), negative-balance, price variance |
| Cutoff | C10 (period), receipt cutoff |
| Presentation | aging foots, due-date completeness |

## Known limitations & data-coverage gaps

This is a controls **demonstration on synthetic data**, not a production GRC system. It cannot perform controls that require fields this dataset does not carry:

- **No user IDs** — segregation of duties uses the `Source` field as a proxy (C21), not the actual preparer/approver. EVIDENCED only.
- **No vendor master** — name-variant and one-time-vendor detection would be heuristic; not implemented as a hard control.
- **No bank-detail change log** — payment-redirection fraud (a key real-world AP control) is out of scope.
- **Money is float, rounded to the cent** — not `decimal.Decimal`.

These gaps are stated plainly because an honest controls inventory names what it does *not* cover.
