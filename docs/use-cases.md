# InvoiceFlow Use Cases

## 1. Accounts Payable Automation

**Problem:** A mid-size company receives 200+ invoices per month across PDF email attachments, scanned images, and vendor portals. The AP team manually keys data into their accounting system, spending 3-4 hours daily on data entry with a 5% error rate.

**Solution:** Deploy InvoiceFlow to watch a shared folder and an IMAP mailbox. Invoices are automatically ingested, parsed by the LLM, validated against purchase orders, and exported to QuickBooks IIF format for direct import.

**Workflow:**

1. Invoices arrive via email or are dropped into `~/.invoiceflow/watch/`
2. InvoiceFlow extracts vendor, line items, amounts, dates, and PO numbers using Ollama
3. Duplicate detection flags previously-processed invoices (fuzzy matching at 85% threshold)
4. PO validation checks vendor name, amount (within $0.01 tolerance), and PO status
5. Expense categorization assigns one of 10 categories based on vendor/line-item keywords
6. AP clerk reviews flagged discrepancies, then approves or rejects via the API
7. Approved invoices are batch-exported to CSV or QuickBooks IIF

```bash
# Set up the watch folder and email polling
invoiceflow watch --dir /mnt/shared/invoices &
invoiceflow email-ingest --host imap.company.com --port 993 \
  --user ap@company.com --password "$IMAP_PASS" --folder INBOX

# Export approved invoices to QuickBooks
curl -X POST http://localhost:8000/api/invoices/export \
  -H "Content-Type: application/json" \
  -d '{"format": "iif", "invoice_ids": []}'
```

**Result:** Data entry time drops from 3-4 hours to 30 minutes of review. Error rate falls below 1%.

---

## 2. Multi-Location Invoice Consolidation

**Problem:** A franchise operator with 12 locations receives invoices from 50+ vendors. Each location forwards invoices differently — some scan to PDF, others photograph with a phone, and some forward emails. The central office needs a unified view.

**Solution:** Each location gets a watch folder or forwards invoices to a dedicated email address. InvoiceFlow processes all formats (PDF, PNG, JPG, TIFF, WEBP, EML) through the same pipeline and stores everything in a single database.

```bash
# Batch process a directory of mixed-format invoices
curl -X POST http://localhost:8000/api/invoices/pipeline/batch \
  -H "Content-Type: application/json" \
  -d '{"directory": "/mnt/location-05/invoices"}'

# Check pipeline stats across all locations
curl http://localhost:8000/api/invoices/pipeline/status
```

**Response:**
```json
{
  "total_invoices": 847,
  "by_status": {
    "pending": 23,
    "approved": 791,
    "rejected": 18,
    "exported": 15
  },
  "duplicates_detected": 34,
  "ollama_model": "qwen2.5:14b",
  "supported_formats": [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp", ".txt", ".eml"]
}
```

---

## 3. Purchase Order Compliance Auditing

**Problem:** A procurement team needs to ensure every invoice matches an approved purchase order before payment. Mismatches in vendor name, amount, or PO status must be flagged for review.

**Solution:** Load purchase orders into InvoiceFlow, then validate each incoming invoice automatically.

```bash
# Create a purchase order
curl -X POST http://localhost:8000/api/purchase-orders \
  -H "Content-Type: application/json" \
  -d '{
    "po_number": "PO-2026-0442",
    "vendor_name": "Acme Industrial Supply",
    "total_amount": 12500.00,
    "description": "Q1 warehouse supplies"
  }'

# Process an invoice and validate against the PO
curl -X POST http://localhost:8000/api/invoices/pipeline/process \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/invoices/acme-march.pdf"}'

# Check validation result
curl -X POST http://localhost:8000/api/invoices/1/validate
```

**Validation response when amount differs:**
```json
{
  "valid": false,
  "discrepancies": [
    "Amount mismatch: invoice $13,200.00 vs PO $12,500.00"
  ],
  "po_number": "PO-2026-0442",
  "po_amount": 12500.00,
  "invoice_amount": 13200.00
}
```

---

## 4. Duplicate Invoice Prevention

**Problem:** Vendors occasionally send the same invoice twice, or different departments submit the same invoice independently. Paying duplicates costs money and creates reconciliation headaches.

**Solution:** InvoiceFlow automatically checks every new invoice against the database using a weighted fuzzy matching algorithm:

- **Invoice number similarity:** 40% weight
- **Vendor name similarity:** 30% weight
- **Amount match:** 30% weight
- **File hash:** Identical files are flagged immediately (SHA-256)

Any match scoring above the configurable threshold (default 85%) is flagged.

```bash
# Check a specific invoice for duplicates
curl -X POST http://localhost:8000/api/invoices/42/duplicates
```

```json
{
  "is_duplicate": true,
  "matches": [
    {
      "invoice_id": 17,
      "invoice_number": "INV-2026-1847",
      "vendor_name": "Office Depot",
      "total_amount": 347.82,
      "similarity_score": 92.5
    }
  ]
}
```

---

## 5. Expense Reporting and Categorization

**Problem:** A finance team needs invoices categorized by expense type for budgeting and reporting, but vendors don't use consistent naming.

**Solution:** InvoiceFlow categorizes each invoice into one of 10 expense categories using keyword matching against vendor names and line item descriptions:

| Category | Example Keywords |
|----------|-----------------|
| Office Supplies | paper, pens, toner, staples |
| IT & Software | license, SaaS, hosting, cloud |
| Professional Services | consulting, legal, audit, accounting |
| Travel & Entertainment | hotel, airfare, meals, rideshare |
| Utilities | electric, water, gas, internet |
| Facilities & Maintenance | repair, janitorial, HVAC, plumbing |
| Marketing & Advertising | ads, campaign, print, social media |
| Shipping & Logistics | freight, courier, postage, FedEx |
| Raw Materials | steel, lumber, fabric, chemicals |
| Insurance | premium, policy, coverage, liability |

Export categorized invoices to CSV for pivot tables and budget analysis:

```bash
invoiceflow export --format csv
```
