"""Fuzzy duplicate detection for invoices.

Uses rapidfuzz to compare invoice numbers, vendor names, and amounts
against existing invoices in the database.
"""

import logging

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Invoice
from ..schemas import DuplicateCheckResult, DuplicateMatch

logger = logging.getLogger(__name__)


def _compute_similarity(inv_a: Invoice, inv_b: Invoice) -> float:
    """Compute a weighted similarity score between two invoices.

    Weights:
    - Invoice number match: 40%
    - Vendor name match: 30%
    - Amount match: 30%
    """
    score = 0.0

    if inv_a.invoice_number and inv_b.invoice_number:
        num_sim = fuzz.ratio(
            inv_a.invoice_number.strip().lower(),
            inv_b.invoice_number.strip().lower(),
        )
        score += num_sim * 0.40
    elif not inv_a.invoice_number and not inv_b.invoice_number:
        score += 0.0
    else:
        score += 0.0

    if inv_a.vendor_name and inv_b.vendor_name:
        vendor_sim = fuzz.ratio(
            inv_a.vendor_name.strip().lower(),
            inv_b.vendor_name.strip().lower(),
        )
        score += vendor_sim * 0.30

    if inv_a.total_amount is not None and inv_b.total_amount is not None:
        if inv_a.total_amount == inv_b.total_amount:
            score += 100.0 * 0.30
        elif inv_a.total_amount > 0:
            diff_pct = abs(inv_a.total_amount - inv_b.total_amount) / inv_a.total_amount
            amt_sim = max(0.0, 100.0 * (1.0 - diff_pct))
            score += amt_sim * 0.30

    return score


async def check_duplicates(
    invoice: Invoice, db: AsyncSession, threshold: float | None = None
) -> DuplicateCheckResult:
    """Check an invoice against all existing invoices for potential duplicates.

    Also checks file_hash for exact file duplicates.
    """
    if threshold is None:
        threshold = settings.duplicate_threshold

    stmt = select(Invoice).where(Invoice.id != invoice.id)
    result = await db.execute(stmt)
    existing = result.scalars().all()

    matches: list[DuplicateMatch] = []

    for other in existing:
        if invoice.file_hash and other.file_hash and invoice.file_hash == other.file_hash:
            matches.append(
                DuplicateMatch(
                    invoice_id=other.id,
                    invoice_number=other.invoice_number,
                    vendor_name=other.vendor_name,
                    total_amount=other.total_amount,
                    similarity_score=100.0,
                )
            )
            continue

        sim = _compute_similarity(invoice, other)
        if sim >= threshold:
            matches.append(
                DuplicateMatch(
                    invoice_id=other.id,
                    invoice_number=other.invoice_number,
                    vendor_name=other.vendor_name,
                    total_amount=other.total_amount,
                    similarity_score=round(sim, 1),
                )
            )

    matches.sort(key=lambda m: m.similarity_score, reverse=True)
    return DuplicateCheckResult(is_duplicate=len(matches) > 0, matches=matches)
