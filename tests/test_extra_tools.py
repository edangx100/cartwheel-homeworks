"""Contract tests for the tools added in Homework 1 Part A.

`list_orders_by_status` was added after the Part B conversation in which a
merchant asked which of their store's orders had not shipped yet (C09). The
agent had to filter `list_my_orders` itself and presented cancelled orders as
work still awaiting shipment.
"""

from __future__ import annotations

from agent import db, tools
from agent.auth import AuthContext

SHOPPER_1 = AuthContext(user_id=1, role="shopper")
MERCHANT_STORE_2 = AuthContext(user_id=9002, role="merchant", store_id=2)
SUPPORT = AuthContext(user_id=9501, role="support")


def test_shopper_sees_only_their_own_orders(world: dict) -> None:
    result = tools.list_orders_by_status(SHOPPER_1, "delivered")
    assert result["ok"] is True
    assert result["status"] == "delivered"
    assert all(o["status"] == "delivered" for o in result["orders"])
    assert result["count"] == len(result["orders"])

    conn = db.connect()
    try:
        owned = {o.id for o in db.list_orders_for_user(conn, 1, 1000)}
    finally:
        conn.close()
    assert {o["order_id"] for o in result["orders"]} <= owned


def test_merchant_is_scoped_to_the_store(world: dict) -> None:
    result = tools.list_orders_by_status(MERCHANT_STORE_2, "refunded")
    assert result["ok"] is True
    assert all(o["store_id"] == 2 for o in result["orders"])


def test_total_matching_reports_beyond_the_returned_page(world: dict) -> None:
    """The count that closes the silent-truncation hole in list_my_orders."""
    result = tools.list_orders_by_status(MERCHANT_STORE_2, "delivered", limit=5)
    assert result["count"] == len(result["orders"]) <= 5
    assert result["total_matching"] >= result["count"]

    conn = db.connect()
    try:
        expected = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE store_id = 2 AND status = 'delivered'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert result["total_matching"] == expected


def test_no_matches_is_a_success_not_an_error(world: dict) -> None:
    result = tools.list_orders_by_status(MERCHANT_STORE_2, "placed")
    assert result["ok"] is True
    assert result["orders"] == []
    assert result["count"] == 0
    assert result["total_matching"] == 0


def test_unknown_status_is_rejected_rather_than_returning_nothing(world: dict) -> None:
    result = tools.list_orders_by_status(SHOPPER_1, "unshipped")
    assert result["ok"] is False
    assert result["error"] == "invalid_argument"
    assert "placed" in result["reason"]


def test_status_matching_ignores_case_and_whitespace(world: dict) -> None:
    result = tools.list_orders_by_status(SHOPPER_1, "  Delivered ")
    assert result["ok"] is True
    assert result["status"] == "delivered"


def test_limit_is_clamped_not_rejected(world: dict) -> None:
    assert tools.list_orders_by_status(SHOPPER_1, "delivered", limit=0)["ok"] is True
    big = tools.list_orders_by_status(SHOPPER_1, "delivered", limit=999)
    assert big["ok"] is True
    assert big["count"] <= tools.DEFAULT_ORDER_LIMIT


def test_support_has_no_orders_of_their_own(world: dict) -> None:
    result = tools.list_orders_by_status(SUPPORT, "delivered")
    assert result["ok"] is False
    assert result["error"] == "invalid_argument"
