"""
AP CONTROLS REGISTER — SOX-style internal controls over the AP close.

Each control is written from a CONTROLLER's point of view: it states the control
objective, the risk it mitigates, the financial-statement assertion it supports,
and produces a deterministic PASS / FAIL / REVIEW result with plain-English flags
a controller can act on before signing the close.

Delivery types:
  AUTOMATED — the engine computes the flag and asserts PASS/FAIL.
  EVIDENCED — the engine produces the exception population a human control reviews.

See CONTROLS.md for the full control narrative, assertion map, and limitations.
Run: python ap_controls.py
"""
import csv, os, datetime as dt
from collections import Counter, defaultdict

D = os.path.dirname(os.path.abspath(__file__))
AP_CONTROL_ACCT = "2000"
GRNI_ACCT = "2150"
CLOSE_PERIOD = "2026-06"
PERIOD_START = dt.date(2026, 6, 1)
PERIOD_END = dt.date(2026, 6, 30)
AS_OF = dt.date(2026, 6, 17)

# A posting to the AP control account is legitimate only if it came from an
# authorized subledger feed. Anything else is a manual / top-side entry.
SUBLEDGER_SOURCES = {"AP", "Payment", "Opening"}
KNOWN_ACCOUNTS = {"1000", "1200", "1210", "2000", "2150", "3000",
                  "4000", "5000", "6000", "6100", "6300"}


def fnum(x):
    try: return float(str(x).replace(",", ""))
    except (ValueError, TypeError): return None


def fdate(x):
    x = (x or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try: return dt.datetime.strptime(x, fmt).date()
        except (ValueError, TypeError): pass
    return None


def load(name, data_dir=None):
    p = os.path.join(data_dir or D, name)
    return list(csv.DictReader(open(p, encoding="utf-8"))) if os.path.exists(p) else []


def _result(passed, n_exceptions):
    """Map an exception count to a controller verdict."""
    if passed is None:
        return "REVIEW" if n_exceptions else "OK"
    return "PASS" if passed else "FAIL"


# ── individual controls — each returns (control_dict) ────────────────────────

def c2_gl_posting_hygiene(gl):
    """C2 — every GL row is structurally valid before any figure is trusted."""
    exc = []
    seen = Counter(r.get("Entry_ID") for r in gl)
    for r in gl:
        eid = (r.get("Entry_ID") or "").strip()
        dr_raw = (r.get("Debit") or "").strip()
        cr_raw = (r.get("Credit") or "").strip()
        dr, cr = fnum(dr_raw) or 0, fnum(cr_raw) or 0
        if not eid:
            exc.append(f"Blank Entry_ID on a GL line")
        elif seen[eid] > 1:
            exc.append(f"Duplicate Entry_ID {eid} ({seen[eid]} lines)")
        if dr_raw and cr_raw and dr and cr:
            exc.append(f"{eid}: both Debit and Credit populated — malformed line")
        if not dr_raw and not cr_raw:
            exc.append(f"{eid}: neither Debit nor Credit — no amount")
        if str(r.get("Account_Number")).strip() not in KNOWN_ACCOUNTS:
            exc.append(f"{eid}: unrecognized account {r.get('Account_Number')}")
    return {
        "id": "C2", "name": "GL posting hygiene (entry-level data integrity)",
        "objective": "Every GL row is structurally valid — unique Entry_ID, exactly "
                     "one of Debit/Credit populated, recognized account — before any "
                     "AP figure derived from the ledger is relied upon.",
        "assertion": "accuracy/valuation", "delivery": "AUTOMATED",
        "result": _result(len(exc) == 0, len(exc)),
        "detail": f"{len(exc)} malformed GL line(s)",
        "exceptions": exc[:25],
    }


def c4_duplicate_keys(invs, pays, gl, pos):
    """C4 — natural primary keys are unique across subledgers and the GL."""
    exc = []
    for table, rows, key in [
        ("AP_Invoices", invs, "Invoice_Number"),
        ("Payments", pays, "Payment_Number"),
        ("GL", gl, "Entry_ID"),
    ]:
        c = Counter((r.get(key) or "").strip() for r in rows)
        for val, n in c.items():
            if val and n > 1:
                exc.append(f"DUPLICATE KEY in {table} — {key} '{val}' appears {n} times")
    # PO + Line composite
    poline = Counter((r.get("PO_Number"), r.get("Line")) for r in pos)
    for (po, ln), n in poline.items():
        if n > 1:
            exc.append(f"DUPLICATE KEY in PO — ({po}, line {ln}) appears {n} times")
    return {
        "id": "C4", "name": "Unique primary keys (Invoice#, Payment#, Entry_ID, PO+Line)",
        "objective": "The natural key of each subledger and the GL is unique, so no "
                     "transaction is silently counted twice.",
        "assertion": "accuracy/valuation", "delivery": "AUTOMATED",
        "result": _result(len(exc) == 0, len(exc)),
        "detail": f"{len(exc)} duplicate key(s)",
        "exceptions": exc[:25],
    }


def c5_referential_integrity(invs, pays, pos, receipts):
    """C5 — every payment ties to an invoice, every invoice to a vendor,
    every PO reference resolves."""
    inv_nums = {(r.get("Invoice_Number") or "").strip() for r in invs}
    po_nums = {(r.get("PO_Number") or "").strip() for r in pos}
    exc = []
    for p in pays:
        ref = (p.get("Invoice_Number") or "").strip()
        if ref not in inv_nums:
            exc.append(f"ORPHAN PAYMENT — {p.get('Payment_Number')} {p.get('Vendor')} "
                       f"${fnum(p.get('Amount')) or 0:,.2f} references invoice "
                       f"'{ref}' not in the subledger")
    for inv in invs:
        if not (inv.get("Vendor") or "").strip():
            exc.append(f"MISSING VENDOR — invoice {inv.get('Invoice_Number')} has no vendor")
    for inv in invs:
        ref = (inv.get("PO_Number") or "").strip()
        if ref and ref not in po_nums:
            exc.append(f"ORPHAN PO REF — invoice {inv.get('Invoice_Number')} "
                       f"cites PO '{ref}' not in the PO master")
    return {
        "id": "C5", "name": "Referential integrity (payment->invoice->vendor, ->PO)",
        "objective": "Every payment references an existing invoice, every invoice "
                     "carries a vendor, and PO references resolve — so match and GRNI "
                     "operate on a complete linked population.",
        "assertion": "existence/occurrence", "delivery": "AUTOMATED",
        "result": _result(len(exc) == 0, len(exc)),
        "detail": f"{len(exc)} referential break(s)",
        "exceptions": exc[:25],
    }


def c8_manual_je_to_ap_control(gl, invs):
    """C8 — manual / top-side JEs to the AP control account that bypass the
    subledger. THE classic management-override / audit red flag."""
    inv_nums = {(r.get("Invoice_Number") or "").strip() for r in invs}
    flagged = []
    net = 0.0
    for r in gl:
        if str(r.get("Account_Number")).strip() != AP_CONTROL_ACCT:
            continue
        src = (r.get("Source") or "").strip()
        ref = (r.get("Invoice_Ref") or "").strip()
        bad_source = src not in SUBLEDGER_SOURCES
        bad_ref = (not ref) or (ref not in inv_nums)
        if bad_source or bad_ref:
            amt = (fnum(r.get("Credit")) or 0) - (fnum(r.get("Debit")) or 0)
            net += amt
            reason = []
            if bad_source: reason.append(f"Source='{src or 'NONE'}' not a subledger feed")
            if not ref: reason.append("no Invoice_Ref")
            elif ref not in inv_nums: reason.append(f"Invoice_Ref '{ref}' not in subledger")
            flagged.append(f"MANUAL JE TO AP CONTROL — Entry {r.get('Entry_ID')} "
                           f"{r.get('Date')}, net {amt:+,.2f}; {'; '.join(reason)}. "
                           f"Obtain JE approval before sign-off.")
    return {
        "id": "C8", "name": "Manual / top-side JE to AP control account (subledger bypass)",
        "objective": "Every posting to acct 2000 must originate from an authorized "
                     "subledger feed (AP, Payment, Opening) and carry a resolvable "
                     "invoice reference. Direct manual entries that bypass the subledger "
                     "are itemized for controller sign-off — the classic override risk.",
        "assertion": "existence/occurrence", "delivery": "AUTOMATED",
        "result": _result(len(flagged) == 0, len(flagged)),
        "detail": f"{len(flagged)} manual JE(s) to acct 2000 netting {net:+,.2f}",
        "exceptions": flagged[:25],
    }


def c9_two_way_coverage(invs, pays, gl):
    """C9 — two-way population tie beneath the net-balance reconciliation."""
    paid = defaultdict(float)
    for p in pays:
        paid[(p.get("Invoice_Number") or "").strip()] += fnum(p.get("Amount")) or 0
    open_invs = {(inv.get("Invoice_Number") or "").strip()
                 for inv in invs
                 if (fnum(inv.get("Amount")) or 0) - paid.get((inv.get("Invoice_Number") or "").strip(), 0) > 0.005}
    gl_refs = {(r.get("Invoice_Ref") or "").strip() for r in gl
               if str(r.get("Account_Number")).strip() == AP_CONTROL_ACCT
               and (r.get("Source") or "").strip() == "AP"}
    in_sub_not_gl = open_invs - gl_refs
    in_gl_not_sub = {r for r in gl_refs if r} - {(inv.get("Invoice_Number") or "").strip() for inv in invs}
    exc = ([f"IN SUBLEDGER, NOT GL — open invoice {x} has no AP-source GL credit" for x in list(in_sub_not_gl)[:12]]
           + [f"IN GL, NOT SUBLEDGER — GL credit refs invoice {x} not in subledger" for x in list(in_gl_not_sub)[:12]])
    return {
        "id": "C9", "name": "Subledger-to-GL coverage completeness (two-way tie)",
        "objective": "Each open invoice has a matching AP-source GL credit and each "
                     "AP-source GL credit maps back to an invoice — catching offsetting "
                     "errors that net to zero and hide under the single-balance tie.",
        "assertion": "completeness", "delivery": "EVIDENCED",
        "result": _result(None, len(exc)),
        "detail": f"{len(in_sub_not_gl)} in-subledger-not-GL, {len(in_gl_not_sub)} in-GL-not-subledger",
        "exceptions": exc,
    }


def c10_cutoff_integrity(gl, invs):
    """C10 — postings land in the correct period; no AP-2000 posting outside the window."""
    exc = []
    for r in gl:
        d = fdate(r.get("Date"))
        period = (r.get("Period") or "").strip()
        if d and period and d.strftime("%Y-%m") != period:
            exc.append(f"PERIOD MISMATCH — Entry {r.get('Entry_ID')} dated {r.get('Date')} "
                       f"tagged period {period}")
        if str(r.get("Account_Number")).strip() == AP_CONTROL_ACCT and d:
            if d < PERIOD_START or d > PERIOD_END:
                exc.append(f"OUT-OF-WINDOW — AP-2000 entry {r.get('Entry_ID')} dated "
                           f"{r.get('Date')} outside close {CLOSE_PERIOD}")
    return {
        "id": "C10", "name": "Period / cutoff integrity of GL & AP postings",
        "objective": "Every GL entry's posting date falls within its stated period and "
                     "the close window, so liabilities and disbursements land in the "
                     "correct month.",
        "assertion": "cutoff", "delivery": "AUTOMATED",
        "result": _result(len(exc) == 0, len(exc)),
        "detail": f"{len(exc)} cutoff exception(s)",
        "exceptions": exc[:25],
    }


def c12_grni_booked(gl, invs, pos, receipts):
    """C12 — the GRNI accrual the engine computes is actually booked to GL 2150."""
    invoiced_pos = {(inv.get("PO_Number") or "").strip() for inv in invs}
    recv = defaultdict(float)
    for r in receipts:
        recv[(r.get("PO_Number") or "").strip()] += fnum(r.get("Qty_Received")) or 0
    po_price = {(r.get("PO_Number") or "").strip(): fnum(r.get("Unit_Price")) or 0 for r in pos}
    computed = round(sum(recv[po] * po_price.get(po, 0)
                         for po in recv if po and po not in invoiced_pos), 2)
    gl_grni = round(sum((fnum(r.get("Credit")) or 0) - (fnum(r.get("Debit")) or 0)
                        for r in gl if str(r.get("Account_Number")).strip() == GRNI_ACCT), 2)
    booked = abs(computed - gl_grni) < 0.01
    return {
        "id": "C12", "name": "GRNI accrual booked to GL 2150 (unrecorded-liability check)",
        "objective": "Goods received but not invoiced are quantified AND accrued to the "
                     "GL — the #1 AP audit risk (completeness of liabilities). The engine "
                     "ties its computed GRNI to the GL 2150 credit and fails when unbooked.",
        "assertion": "completeness", "delivery": "AUTOMATED",
        "result": _result(booked, 0 if booked else 1),
        "detail": f"computed {computed:,.2f} vs GL 2150 {gl_grni:,.2f}"
                  + ("" if booked else " — UNRECORDED LIABILITY"),
        "exceptions": [] if booked else
            [f"GRNI of {computed:,.2f} computed from receipts is NOT booked to GL 2150 "
             f"(GL shows {gl_grni:,.2f}). Record the accrual before close."],
    }


def c21_segregation_of_duties(gl):
    """C21 — single-source prepare-and-pay on the AP control account (EVIDENCED).
    Source is the only preparer/approver proxy in this dataset — see limitations."""
    by_ref = defaultdict(list)
    for r in gl:
        if str(r.get("Account_Number")).strip() == AP_CONTROL_ACCT:
            by_ref[(r.get("Invoice_Ref") or "").strip()].append(r)
    exc = []
    for ref, legs in by_ref.items():
        if not ref:
            continue
        sources = {(l.get("Source") or "").strip() for l in legs}
        non_sub = sources - SUBLEDGER_SOURCES
        if len(legs) >= 2 and non_sub and len(sources) == 1:
            exc.append(f"SELF-CLEARED — invoice {ref}: both legs posted by single "
                       f"non-subledger source {sources}")
    return {
        "id": "C21", "name": "Segregation of duties — single-source prepare-and-pay (proxy)",
        "objective": "No single source both raises and clears an AP liability. Uses the "
                     "GL Source field as a preparer/approver proxy (see limitations — "
                     "Source is not a user ID).",
        "assertion": "existence/occurrence", "delivery": "EVIDENCED",
        "result": _result(None, len(exc)),
        "detail": f"{len(exc)} self-cleared item(s) for review",
        "exceptions": exc[:25],
    }


def run_controls(data_dir=None):
    """Run the full AP controls register. Returns dict with register + counts."""
    d = data_dir or D
    invs = load("AP_Invoices.csv", d)
    pays = load("Payments.csv", d)
    gl = load("GL.csv", d)
    pos = load("PO.csv", d)
    receipts = load("Receipts.csv", d)
    if not invs or not gl:
        raise ValueError("AP_Invoices.csv and GL.csv must exist and be non-empty in " + d)

    register = [
        c2_gl_posting_hygiene(gl),
        c4_duplicate_keys(invs, pays, gl, pos),
        c5_referential_integrity(invs, pays, pos, receipts),
        c8_manual_je_to_ap_control(gl, invs),
        c9_two_way_coverage(invs, pays, gl),
        c10_cutoff_integrity(gl, invs),
        c12_grni_booked(gl, invs, pos, receipts),
        c21_segregation_of_duties(gl),
    ]
    fails = sum(1 for c in register if c["result"] == "FAIL")
    reviews = sum(1 for c in register if c["result"] == "REVIEW")
    return {"register": register, "fail_count": fails, "review_count": reviews}


if __name__ == "__main__":
    r = run_controls()
    print("AP CONTROLS REGISTER — close", CLOSE_PERIOD, "(SYNTHETIC)\n")
    for c in r["register"]:
        tag = {"PASS": "[PASS]", "FAIL": "[FAIL]",
               "REVIEW": "[REVIEW]", "OK": "[OK]"}[c["result"]]
        print(f"{tag} {c['id']} {c['name']}")
        print(f"        assertion: {c['assertion']} | {c['delivery']} | {c['detail']}")
        for e in c["exceptions"][:5]:
            print(f"          - {e}")
        if len(c["exceptions"]) > 5:
            print(f"          ... ({len(c['exceptions']) - 5} more)")
    print(f"\nSUMMARY: {r['fail_count']} FAIL, {r['review_count']} REVIEW, "
          f"{len(r['register']) - r['fail_count'] - r['review_count']} PASS/OK")
    print("CONTROLS PASS — ready for controller sign-off" if r["fail_count"] == 0
          else "** CONTROL FAILURES — resolve before sign-off **")
