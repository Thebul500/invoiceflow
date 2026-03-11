"""InvoiceFlow CLI — command-line interface for invoice processing.

Provides direct access to the core data ingestion pipeline:
- Ingest local invoice files (PDF, image, email, text)
- Fetch and ingest invoices from remote URLs via HTTP
- Export processed invoices to CSV or QuickBooks IIF
- List and manage invoices (list, approve, reject)
- View pipeline status and statistics
- Run the API server
- Start the watch folder monitor
"""

import argparse
import asyncio
import logging
import sys

from .config import settings


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def _cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest a local invoice file through the extraction pipeline."""
    from .database import init_db
    from .engine.ingestor import ingest_file

    await init_db()

    result = await ingest_file(args.file)
    if result is None:
        print(f"Failed to ingest: {args.file}", file=sys.stderr)
        return 1

    print(f"Ingested invoice #{result['id']}")
    print(f"  Vendor:   {result.get('vendor_name', 'N/A')}")
    print(f"  Number:   {result.get('invoice_number', 'N/A')}")
    print(f"  Amount:   {result.get('total_amount', 'N/A')}")
    print(f"  Category: {result.get('category', 'N/A')}")
    print(f"  Status:   {result.get('status', 'N/A')}")
    return 0


async def _cmd_fetch(args: argparse.Namespace) -> int:
    """Fetch an invoice from a remote URL and ingest it via HTTP."""
    from .database import init_db
    from .engine.ingestor import fetch_from_url

    await init_db()

    result = await fetch_from_url(args.url, args.filename)
    if result is None:
        print(f"Failed to fetch/ingest: {args.url}", file=sys.stderr)
        return 1

    print(f"Fetched and ingested invoice #{result['id']}")
    print(f"  Vendor:   {result.get('vendor_name', 'N/A')}")
    print(f"  Number:   {result.get('invoice_number', 'N/A')}")
    print(f"  Amount:   {result.get('total_amount', 'N/A')}")
    print(f"  Category: {result.get('category', 'N/A')}")
    return 0


async def _cmd_export(args: argparse.Namespace) -> int:
    """Export processed invoices to CSV or QuickBooks IIF."""
    from .database import async_session, init_db
    from .engine.exporter import export_csv, export_iif

    await init_db()

    async with async_session() as db:
        if args.format == "iif":
            path = await export_iif(db)
        else:
            path = await export_csv(db)

    print(f"Exported to: {path}")
    return 0


async def _cmd_watch(args: argparse.Namespace) -> int:
    """Start the watch folder monitor for automatic data ingestion."""
    from .database import init_db
    from .engine.ingestor import run_ingestor

    await init_db()

    watch_dir = args.dir or settings.watch_dir
    print(f"Watching for invoice files in: {watch_dir}")
    print("Drop PDF, image, email, or text files to auto-ingest. Ctrl+C to stop.")
    await run_ingestor(watch_dir)
    return 0


async def _cmd_email_ingest(args: argparse.Namespace) -> int:
    """Fetch invoices from an IMAP email inbox."""
    from .database import init_db
    from .engine.email_ingestor import ingest_from_mailbox

    await init_db()

    print(f"Connecting to IMAP: {args.host or settings.imap_host}:{args.port or settings.imap_port}")
    results = await ingest_from_mailbox(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        folder=args.folder,
    )

    if not results:
        print("No invoice emails found.")
        return 0

    success = sum(1 for r in results if "error" not in r)
    print(f"Processed {len(results)} attachments ({success} succeeded)")
    for r in results:
        if "error" in r:
            print(f"  FAIL: {r.get('file', 'unknown')} — {r['error']}")
        else:
            print(f"  OK:   #{r['id']} {r.get('vendor_name', 'N/A')} ${r.get('total_amount', 0):.2f}")
    return 0


async def _cmd_list(args: argparse.Namespace) -> int:
    """List invoices with optional status filter."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from .database import async_session, init_db
    from .models import Invoice

    await init_db()

    async with async_session() as db:
        stmt = select(Invoice).options(selectinload(Invoice.line_items))
        if args.status:
            stmt = stmt.where(Invoice.status == args.status)
        stmt = stmt.order_by(Invoice.id.desc()).limit(args.limit)
        result = await db.execute(stmt)
        invoices = list(result.scalars().all())

    if not invoices:
        print("No invoices found.")
        return 0

    # Column header
    print(f"{'ID':<6} {'Number':<18} {'Vendor':<25} {'Amount':>12} {'Status':<10} {'Category':<20}")
    print("-" * 95)
    for inv in invoices:
        inv_num = (inv.invoice_number or "—")[:17]
        vendor = (inv.vendor_name or "—")[:24]
        amount = f"${inv.total_amount:,.2f}" if inv.total_amount else "—"
        status = inv.status or "—"
        category = (inv.category or "—")[:19]
        print(f"{inv.id:<6} {inv_num:<18} {vendor:<25} {amount:>12} {status:<10} {category:<20}")

    print(f"\n{len(invoices)} invoice(s) shown.")
    return 0


async def _cmd_status(args: argparse.Namespace) -> int:
    """Show pipeline status and statistics."""
    from .database import async_session, init_db
    from .engine.pipeline import get_pipeline_status

    await init_db()

    async with async_session() as db:
        status = await get_pipeline_status(db)

    print("InvoiceFlow Pipeline Status")
    print("=" * 40)
    print(f"  Total invoices:    {status['total_invoices']}")
    print(f"  Pending:           {status['by_status']['pending']}")
    print(f"  Approved:          {status['by_status']['approved']}")
    print(f"  Rejected:          {status['by_status']['rejected']}")
    print(f"  Exported:          {status['by_status']['exported']}")
    print(f"  Duplicates found:  {status['duplicates_detected']}")
    print()
    print(f"  Ollama model:      {status['ollama_model']}")
    print(f"  Ollama URL:        {status['ollama_url']}")
    print(f"  Watch dir:         {status['watch_dir']}")
    print(f"  Formats:           {', '.join(status['supported_formats'])}")
    return 0


async def _cmd_approve(args: argparse.Namespace) -> int:
    """Approve or reject an invoice by ID."""
    from sqlalchemy import select

    from .database import async_session, init_db
    from .models import Invoice

    await init_db()

    new_status = "approved" if args.action == "approve" else "rejected"

    async with async_session() as db:
        stmt = select(Invoice).where(Invoice.id == args.invoice_id)
        result = await db.execute(stmt)
        invoice = result.scalar_one_or_none()

        if not invoice:
            print(f"Error: Invoice #{args.invoice_id} not found.", file=sys.stderr)
            return 1

        old_status = invoice.status
        invoice.status = new_status
        await db.commit()

    print(f"Invoice #{args.invoice_id}: {old_status} -> {new_status}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    """Run the FastAPI API server."""
    import uvicorn

    uvicorn.run(
        "invoiceflow.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="invoiceflow",
        description="AI invoice processing pipeline — ingest, extract, validate, export.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    sub = parser.add_subparsers(dest="command")

    # ingest
    p_ingest = sub.add_parser("ingest", help="Ingest a local invoice file")
    p_ingest.add_argument("file", help="Path to invoice file (PDF, image, email, text)")

    # fetch
    p_fetch = sub.add_parser("fetch", help="Fetch and ingest an invoice from a URL")
    p_fetch.add_argument("url", help="Remote URL to fetch the invoice from")
    p_fetch.add_argument("--filename", help="Override saved filename")

    # export
    p_export = sub.add_parser("export", help="Export invoices to CSV or IIF")
    p_export.add_argument(
        "--format", choices=["csv", "iif"], default="csv", help="Export format (default: csv)"
    )

    # watch
    p_watch = sub.add_parser("watch", help="Start watch folder monitor for auto-ingestion")
    p_watch.add_argument("--dir", help="Watch directory (default: ~/.invoiceflow/watch)")

    # email-ingest
    p_email = sub.add_parser("email-ingest", help="Fetch invoices from an IMAP email inbox")
    p_email.add_argument("--host", help="IMAP server hostname")
    p_email.add_argument("--port", type=int, help="IMAP server port")
    p_email.add_argument("--user", help="IMAP username")
    p_email.add_argument("--password", help="IMAP password")
    p_email.add_argument("--folder", help="IMAP folder (default: INBOX)")

    # list
    p_list = sub.add_parser("list", help="List invoices with optional filters")
    p_list.add_argument(
        "--status", choices=["pending", "approved", "rejected", "exported"],
        help="Filter by status",
    )
    p_list.add_argument("--limit", type=int, default=25, help="Max invoices to show (default: 25)")

    # status
    sub.add_parser("status", help="Show pipeline status and statistics")

    # approve / reject
    p_approve = sub.add_parser("approve", help="Approve an invoice by ID")
    p_approve.add_argument("invoice_id", type=int, help="Invoice ID to approve")
    p_approve.set_defaults(action="approve")

    p_reject = sub.add_parser("reject", help="Reject an invoice by ID")
    p_reject.add_argument("invoice_id", type=int, help="Invoice ID to reject")
    p_reject.set_defaults(action="reject")

    # serve
    p_serve = sub.add_parser("serve", help="Run the API server")
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host")
    p_serve.add_argument("--port", type=int, default=8000, help="Bind port")
    p_serve.add_argument("--reload", action="store_true", help="Auto-reload on code changes")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _setup_logging(args.verbose)

    if args.command is None:
        parser.print_help()
        return 0

    cmd_map = {
        "ingest": _cmd_ingest,
        "fetch": _cmd_fetch,
        "export": _cmd_export,
        "watch": _cmd_watch,
        "email-ingest": _cmd_email_ingest,
        "list": _cmd_list,
        "status": _cmd_status,
        "approve": _cmd_approve,
        "reject": _cmd_approve,
    }

    if args.command == "serve":
        return _cmd_serve(args)

    handler = cmd_map.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return asyncio.run(handler(args))


if __name__ == "__main__":
    sys.exit(main())
