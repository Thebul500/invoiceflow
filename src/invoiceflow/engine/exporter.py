"""Export invoices to CSV and QuickBooks IIF format."""

import csv
import io
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..models import Invoice

logger = logging.getLogger(__name__)


async def _load_invoices(
    db: AsyncSession, invoice_ids: list[int] | None = None
) -> list[Invoice]:
    """Load invoices with line items. If invoice_ids is empty, load all approved."""
    stmt = select(Invoice).options(selectinload(Invoice.line_items))
    if invoice_ids:
        stmt = stmt.where(Invoice.id.in_(invoice_ids))
    else:
        stmt = stmt.where(Invoice.status == "approved")
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def export_csv(
    db: AsyncSession, invoice_ids: list[int] | None = None
) -> str:
    """Export invoices to CSV format. Returns the file path."""
    invoices = await _load_invoices(db, invoice_ids)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_path = Path(settings.export_dir) / f"invoices_{timestamp}.csv"

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Invoice ID", "Invoice Number", "Vendor", "Invoice Date", "Due Date",
        "Subtotal", "Tax", "Total", "Currency", "PO Number", "Category", "Status",
        "Line Description", "Line Qty", "Line Unit Price", "Line Amount",
    ])

    for inv in invoices:
        if inv.line_items:
            for item in inv.line_items:
                writer.writerow([
                    inv.id, inv.invoice_number, inv.vendor_name,
                    inv.invoice_date, inv.due_date, inv.subtotal,
                    inv.tax_amount, inv.total_amount, inv.currency,
                    inv.po_number, inv.category, inv.status,
                    item.description, item.quantity, item.unit_price, item.amount,
                ])
        else:
            writer.writerow([
                inv.id, inv.invoice_number, inv.vendor_name,
                inv.invoice_date, inv.due_date, inv.subtotal,
                inv.tax_amount, inv.total_amount, inv.currency,
                inv.po_number, inv.category, inv.status,
                "", "", "", "",
            ])

    export_path.write_text(output.getvalue())
    logger.info("Exported %d invoices to CSV: %s", len(invoices), export_path)
    return str(export_path)


async def export_iif(
    db: AsyncSession, invoice_ids: list[int] | None = None
) -> str:
    """Export invoices to QuickBooks IIF (Intuit Interchange Format).

    IIF is a tab-delimited format with header rows defining the columns,
    followed by data rows. Bills map to vendor invoices in QuickBooks.
    """
    invoices = await _load_invoices(db, invoice_ids)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_path = Path(settings.export_dir) / f"invoices_{timestamp}.iif"

    lines: list[str] = []
    lines.append("!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tMEMO")
    lines.append("!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tMEMO")
    lines.append("!ENDTRNS")

    for inv in invoices:
        date_str = inv.invoice_date or ""
        total = inv.total_amount or 0.0
        vendor = inv.vendor_name or "Unknown"
        doc_num = inv.invoice_number or ""
        category = inv.category or "General Expense"

        lines.append(
            f"TRNS\tBILL\t{date_str}\tAccounts Payable\t{vendor}\t"
            f"{-total:.2f}\t{doc_num}\t"
        )

        if inv.line_items:
            for item in inv.line_items:
                lines.append(
                    f"SPL\tBILL\t{date_str}\t{category}\t{vendor}\t"
                    f"{item.amount:.2f}\t{doc_num}\t{item.description}"
                )
        else:
            lines.append(
                f"SPL\tBILL\t{date_str}\t{category}\t{vendor}\t"
                f"{total:.2f}\t{doc_num}\t"
            )

        lines.append("ENDTRNS")

    export_path.write_text("\n".join(lines))
    logger.info("Exported %d invoices to IIF: %s", len(invoices), export_path)
    return str(export_path)
