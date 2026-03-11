"""Expense categorization engine.

Assigns expense categories to invoices based on vendor name and line item
descriptions using keyword matching rules.
"""

import logging

from ..models import Invoice

logger = logging.getLogger(__name__)

CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("Office Supplies", ["office", "paper", "toner", "ink", "staple", "pen", "folder", "binder"]),
    ("IT & Software", ["software", "license", "saas", "cloud", "hosting", "domain", "ssl",
                        "computer", "laptop", "monitor", "keyboard", "mouse", "server"]),
    ("Professional Services", ["consulting", "legal", "accounting", "audit", "advisory",
                                "attorney", "lawyer", "cpa"]),
    ("Travel & Entertainment", ["travel", "hotel", "flight", "airline", "uber", "lyft",
                                 "rental car", "meal", "restaurant", "catering"]),
    ("Utilities", ["electric", "gas", "water", "internet", "phone", "telecom",
                    "utility", "power"]),
    ("Facilities & Maintenance", ["maintenance", "repair", "cleaning", "janitorial",
                                    "hvac", "plumbing", "electrical", "landscaping"]),
    ("Marketing & Advertising", ["marketing", "advertising", "ad campaign", "print",
                                   "signage", "branding", "seo", "social media"]),
    ("Shipping & Logistics", ["shipping", "freight", "courier", "fedex", "ups", "usps",
                                "dhl", "postage", "delivery"]),
    ("Raw Materials", ["material", "lumber", "steel", "plastic", "chemical",
                        "component", "part", "supply"]),
    ("Insurance", ["insurance", "premium", "coverage", "policy", "liability"]),
]


def categorize_invoice(invoice: Invoice) -> str:
    """Categorize an invoice based on vendor name and line item descriptions.

    Returns the best-matching expense category or 'General Expense'.
    """
    text_parts: list[str] = []
    if invoice.vendor_name:
        text_parts.append(invoice.vendor_name.lower())
    for item in invoice.line_items:
        if item.description:
            text_parts.append(item.description.lower())

    combined = " ".join(text_parts)

    best_category = "General Expense"
    best_score = 0

    for category, keywords in CATEGORY_RULES:
        score = sum(1 for kw in keywords if kw in combined)
        if score > best_score:
            best_score = score
            best_category = category

    return best_category
