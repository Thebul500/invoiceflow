"""Purchase order management routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import PurchaseOrder
from ..schemas import PurchaseOrderCreate, PurchaseOrderList, PurchaseOrderResponse

router = APIRouter(prefix="/api/purchase-orders", tags=["purchase_orders"])


@router.post("", response_model=PurchaseOrderResponse, status_code=201)
async def create_purchase_order(
    data: PurchaseOrderCreate, db: AsyncSession = Depends(get_db)
):
    """Create a new purchase order."""
    existing = await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.po_number == data.po_number)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"PO {data.po_number} already exists")

    po = PurchaseOrder(
        po_number=data.po_number,
        vendor_name=data.vendor_name,
        total_amount=data.total_amount,
        description=data.description,
    )
    db.add(po)
    await db.commit()
    await db.refresh(po)
    return po


@router.get("", response_model=PurchaseOrderList)
async def list_purchase_orders(
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List purchase orders."""
    stmt = select(PurchaseOrder)
    count_stmt = select(func.count(PurchaseOrder.id))

    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
        count_stmt = count_stmt.where(PurchaseOrder.status == status)

    stmt = stmt.offset(skip).limit(limit).order_by(PurchaseOrder.id.desc())
    result = await db.execute(stmt)
    pos = list(result.scalars().all())

    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    return PurchaseOrderList(purchase_orders=pos, total=total)  # type: ignore[arg-type]


@router.get("/{po_id}", response_model=PurchaseOrderResponse)
async def get_purchase_order(po_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single purchase order."""
    stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id)
    result = await db.execute(stmt)
    po = result.scalar_one_or_none()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return po
