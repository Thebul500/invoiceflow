"""Purchase order validation — compares invoice data against POs and flags discrepancies."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Invoice, PurchaseOrder
from ..schemas import ValidationResult

logger = logging.getLogger(__name__)

AMOUNT_TOLERANCE = 0.01


async def validate_against_po(
    invoice: Invoice, db: AsyncSession
) -> ValidationResult:
    """Validate an invoice against its referenced purchase order.

    Checks:
    - PO exists
    - Vendor name matches
    - Total amount within tolerance
    - PO is still open
    """
    if not invoice.po_number:
        return ValidationResult(
            valid=True, discrepancies=["No PO number on invoice — skipped PO validation"]
        )

    stmt = select(PurchaseOrder).where(PurchaseOrder.po_number == invoice.po_number)
    result = await db.execute(stmt)
    po = result.scalar_one_or_none()

    if po is None:
        return ValidationResult(
            valid=False,
            discrepancies=[f"PO {invoice.po_number} not found in system"],
            po_number=invoice.po_number,
            invoice_amount=invoice.total_amount,
        )

    discrepancies: list[str] = []

    if po.status != "open":
        discrepancies.append(f"PO {po.po_number} status is '{po.status}', expected 'open'")

    if invoice.vendor_name and po.vendor_name:
        inv_vendor = invoice.vendor_name.strip().lower()
        po_vendor = po.vendor_name.strip().lower()
        if inv_vendor != po_vendor:
            discrepancies.append(
                f"Vendor mismatch: invoice='{invoice.vendor_name}', PO='{po.vendor_name}'"
            )

    if invoice.total_amount is not None and po.total_amount is not None:
        diff = abs(invoice.total_amount - po.total_amount)
        if diff > AMOUNT_TOLERANCE:
            discrepancies.append(
                f"Amount mismatch: invoice=${invoice.total_amount:.2f}, "
                f"PO=${po.total_amount:.2f} (diff=${diff:.2f})"
            )

    return ValidationResult(
        valid=len(discrepancies) == 0,
        discrepancies=discrepancies,
        po_number=po.po_number,
        po_amount=po.total_amount,
        invoice_amount=invoice.total_amount,
    )
