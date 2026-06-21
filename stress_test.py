"""
Stress test — 20,000 invoices across 4 intercompany entities.
Simulates a manufacturing group where divisions bill each other:
  Atlas Raw Materials   → sells raw inputs to Assembly
  Atlas Assembly        → sells finished goods to Distribution
  Atlas Distribution    → sells to external customers (AP to external vendors)
  Atlas Corporate       → charges shared services (IT, HR, rent) to all 3

Intercompany invoices create AP in the buyer and AR in the seller — they must
eliminate on consolidation. This test proves the engine handles:
  - 20k invoices without choking
  - intercompany vs external vendor separation
  - dirty data (name variants, credit memos, partial bills, duplicates)
  - all controls still fire correctly at scale

Run: python stress_test.py
"""
import csv, os, random, datetime as dt, sys, time

random.seed(77)
D = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(D, "_stress")
os.makedirs(TMP, exist_ok=True)

AP_CONTROL = "2000"
BASE = dt.date(2026, 6, 17)

# ── the 4 intercompany entities ──────────────────────────────────────────────
ENTITIES = {
    "RAW":  {"name": "Atlas Raw Materials",   "code": "IC-RAW"},
    "ASSY": {"name": "Atlas Assembly",        "code": "IC-ASSY"},
    "DIST": {"name": "Atlas Distribution",    "code": "IC-DIST"},
    "CORP": {"name": "Atlas Corporate",       "code": "IC-CORP"},
}

# intercompany flows: buyer -> seller
IC_FLOWS = [
    ("ASSY", "RAW",  "Raw materials", (500, 5000)),
    ("DIST", "ASSY", "Finished goods", (2000, 15000)),
    ("RAW",  "CORP", "Shared services", (1000, 8000)),
    ("ASSY", "CORP", "Shared services", (1000, 8000)),
    ("DIST", "CORP", "Shared services", (1000, 8000)),
]

# external vendors per entity
EXT_VENDORS = {
    "RAW":  ["Steelworks Inc", "ChemSupply Co", "Ore Logistics", "PackagingPro",
             "Industrial Parts", "Metal Traders LLC"],
    "ASSY": ["Tooling Masters", "Robot Systems", "Assembly Line Co", "QC Labs",
             "Welding Supply", "Conveyor Corp"],
    "DIST": ["FreightFirst", "Warehouse Solutions", "Last Mile LLC", "Pallet Co",
             "Shrinkwrap Inc", "Cold Chain Corp"],
    "CORP": ["CloudHost Inc", "Office Depot", "ADP Payroll", "Legal & Co",
             "InsureCorp", "Facilities Mgmt"],
}

# dirty-name variants (15% chance)
DIRTY = {
    "Steelworks Inc":  ["Steelworks Inc.", "STEELWORKS INC", "Steelworks Inc "],
    "ChemSupply Co":   ["Chemsupply Co", "ChemSupply  Co"],
    "CloudHost Inc":   ["Cloud Host Inc", "CLOUDHOST INC"],
    "ADP Payroll":     ["ADP  Payroll", "adp payroll"],
}


def dirty(name):
    if name in DIRTY and random.random() < 0.15:
        return random.choice(DIRTY[name])
    return name


def w(name, header, rows):
    with open(os.path.join(TMP, name), "w", newline="", encoding="utf-8") as f:
        cw = csv.writer(f)
        cw.writerow(header)
        cw.writerows(rows)


def main():
    pos, receipts, invoices, payments, gl, vstmt = [], [], [], [], [], []
    eid = 900000
    ic_invoices = 0
    ext_invoices = 0
    traps_planted = 0

    def je(acct, nm, desc, dr, cr, src, ref):
        nonlocal eid
        eid += 1
        gl.append([f"JE{eid}", "2026-06-15", "2026-06", acct, nm, desc,
                   round(dr, 2) if dr else "", round(cr, 2) if cr else "",
                   src, ref])

    N = 20000
    inv_idx = 0
    ap_total = 0.0
    paid_total = 0.0

    # ── generate intercompany invoices (~30% of volume) ──────────────────────
    ic_count = int(N * 0.30)
    for i in range(ic_count):
        flow = random.choice(IC_FLOWS)
        buyer_code, seller_code, desc, (lo, hi) = flow
        seller = ENTITIES[seller_code]["name"]
        amt = round(random.uniform(lo, hi), 2)
        qty = random.randint(1, 100)
        price = round(amt / qty, 2)
        amt = round(qty * price, 2)
        po = f"PO-IC-{inv_idx:06d}"
        inv = f"IC-{inv_idx:06d}"
        due = (BASE + dt.timedelta(days=random.choice([15, 30, 45]))).isoformat()

        pos.append([po, seller, 1, qty, price, "Approved"])
        receipts.append([f"RC-IC-{inv_idx:06d}", po, qty,
                         (BASE - dt.timedelta(days=random.randint(3, 15))).isoformat()])
        invoices.append([inv, seller, po, qty, price, amt,
                         (BASE - dt.timedelta(days=random.randint(1, 20))).isoformat(),
                         due, "Open"])
        ap_total += amt
        je("5000", "Operating Expense", f"IC invoice {inv}", amt, 0,
           f"IC-{buyer_code}", inv)
        je(AP_CONTROL, "Accounts Payable", f"IC invoice {inv}", 0, amt,
           f"IC-{buyer_code}", inv)
        vstmt.append([seller, inv, amt, "2026-06-30"])

        if random.random() < 0.6:
            payments.append([f"PMT-IC-{inv_idx:06d}", seller, inv, amt,
                             (BASE - dt.timedelta(days=random.randint(0, 5))).isoformat()])
            paid_total += amt
            je(AP_CONTROL, "Accounts Payable", f"IC payment {inv}", amt, 0,
               "Payment", inv)
            je("1000", "Cash", f"IC payment {inv}", 0, amt, "Payment", inv)

        inv_idx += 1
        ic_invoices += 1

    # ── generate external vendor invoices (~70% of volume) ───────────────────
    ext_count = N - ic_count
    for i in range(ext_count):
        entity = random.choice(list(EXT_VENDORS.keys()))
        v_clean = random.choice(EXT_VENDORS[entity])
        v = dirty(v_clean)
        qty = random.randint(1, 500)
        price = round(random.uniform(5, 2000), 2)
        amt = round(qty * price, 2)
        po = f"PO-{inv_idx:06d}"
        inv = f"INV-{inv_idx:06d}"
        due = (BASE + dt.timedelta(
            days=random.choice([-30, -10, 0, 15, 30, 45, 60, 90]))).isoformat()

        pos.append([po, v_clean, 1, qty, price, "Approved"])
        receipts.append([f"RC-{inv_idx:06d}", po, qty,
                         (BASE - dt.timedelta(days=random.randint(1, 20))).isoformat()])
        invoices.append([inv, v, po, qty, price, amt,
                         (BASE - dt.timedelta(days=random.randint(1, 25))).isoformat(),
                         due, "Open"])
        ap_total += amt
        je("5000", "Operating Expense", f"Invoice {inv}", amt, 0, "AP", inv)
        je(AP_CONTROL, "Accounts Payable", f"Invoice {inv}", 0, amt, "AP", inv)
        vstmt.append([v_clean, inv, amt, "2026-06-30"])

        if random.random() < 0.45:
            payments.append([f"PMT-{inv_idx:06d}", v, inv, amt,
                             (BASE - dt.timedelta(days=random.randint(0, 10))).isoformat()])
            paid_total += amt
            je(AP_CONTROL, "Accounts Payable", f"Payment {inv}", amt, 0,
               "Payment", inv)
            je("1000", "Cash", f"Payment {inv}", 0, amt, "Payment", inv)

        inv_idx += 1
        ext_invoices += 1

    # ── TRAPS ────────────────────────────────────────────────────────────────

    # 1. IC credit memo + reversal (Atlas Corporate charges ASSY, then reverses)
    ic_seller = ENTITIES["CORP"]["name"]
    invoices.append(["IC-CM-001", ic_seller, "", 1, -7500.00, -7500.00,
                     "2026-06-05", "2026-06-05", "Credit Memo"])
    ap_total -= 7500.00
    je("5000", "Operating Expense", "IC credit memo IC-CM-001", 0, 7500, "IC-ASSY", "IC-CM-001")
    je(AP_CONTROL, "Accounts Payable", "IC credit memo IC-CM-001", 7500, 0, "IC-ASSY", "IC-CM-001")
    invoices.append(["IC-CM-001-REV", ic_seller, "", 1, 7500.00, 7500.00,
                     "2026-06-12", "2026-06-12", "Reversal"])
    ap_total += 7500.00
    je("5000", "Operating Expense", "IC reversal IC-CM-001-REV", 7500, 0, "IC-ASSY", "IC-CM-001-REV")
    je(AP_CONTROL, "Accounts Payable", "IC reversal IC-CM-001-REV", 0, 7500, "IC-ASSY", "IC-CM-001-REV")
    traps_planted += 1

    # 2. Duplicate payment on external vendor (same amount, suffixed invoice)
    dup_v = "Steelworks Inc"
    dup_amt = 12345.67
    invoices.append(["INV-DUP-EXT", dup_v, "PO-000001", 1, dup_amt, dup_amt,
                     "2026-06-03", "2026-06-20", "Open"])
    ap_total += dup_amt
    je("5000", "Operating Expense", "Invoice INV-DUP-EXT", dup_amt, 0, "AP", "INV-DUP-EXT")
    je(AP_CONTROL, "Accounts Payable", "Invoice INV-DUP-EXT", 0, dup_amt, "AP", "INV-DUP-EXT")
    invoices.append(["INV-DUP-EXT-R", dup_v, "PO-000001", 1, dup_amt, dup_amt,
                     "2026-06-04", "2026-06-21", "Open"])
    ap_total += dup_amt
    je("5000", "Operating Expense", "Invoice INV-DUP-EXT-R", dup_amt, 0, "AP", "INV-DUP-EXT-R")
    je(AP_CONTROL, "Accounts Payable", "Invoice INV-DUP-EXT-R", 0, dup_amt, "AP", "INV-DUP-EXT-R")
    payments.append(["PMT-DUP-1", dup_v, "INV-DUP-EXT", dup_amt, "2026-06-13"])
    payments.append(["PMT-DUP-2", dup_v, "INV-DUP-EXT-R", dup_amt, "2026-06-14"])
    paid_total += 2 * dup_amt
    traps_planted += 1

    # 3. Price increase on IC invoice (Raw Materials raises price mid-month)
    pos.append(["PO-IC-PRICE", ENTITIES["RAW"]["name"], 1, 100, 50.00, "Approved"])
    receipts.append(["RC-IC-PRICE", "PO-IC-PRICE", 100, "2026-06-08"])
    invoices.append(["IC-PRICE-1", ENTITIES["RAW"]["name"], "PO-IC-PRICE",
                     50, 50.00, 2500.00, "2026-06-05", "2026-06-25", "Open"])
    ap_total += 2500.00
    je("5000", "Operating Expense", "IC invoice IC-PRICE-1", 2500, 0, "IC-ASSY", "IC-PRICE-1")
    je(AP_CONTROL, "Accounts Payable", "IC invoice IC-PRICE-1", 0, 2500, "IC-ASSY", "IC-PRICE-1")
    invoices.append(["IC-PRICE-2", ENTITIES["RAW"]["name"], "PO-IC-PRICE",
                     50, 65.00, 3250.00, "2026-06-12", "2026-06-30", "Open"])
    ap_total += 3250.00
    je("5000", "Operating Expense", "IC invoice IC-PRICE-2", 3250, 0, "IC-ASSY", "IC-PRICE-2")
    je(AP_CONTROL, "Accounts Payable", "IC invoice IC-PRICE-2", 0, 3250, "IC-ASSY", "IC-PRICE-2")
    traps_planted += 1

    # 4. GRNI — received but never invoiced (external vendor)
    pos.append(["PO-GRNI-001", "Robot Systems", 1, 30, 250.00, "Approved"])
    receipts.append(["RC-GRNI-001", "PO-GRNI-001", 30, "2026-06-09"])
    traps_planted += 1

    # 5. Unapproved PO with invoice
    pos.append(["PO-UNAPP", "Pallet Co", 1, 10, 150.00, "Draft"])
    receipts.append(["RC-UNAPP", "PO-UNAPP", 10, "2026-06-11"])
    invoices.append(["INV-UNAPP", "Pallet Co", "PO-UNAPP", 10, 150.00, 1500.00,
                     "2026-06-07", "2026-06-27", "Open"])
    ap_total += 1500.00
    je("5000", "Operating Expense", "Invoice INV-UNAPP", 1500, 0, "AP", "INV-UNAPP")
    je(AP_CONTROL, "Accounts Payable", "Invoice INV-UNAPP", 0, 1500, "AP", "INV-UNAPP")
    traps_planted += 1

    # 6. Blank due dates (batch)
    for j in range(5):
        invoices.append([f"INV-NODATE-{j}", "Facilities Mgmt", f"PO-{inv_idx + j:06d}",
                         1, 999.99, 999.99, "2026-06-01", "", "Open"])
        ap_total += 999.99
    traps_planted += 1

    # balance GL
    je("1000", "Cash", "Opening cash", 500_000_000, 0, "Opening", "OPEN")
    je("3000", "Equity", "Opening equity", 0, 500_000_000, "Opening", "OPEN")

    w("PO.csv", ["PO_Number", "Vendor", "Line", "Qty_Ordered", "Unit_Price", "Status"], pos)
    w("Receipts.csv", ["Receipt_Number", "PO_Number", "Qty_Received", "Receipt_Date"], receipts)
    w("AP_Invoices.csv",
      ["Invoice_Number", "Vendor", "PO_Number", "Qty_Billed", "Unit_Price",
       "Amount", "Invoice_Date", "Due_Date", "Status"], invoices)
    w("Payments.csv",
      ["Payment_Number", "Vendor", "Invoice_Number", "Amount", "Payment_Date"], payments)
    w("GL.csv",
      ["Entry_ID", "Date", "Period", "Account_Number", "Account_Name",
       "Description", "Debit", "Credit", "Source", "Invoice_Ref"], gl)
    w("Vendor_Statement.csv",
      ["Vendor", "Invoice_Number", "Amount", "Statement_Date"], vstmt)

    print(f"STRESS DATA -> {TMP}")
    print(f"Invoices: {len(invoices)} ({ic_invoices} intercompany, "
          f"{ext_invoices} external, {len(invoices) - ic_invoices - ext_invoices} traps)")
    print(f"POs: {len(pos)} | Receipts: {len(receipts)} | Payments: {len(payments)} "
          f"| GL lines: {len(gl)}")
    print(f"Traps: {traps_planted}")
    print(f"\nIntercompany entities:")
    for k, v in ENTITIES.items():
        print(f"  {v['code']}: {v['name']}")

    # ── run all modules ──────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    sys.path.insert(0, D)
    from ap_match import run_match
    from ap_duplicates import find_duplicates
    from ap_close import run_close
    from ap_vendor_recon import reconcile

    t = time.time()

    print("\n=== 3-WAY MATCH ===")
    m = run_match(data_dir=TMP)
    print(f"Matched: {m['matched_count']}, Exceptions: {m['exception_count']}")
    for e in m["exceptions"][:15]:
        print(f"  [{e['reason']}] {e['invoice']}: {e['detail']}")
    if m["exception_count"] > 15:
        print(f"  ... ({m['exception_count'] - 15} more)")

    print("\n=== DUPLICATES ===")
    dups = find_duplicates(data_dir=TMP)
    print(f"Suspected: {len(dups)}")
    for d in dups[:10]:
        print(f"  [{d['reason']}] {d['vendor']} ${d['amount']:,.2f} {d['invoices']}")

    print("\n=== AP CLOSE ===")
    r = run_close(data_dir=TMP)
    print(f"Subledger: {r['ap_subledger']:,.2f} | GL AP: {r['gl_ap']:,.2f} | "
          f"Variance: {r['variance']:,.2f}")
    print(f"GRNI: {r['grni']:,.2f} ({len(r['grni_items'])} items)")
    print(f"Exceptions: {len(r['exc'])}")
    print("CONTROLS:")
    for n, d, ok in r["checks"]:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    print("\n=== VENDOR RECON ===")
    vr = reconcile(data_dir=TMP)
    ic_vendors = [v for v in vr["vendors"]
                  if any(e["name"] in v["vendor"] for e in ENTITIES.values())]
    ext_vendors = [v for v in vr["vendors"]
                   if not any(e["name"] in v["vendor"] for e in ENTITIES.values())]
    print(f"Total vendors: {vr['vendor_count']} "
          f"({len(ic_vendors)} intercompany, {len(ext_vendors)} external)")
    print(f"Tied: {vr['tied_count']}, Variance: {vr['variance_count']}")

    elapsed = time.time() - t
    print(f"\n=== TIMING: {elapsed:.2f}s for {len(invoices)} invoices ===")


if __name__ == "__main__":
    main()
