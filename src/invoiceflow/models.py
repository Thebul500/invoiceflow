"""SQLAlchemy database models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Invoice(Base):
    """An invoice document processed by the system."""

    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    invoice_number: Mapped[Optional[str]] = mapped_column(String, index=True, default=None)
    vendor_name: Mapped[Optional[str]] = mapped_column(String, index=True, default=None)
    vendor_address: Mapped[Optional[str]] = mapped_column(String, default=None)
    invoice_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    due_date: Mapped[Optional[str]] = mapped_column(String, default=None)
    subtotal: Mapped[Optional[float]] = mapped_column(default=None)
    tax_amount: Mapped[Optional[float]] = mapped_column(default=None)
    total_amount: Mapped[Optional[float]] = mapped_column(default=None)
    currency: Mapped[str] = mapped_column(String, default="USD")
    po_number: Mapped[Optional[str]] = mapped_column(String, index=True, default=None)
    status: Mapped[str] = mapped_column(String, index=True, default="pending")
    category: Mapped[Optional[str]] = mapped_column(String, default=None)
    file_path: Mapped[Optional[str]] = mapped_column(String, default=None)
    file_hash: Mapped[Optional[str]] = mapped_column(String, index=True, default=None)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, default=None)
    extracted_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    validation_notes: Mapped[Optional[str]] = mapped_column(Text, default=None)
    duplicate_of_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("invoices.id"), default=None
    )
    created_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    line_items: Mapped[list["LineItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    duplicate_of: Mapped[Optional["Invoice"]] = relationship(remote_side="Invoice.id")


class LineItem(Base):
    """A single line item on an invoice."""

    __tablename__ = "line_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    description: Mapped[str] = mapped_column(String, default="")
    quantity: Mapped[float] = mapped_column(default=1.0)
    unit_price: Mapped[Optional[float]] = mapped_column(default=None)
    amount: Mapped[float] = mapped_column(default=0.0)

    invoice: Mapped["Invoice"] = relationship(back_populates="line_items")


class PurchaseOrder(Base):
    """A purchase order for validation against invoices."""

    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    po_number: Mapped[str] = mapped_column(String, unique=True, index=True)
    vendor_name: Mapped[str] = mapped_column(String)
    total_amount: Mapped[float] = mapped_column()
    status: Mapped[str] = mapped_column(String, default="open")
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
