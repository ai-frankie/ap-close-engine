"""Generate synthetic AP data: POs, receipts, invoices, payments, GL, vendor statement.
Deterministic (seeded). Self-consistent so the close ties, with known planted breaks.
Run: python gen_data.py
"""
import csv, os, random, datetime as dt

random.seed(11)
D = os.path.dirname(os.path.abspath(__file__))
AP_CONTROL = "2000"
GRNI_ACCT = "2150"
VENDORS = ["Acme Corp", "Globex Inc", "Initech LLC", "Umbrella Ltd",
           "Stark Supply", "Wayne Materials", "Soylent Co", "Hooli Tech"]


def w(name, header, rows):
    with open(os.path.join(D, name), "w", newline="", encoding="utf-8") as f:
        cw = csv.writer(f)
        cw.writerow(header)
        cw.writerows(rows)


def main():
    pos, receipts, invoices, payments, gl, vstmt = [], [], [], [], [], []
    eid = 700000

    def je(acct, nm, desc, dr, cr, src, ref):
        nonlocal eid
        eid += 1
        gl.append([f"JE{eid}", "2026-06-15", "2026-06", acct, nm, desc,
                   round(dr, 2) if dr else "", round(cr, 2) if cr else "",
                   src, ref])

    base = dt.date(2026, 6, 17)
    N = 120
    ap_sub_total = 0.0
    paid_total = 0.0

    for i in range(N):
        v = random.choice(VENDORS)
        po = f"PO-{i:05d}"
        qty = random.randint(5, 200)
        price = round(random.uniform(10, 500), 2)
        amt = round(qty * price, 2)
        due = (base + dt.timedelta(days=random.choice([-20, 5, 30, 45, 60]))).isoformat()
        inv = f"INV-{1000 + i}"

        # PO (single-line, all approved for the clean population)
        pos.append([po, v, 1, qty, price, "Approved"])
        # full receipt
        receipts.append([f"RC-{i:05d}", po, qty, "2026-06-10"])
        # invoice matches PO exactly
        invoices.append([inv, v, po, qty, price, amt,
                         "2026-06-01", due, "Open"])
        ap_sub_total += amt
        # GL: DR Expense / CR AP control, with invoice ref
        je("5000", "Operating Expense", f"Invoice {inv}", amt, 0, "AP", inv)
        je(AP_CONTROL, "Accounts Payable", f"Invoice {inv}", 0, amt, "AP", inv)
        # vendor statement mirrors open invoices
        vstmt.append([v, inv, amt, "2026-06-30"])

        # pay ~half (clean payments, properly referenced)
        if random.random() < 0.5:
            payments.append([f"PMT-{i:05d}", v, inv, amt, "2026-06-12"])
            paid_total += amt
            # GL: DR AP / CR Cash
            je(AP_CONTROL, "Accounts Payable", f"Payment {inv}", amt, 0, "Payment", inv)
            je("1000", "Cash", f"Payment {inv}", 0, amt, "Payment", inv)

    # ---- PLANTED BREAK 1: duplicate payment ----
    # same vendor + amount, invoice suffixed with -R
    dv, da = VENDORS[0], 4321.00
    pos.append(["PO-2001", dv, 1, 1, da, "Approved"])
    receipts.append(["RC-2001", "PO-2001", 1, "2026-06-09"])
    invoices.append(["INV-2001", dv, "PO-2001", 1, da, da,
                      "2026-06-02", "2026-06-20", "Open"])
    ap_sub_total += da
    je("5000", "Operating Expense", "Invoice INV-2001", da, 0, "AP", "INV-2001")
    je(AP_CONTROL, "Accounts Payable", "Invoice INV-2001", 0, da, "AP", "INV-2001")
    vstmt.append([dv, "INV-2001", da, "2026-06-30"])
    # the duplicate: same vendor, same amount, suffixed invoice
    invoices.append(["INV-2001-R", dv, "PO-2001", 1, da, da,
                      "2026-06-03", "2026-06-21", "Open"])
    ap_sub_total += da
    je("5000", "Operating Expense", "Invoice INV-2001-R", da, 0, "AP", "INV-2001-R")
    je(AP_CONTROL, "Accounts Payable", "Invoice INV-2001-R", 0, da, "AP", "INV-2001-R")
    payments.append(["PMT-9001", dv, "INV-2001", da, "2026-06-13"])
    payments.append(["PMT-9002", dv, "INV-2001-R", da, "2026-06-14"])
    paid_total += 2 * da

    # ---- PLANTED BREAK 2: 3-way match price variance ----
    # invoice price 130 vs PO price 100 (30% over tolerance)
    pos.append(["PO-3001", VENDORS[1], 1, 10, 100.00, "Approved"])
    receipts.append(["RC-3001", "PO-3001", 10, "2026-06-10"])
    invoices.append(["INV-3001", VENDORS[1], "PO-3001", 10, 130.00, 1300.00,
                      "2026-06-05", "2026-06-25", "Open"])
    ap_sub_total += 1300.00
    je("5000", "Operating Expense", "Invoice INV-3001", 1300, 0, "AP", "INV-3001")
    je(AP_CONTROL, "Accounts Payable", "Invoice INV-3001", 0, 1300, "AP", "INV-3001")
    vstmt.append([VENDORS[1], "INV-3001", 1300.00, "2026-06-30"])

    # ---- PLANTED BREAK 3: GRNI — goods received, NOT invoiced ----
    # 20 units @ 75 = 1,500 accrual needed (not in GL, not in invoices)
    pos.append(["PO-4001", VENDORS[2], 1, 20, 75.00, "Approved"])
    receipts.append(["RC-4001", "PO-4001", 20, "2026-06-11"])
    # no invoice, no GL entry, no payment — the gap the reviewer must catch

    # ---- PLANTED BREAK 4: unapproved PO (PO exists but not approved) ----
    pos.append(["PO-5001", VENDORS[3], 1, 5, 200.00, "Draft"])
    receipts.append(["RC-5001", "PO-5001", 5, "2026-06-12"])
    invoices.append(["INV-5001", VENDORS[3], "PO-5001", 5, 200.00, 1000.00,
                      "2026-06-06", "2026-06-26", "Open"])
    ap_sub_total += 1000.00
    je("5000", "Operating Expense", "Invoice INV-5001", 1000, 0, "AP", "INV-5001")
    je(AP_CONTROL, "Accounts Payable", "Invoice INV-5001", 0, 1000, "AP", "INV-5001")

    # balance the GL: opening cash + equity
    total_expense = round(ap_sub_total, 2)
    je("1000", "Cash", "Opening cash", 5_000_000, 0, "Opening", "OPEN")
    je("3000", "Equity", "Opening equity", 0, 5_000_000, "Opening", "OPEN")

    w("PO.csv",
      ["PO_Number", "Vendor", "Line", "Qty_Ordered", "Unit_Price", "Status"], pos)
    w("Receipts.csv",
      ["Receipt_Number", "PO_Number", "Qty_Received", "Receipt_Date"], receipts)
    w("AP_Invoices.csv",
      ["Invoice_Number", "Vendor", "PO_Number", "Qty_Billed", "Unit_Price",
       "Amount", "Invoice_Date", "Due_Date", "Status"], invoices)
    w("Payments.csv",
      ["Payment_Number", "Vendor", "Invoice_Number", "Amount", "Payment_Date"],
      payments)
    w("GL.csv",
      ["Entry_ID", "Date", "Period", "Account_Number", "Account_Name",
       "Description", "Debit", "Credit", "Source", "Invoice_Ref"], gl)
    w("Vendor_Statement.csv",
      ["Vendor", "Invoice_Number", "Amount", "Statement_Date"], vstmt)

    ap_sub_total = round(ap_sub_total, 2)
    paid_total = round(paid_total, 2)
    print(f"Generated: {len(invoices)} invoices, {len(pos)} POs, "
          f"{len(receipts)} receipts, {len(payments)} payments, {len(gl)} GL lines")
    print(f"AP subledger (gross invoices): {ap_sub_total:,.2f}")
    print(f"Payments applied: {paid_total:,.2f}")
    print(f"Open AP (invoices - payments): {ap_sub_total - paid_total:,.2f}")
    print(f"GRNI expected: 1,500.00 (PO-4001: 20 x 75, received, no invoice)")
    print(f"Planted breaks: duplicate payment (INV-2001/INV-2001-R), "
          f"price variance (INV-3001), GRNI omission (PO-4001), "
          f"unapproved PO (PO-5001/INV-5001)")


if __name__ == "__main__":
    main()
