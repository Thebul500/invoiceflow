"""Pydantic request/response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    timestamp: datetime


# --- Line Items ---


class LineItemBase(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: Optional[float] = None
    amount: float


class LineItemResponse(LineItemBase):
    id: int
    invoice_id: int
    model_config = {"from_attributes": True}


# --- Invoices ---


class InvoiceBase(BaseModel):
    invoice_number: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_address: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    total_amount: Optional[float] = None
    currency: str = "USD"
    po_number: Optional[str] = None
    category: Optional[str] = None


class InvoiceCreate(InvoiceBase):
    """Manual invoice creation (without file upload)."""

    line_items: list[LineItemBase] = Field(default_factory=list)


class InvoiceResponse(InvoiceBase):
    id: int
    status: str
    file_path: Optional[str] = None
    file_hash: Optional[str] = None
    raw_text: Optional[str] = None
    validation_notes: Optional[str] = None
    duplicate_of_id: Optional[int] = None
    line_items: list[LineItemResponse] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class InvoiceListResponse(BaseModel):
    invoices: list[InvoiceResponse]
    total: int


class InvoiceStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(pending|approved|rejected|exported)$")


# --- Purchase Orders ---


class PurchaseOrderCreate(BaseModel):
    po_number: str
    vendor_name: str
    total_amount: float
    description: Optional[str] = None


class PurchaseOrderResponse(PurchaseOrderCreate):
    id: int
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class PurchaseOrderList(BaseModel):
    purchase_orders: list[PurchaseOrderResponse]
    total: int


# --- Validation ---


class ValidationResult(BaseModel):
    valid: bool
    discrepancies: list[str] = Field(default_factory=list)
    po_number: Optional[str] = None
    po_amount: Optional[float] = None
    invoice_amount: Optional[float] = None


# --- Duplicate Detection ---


class DuplicateMatch(BaseModel):
    invoice_id: int
    invoice_number: Optional[str] = None
    vendor_name: Optional[str] = None
    total_amount: Optional[float] = None
    similarity_score: float


class DuplicateCheckResult(BaseModel):
    is_duplicate: bool
    matches: list[DuplicateMatch] = Field(default_factory=list)


# --- Export ---


class ExportRequest(BaseModel):
    invoice_ids: list[int] = Field(default_factory=list)
    format: str = Field(default="csv", pattern="^(csv|iif)$")


class ExportResponse(BaseModel):
    file_path: str
    format: str
    invoice_count: int


# --- Ingestion ---


class IngestRequest(BaseModel):
    file_path: str = Field(..., description="Path to a local invoice file to ingest")


class IngestResponse(BaseModel):
    id: Optional[int] = None
    invoice_number: Optional[str] = None
    vendor_name: Optional[str] = None
    total_amount: Optional[float] = None
    status: Optional[str] = None
    category: Optional[str] = None
    message: str = "Ingested successfully"


class FetchUrlRequest(BaseModel):
    """Fetch an invoice from a remote URL for ingestion."""

    url: str = Field(..., description="URL to fetch the invoice file from")
    filename: Optional[str] = Field(None, description="Override filename (auto-detected if omitted)")


class WatchFolderStatus(BaseModel):
    watch_dir: str
    supported_extensions: list[str]
    active: bool = True
