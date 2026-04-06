"""
Mock e-commerce tools for the lab. Data is fixed so traces are reproducible.
Use these for the ReAct agent; the chatbot baseline does not call them.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, TypedDict


class ToolDefinition(TypedDict):
    name: str
    description: str
    args_format: str
    fn: Callable[..., str]


# --- Mock catalog (item name -> unit price USD, units in stock) ---
_CATALOG: Dict[str, Dict[str, float]] = {
    "iphone": {"unit_price_usd": 999.0, "quantity": 120},
    "iphone 15": {"unit_price_usd": 999.0, "quantity": 120},
    "airpods": {"unit_price_usd": 179.0, "quantity": 200},
}

# Coupon code -> percent off the line (0-100)
_COUPONS: Dict[str, float] = {
    "WINNER": 10.0,
    "SAVE5": 5.0,
}

# City (normalized lower) -> base fee USD + per-kg USD
_SHIPPING_RULES: Dict[str, tuple] = {
    "hanoi": (5.0, 2.0),
    "ho chi minh": (6.0, 2.2),
    "default": (8.0, 2.5),
}

# ISO2 country code -> VAT percent for demo
_VAT: Dict[str, float] = {
    "VN": 10.0,
    "US": 0.0,
}


def _norm_item(name: str) -> str:
    return name.strip().lower()


def _norm_city(city: str) -> str:
    return city.strip().lower()


def check_stock(item_name: str) -> str:
    """Look up price and availability."""
    key = _norm_item(item_name)
    for catalog_key, row in _CATALOG.items():
        if catalog_key == key or catalog_key in key or key in catalog_key:
            return json.dumps(
                {
                    "item": catalog_key,
                    "unit_price_usd": row["unit_price_usd"],
                    "quantity_available": int(row["quantity"]),
                }
            )
    return json.dumps({"error": f"Unknown item: {item_name!r}", "quantity_available": 0})


def get_discount(coupon_code: str) -> str:
    """Return percent discount for a coupon code, or 0 if invalid."""
    code = coupon_code.strip().upper()
    pct = _COUPONS.get(code, 0.0)
    return json.dumps({"coupon_code": code, "discount_percent": pct, "valid": code in _COUPONS})


def calc_shipping(weight_kg: float, destination_city: str) -> str:
    """Shipping cost USD from weight (kg) and destination city."""
    city = _norm_city(destination_city)
    base, per_kg = _SHIPPING_RULES.get(city, _SHIPPING_RULES["default"])
    w = max(0.0, float(weight_kg))
    cost = base + per_kg * w
    return json.dumps(
        {
            "destination_city": destination_city.strip(),
            "weight_kg": w,
            "shipping_usd": round(cost, 2),
        }
    )


def calc_line_total(unit_price_usd: float, quantity: int, discount_percent: float) -> str:
    """
    Line total after percent discount (before shipping and VAT).
    discount_percent is 0–100.
    """
    u = float(unit_price_usd)
    q = max(0, int(quantity))
    d = max(0.0, min(100.0, float(discount_percent)))
    subtotal = u * q * (1.0 - d / 100.0)
    return json.dumps(
        {
            "unit_price_usd": u,
            "quantity": q,
            "discount_percent": d,
            "line_total_usd": round(subtotal, 2),
        }
    )


def apply_vat(amount_usd: float, country_code: str) -> str:
    """Apply demo VAT to an amount. country_code is ISO2, e.g. VN, US."""
    cc = country_code.strip().upper()
    rate = _VAT.get(cc, 0.0)
    amt = max(0.0, float(amount_usd))
    tax = amt * (rate / 100.0)
    return json.dumps(
        {
            "country_code": cc,
            "vat_percent": rate,
            "amount_before_tax_usd": round(amt, 2),
            "vat_usd": round(tax, 2),
            "total_with_vat_usd": round(amt + tax, 2),
        }
    )


TOOL_DEFINITIONS: List[ToolDefinition] = [
    {
        "name": "check_stock",
        "description": (
            "Looks up a product by name (e.g. 'iPhone', 'AirPods'). "
            "Returns JSON with unit_price_usd, quantity_available, and item key. "
            "Use exact catalog names when possible."
        ),
        "args_format": "item_name: string - product name as the customer would say it.",
        "fn": lambda item_name: check_stock(item_name),
    },
    {
        "name": "get_discount",
        "description": (
            "Validates a coupon code and returns JSON with discount_percent (0–100) and valid boolean. "
            "Invalid codes yield discount_percent 0."
        ),
        "args_format": "coupon_code: string - uppercase or mixed case, e.g. WINNER.",
        "fn": lambda coupon_code: get_discount(coupon_code),
    },
    {
        "name": "calc_shipping",
        "description": (
            "Computes shipping in USD from parcel weight in kg and destination city name. "
            "Knows 'Hanoi' and 'Ho Chi Minh'; other cities use a default rate."
        ),
        "args_format": "weight_kg: number, destination_city: string - e.g. weight_kg=0.4, destination_city='Hanoi'.",
        "fn": lambda weight_kg, destination_city: calc_shipping(float(weight_kg), str(destination_city)),
    },
    {
        "name": "calc_line_total",
        "description": (
            "Computes discounted line total in USD: unit price × quantity after percent discount. "
            "Use after check_stock and get_discount."
        ),
        "args_format": "unit_price_usd: number, quantity: integer, discount_percent: number (0-100).",
        "fn": lambda unit_price_usd, quantity, discount_percent: calc_line_total(
            float(unit_price_usd), int(quantity), float(discount_percent)
        ),
    },
    {
        "name": "apply_vat",
        "description": (
            "Applies demo VAT to amount_usd for ISO2 country_code (VN = 10%). "
            "For checkout totals, set amount_usd = (discounted line total) + (shipping_usd) before tax, "
            "unless the user specifies tax on merchandise only."
        ),
        "args_format": "amount_usd: number, country_code: string - ISO2, e.g. 'VN'.",
        "fn": lambda amount_usd, country_code: apply_vat(float(amount_usd), str(country_code)),
    },
]


def get_tool_specs_for_prompt() -> List[Dict[str, str]]:
    """Minimal dicts for ReAct system prompts (name + description + args)."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "args": t["args_format"],
        }
        for t in TOOL_DEFINITIONS
    ]


def get_tool_by_name(name: str) -> ToolDefinition | None:
    for t in TOOL_DEFINITIONS:
        if t["name"] == name:
            return t
    return None


def dispatch_tool(name: str, arguments: Dict[str, Any]) -> str:
    """
    Run a tool by name with keyword arguments matching the Python functions.
    Raises ValueError for unknown tool or bad args.
    """
    t = get_tool_by_name(name)
    if not t:
        return json.dumps({"error": f"unknown_tool:{name}"})
    fn = t["fn"]
    try:
        if name == "check_stock":
            return fn(arguments["item_name"])
        if name == "get_discount":
            return fn(arguments["coupon_code"])
        if name == "calc_shipping":
            return fn(arguments["weight_kg"], arguments["destination_city"])
        if name == "calc_line_total":
            return fn(arguments["unit_price_usd"], arguments["quantity"], arguments["discount_percent"])
        if name == "apply_vat":
            return fn(arguments["amount_usd"], arguments["country_code"])
    except KeyError as e:
        return json.dumps({"error": "missing_argument", "detail": str(e)})
    except (TypeError, ValueError) as e:
        return json.dumps({"error": "invalid_argument", "detail": str(e)})
    return json.dumps({"error": "unhandled_tool", "name": name})
