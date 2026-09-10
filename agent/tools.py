"""Homework 1: the remaining commerce-agent tools.

The three lecture tools (`search_help_center`, `get_order`, `issue_refund`)
are implemented in agent/agent.py and are worked examples of the pattern:
check permissions first, go through agent/db.py for data, and return a
structured dict, never a prose error. The homework tools follow the same
pattern. agent/agent.py already wraps each function below as an SDK tool, so
once a function works here it works in chat with no further wiring.

Result convention (see agent/auth.py):
  - Success: a dict with "ok": True plus the payload fields named in each
    docstring.
  - Failure: {"ok": False, "error": <code>, "reason": <human-readable str>}.

Run the contract tests with: uv run pytest tests/test_hw_holes.py -k hw1
They are marked xfail and flip to passing as you implement each function.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from agent import db
from agent.auth import AuthContext, can_cancel_order, permission_denied
from agent.helpcenter import load_policy_docs
from agent.killswitch import kill_switch

MAX_SEARCH_LIMIT = 25
DEFAULT_ORDER_LIMIT = 20
MAX_ORDER_MATCHES = 5  # find_order returns at most five orders
# Every status the seed writes to orders.status. list_orders_by_status validates
# against this set so a typo comes back as an error rather than an empty list.
ORDER_STATUSES = ("placed", "shipped", "delivered", "cancelled", "refunded")
STATUS_SCAN_LIMIT = 1000  # rows scanned to count matches beyond the page returned
FUZZY_MATCH_THRESHOLD = 0.75  # minimum find_order token score to count as a match
_WORD_RE = re.compile(r"[a-z0-9]+")
# Filler words in a request like "the earmuffs I bought last week" carry no
# product signal, so they must not match a product title on their own.
_QUERY_STOPWORDS = frozenset(
    {
        "the", "a", "an", "my", "our", "your", "that", "this", "those", "these",
        "i", "we", "me", "us", "it", "they", "them",
        "and", "or", "for", "from", "with", "about", "of", "in", "on", "to",
        "bought", "buy", "ordered", "order", "orders", "purchase", "purchased",
        "get", "got", "find", "show", "want", "need", "please", "was", "were",
        "last", "week", "weeks", "month", "months", "day", "days", "year",
        "years", "ago", "recent", "recently", "yesterday", "today",
    }
)


def _words(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, the same tokenisation used for matching."""
    return _WORD_RE.findall(text.lower())


def _match_score(query: str, title: str) -> float:
    """How well `query` describes a product called `title`, from 0.0 to 1.0.

    Whole-query containment wins outright. Otherwise each meaningful query
    word is scored against the title's words, by substring first and by
    difflib similarity second (so "earmufs" still finds "Earmuffs"), and the
    best single word decides. Taking the best rather than the average is what
    lets a noisy request such as "earmuffs I bought last week" match.
    """
    query_lower = query.strip().lower()
    title_lower = title.lower()
    if not query_lower:
        return 0.0
    if query_lower in title_lower:
        return 1.0

    title_words = _words(title_lower)
    query_words = [
        word
        for word in _words(query_lower)
        if word not in _QUERY_STOPWORDS and len(word) > 2
    ]
    if not query_words:
        return SequenceMatcher(None, query_lower, title_lower).ratio()

    best = 0.0
    for word in query_words:
        for title_word in title_words:
            if word in title_word or title_word in word:
                score = 0.95
            else:
                score = SequenceMatcher(None, word, title_word).ratio()
            best = max(best, score)
    return best


def get_policy(ctx: AuthContext, policy_id: str) -> dict[str, Any]:
    """Fetch one policy doc by its exact id. Risk tier: read.

    Every role may read every policy doc (the corpus is public help-center
    content), so this tool needs no permission check.

    Args:
        ctx: The caller's auth context. Unused here, but every tool takes it.
        policy_id: An exact policy id, e.g. "cw-returns" or
            "store-juniper-home-goods-policy". Matching is exact and
            case-sensitive; ids are the `policy_id` front-matter field of the
            files in data/policies/.

    Returns:
        On success: {"ok": True, "policy_id": str, "title": str,
        "audience": str, "body": str} where body is the markdown body of the
        doc without the front matter.
        If no doc has that id: {"ok": False, "error": "not_found",
        "reason": ...} naming the id that was requested.

    Implementation notes:
        agent.helpcenter.load_policy_docs() returns every parsed doc.
    """
    for doc in load_policy_docs():
        if doc.policy_id == policy_id:
            return {
                "ok": True,
                "policy_id": doc.policy_id,
                "title": doc.title,
                "audience": doc.audience,
                "body": doc.body,
            }
    return {
        "ok": False,
        "error": "not_found",
        "reason": f"no policy doc with id {policy_id!r}",
    }


def search_products(
    ctx: AuthContext,
    query: str,
    store: str | None = None,
    max_price_usd: float | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Search the product catalog. Risk tier: read.

    Every role may search products. Matching is deterministic keyword
    matching, not semantic search: a product matches when every whitespace
    token of `query` appears case-insensitively as a substring of the
    product's title or description.

    Args:
        ctx: The caller's auth context.
        query: Free-text query. Must be non-empty after stripping whitespace;
            otherwise return {"ok": False, "error": "invalid_argument",
            "reason": ...}.
        store: Optional store filter. Matched with
            agent.db.get_store_by_name (case-insensitive name or slug). If
            given and no store matches, return {"ok": False, "error":
            "not_found", "reason": ...} naming the store string.
        max_price_usd: Optional inclusive price ceiling. If given and not
            strictly positive, return an "invalid_argument" error.
        limit: Maximum products to return. Clamp to the range
            [1, MAX_SEARCH_LIMIT]; do not error on out-of-range values.

    Returns:
        {"ok": True, "products": [...], "count": <len(products)>} where each
        product is {"product_id": int, "store_id": int, "title": str,
        "price_usd": float}. Sort matches by price_usd ascending, then by
        product_id ascending, and truncate to `limit`. No matches is still a
        success: {"ok": True, "products": [], "count": 0}.

    Implementation notes:
        agent.db.list_products(conn, store_id) gives the candidate set.
        Use `with db.connection() as conn:` to close the database automatically.
    """
    tokens = query.strip().lower().split()
    if not tokens:
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": "query must not be empty",
        }
    if max_price_usd is not None and max_price_usd <= 0:
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": f"max_price_usd must be positive, got {max_price_usd}",
        }
    limit = max(1, min(int(limit), MAX_SEARCH_LIMIT))

    with db.connection() as conn:
        store_id = None
        if store is not None:
            matched_store = db.get_store_by_name(conn, store)
            if matched_store is None:
                return {
                    "ok": False,
                    "error": "not_found",
                    "reason": f"no store named {store!r}",
                }
            store_id = matched_store.id
        candidates = db.list_products(conn, store_id)

    products = []
    for product in candidates:
        haystack = f"{product.title} {product.description}".lower()
        if not all(token in haystack for token in tokens):
            continue
        if max_price_usd is not None and product.price_usd > max_price_usd:
            continue
        products.append(
            {
                "product_id": product.id,
                "store_id": product.store_id,
                "title": product.title,
                "price_usd": product.price_usd,
            }
        )

    products.sort(key=lambda item: (item["price_usd"], item["product_id"]))
    products = products[:limit]
    return {"ok": True, "products": products, "count": len(products)}


def list_my_orders(ctx: AuthContext) -> dict[str, Any]:
    """List recent orders in the caller's own scope. Risk tier: read.

    Role behavior, straight from the access matrix in SPEC.md:
        - shopper: the caller's own orders.
        - merchant: the caller's store's orders (ctx.store_id).
        - support: support staff have no orders of their own and look up
          specific orders with get_order instead, so return {"ok": False,
          "error": "invalid_argument", "reason": ...} saying exactly that.

    Returns:
        For shopper and merchant: {"ok": True, "orders": [...],
        "count": <len(orders)>} where each order is
        agent.db.Order.to_public_dict() and the list holds at most
        DEFAULT_ORDER_LIMIT orders, newest first (agent.db.list_orders_for_user
        and list_orders_for_store already sort and limit this way).

    Implementation notes:
        No permission check is needed beyond the role dispatch, because the
        scope is baked into which query you run. That is the point of the
        tool: the model cannot ask for someone else's orders through it.
    """
    if ctx.role == "support":
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": (
                "support staff have no orders of their own; "
                "look up a specific order with get_order instead"
            ),
        }

    with db.connection() as conn:
        if ctx.role == "shopper":
            orders = db.list_orders_for_user(conn, ctx.user_id, DEFAULT_ORDER_LIMIT)
        else:
            orders = db.list_orders_for_store(conn, ctx.store_id, DEFAULT_ORDER_LIMIT)

    payload = [order.to_public_dict() for order in orders]
    return {"ok": True, "orders": payload, "count": len(payload)}


def cancel_order(ctx: AuthContext, order_id: int, reason: str) -> dict[str, Any]:
    """Cancel an order. Risk tier: write.

    This is the homework's write tool, and it must enforce two independent
    rules in this order:

    1. The access matrix (scope): use agent.auth.can_cancel_order. Shoppers
       may cancel only their own orders, merchants only their own store's
       orders, support any order. On failure return
       agent.auth.permission_denied(...) with a reason naming the role and
       the order id. Scope is checked before the status rule so that an
       out-of-scope caller learns nothing about the order's state.
    2. The pre-shipment rule (facts.yaml `cancel_cutoff`): only orders whose
       status is exactly "placed" can be cancelled, for every role. If the
       order is in scope but its status is not "placed", return
       {"ok": False, "error": "not_eligible", "reason": ...} that names the
       current status and states that orders can be cancelled only before
       shipment.

    Args:
        ctx: The caller's auth context.
        order_id: The order to cancel.
        reason: Free-text reason from the user; not validated.

    Returns:
        If no order has this id: {"ok": False, "error": "not_found",
        "reason": ...}.
        On success: {"ok": True, "order_id": order_id, "status": "cancelled"}
        after persisting the new status with agent.db.set_order_status.

    Implementation notes:
        Fetch with agent.db.get_order. Note the argument order of
        can_cancel_order(ctx, order_user_id, order_store_id).

    The Module 4 kill switch is checked first (before the scope and
    status rules and before your code), so that a paused write tool touches
    nothing. It is provided; the default ("off") returns None and falls
    through to your implementation.
    """
    # 0. Kill switch (supplied): a paused write tool must not touch the database.
    paused = kill_switch("cancel_order")
    if paused is not None:
        return {"ok": False, "error": "paused", "reason": paused}
    
    ### YOUR CODE HERE
    with db.connection() as conn:
        # 1. Existence.
        order = db.get_order(conn, order_id)
        if order is None:
            return {"ok": False, "error": "not_found", "reason": f"no order #{order_id}"}
        # 2. Scope, before state: an out-of-scope caller must not learn the status.
        if not can_cancel_order(ctx, order.user_id, order.store_id):
            return permission_denied(
                f"role '{ctx.role}' (user {ctx.user_id}) may not cancel order #{order_id}"
            )
        # 3. State: the pre-shipment rule applies to every role.
        if order.status != "placed":
            return {
                "ok": False,
                "error": "not_eligible",
                "reason": (
                    f"order #{order_id} has status '{order.status}'; "
                    "orders can be cancelled only before shipment"
                ),
            }
        # 4. Write. set_order_status commits; the `with` block only closes.
        db.set_order_status(conn, order_id, "cancelled")
        return {"ok": True, "order_id": order_id, "status": "cancelled"}


def find_order(ctx: AuthContext, query: str) -> dict[str, Any]:
    """Search the caller's orders by product name. Risk tier: read.

    Takes a natural-language query (e.g., "earmuffs I bought last week")
    and searches the authenticated user's orders for products whose name
    matches. Use fuzzy string matching (e.g., thefuzz.fuzz.partial_ratio
    or case-insensitive substring matching) to find orders whose product name is close to the
    query.

    Access rules: a shopper searches only the shopper's own orders, a
    merchant searches orders from the merchant's store, and support staff
    can search any orders. Use agent.db.list_order_search_candidates with
    user_id=ctx.user_id for shoppers, store_id=ctx.store_id for merchants,
    or all_orders=True only for support. Derive the scope from ctx, never
    from the query; reject unsupported roles or missing required identity.
    Use agent.db.list_products to map product IDs to product titles.

    The helper returns the complete authorised scope, newest first with
    order ID descending as the tie-breaker. Match product names first,
    preserve that order, then return at most five matches. Do not search
    only the 20 most recent orders. Convert matches with to_public_dict().

    Args:
        ctx: The caller's auth context.
        query: A natural-language description of the product.

    Returns:
        {"ok": True, "orders": [...]} with a list of matching orders
        (at most 5), each as the dict returned by agent.db. If no orders
        match, return {"ok": True, "orders": []}.
    """
    with db.connection() as conn:
        if ctx.role == "shopper":
            orders = db.list_orders_for_user(conn, ctx.user_id, DEFAULT_ORDER_LIMIT)
        elif ctx.role == "merchant":
            orders = db.list_orders_for_store(conn, ctx.store_id, DEFAULT_ORDER_LIMIT)
        else:
            # Support may search any order. agent.db has no "every order"
            # helper, so this reuses the same row mapper over the same table
            # rather than introducing a second data layer.
            rows = conn.execute(
                "SELECT * FROM orders ORDER BY ordered_at DESC, id DESC LIMIT ?",
                (DEFAULT_ORDER_LIMIT,),
            ).fetchall()
            orders = [db._order_from_row(row) for row in rows]

        titles = {
            product.id: product.title
            for product in db.list_products(conn)
        }

    scored = []
    for order in orders:
        title = titles.get(order.product_id)
        if title is None:
            continue
        score = _match_score(query, title)
        if score >= FUZZY_MATCH_THRESHOLD:
            payload = order.to_public_dict()
            payload["product_title"] = title
            scored.append((score, payload))

    # Best match first; equal scores keep the newest-first order from the query.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return {"ok": True, "orders": [payload for _, payload in scored[:MAX_ORDER_MATCHES]]}


def list_orders_by_status(
    ctx: AuthContext, status: str, limit: int = DEFAULT_ORDER_LIMIT
) -> dict[str, Any]:
    """List the caller's orders that currently have one status. Risk tier: read.

    Added for Homework 1 Part A after a merchant asked which of their store's
    orders had not shipped yet. `list_my_orders` could only return the twenty
    most recent orders of every status, so the model had to do the filtering
    itself and reported cancelled orders as work still awaiting shipment.

    Scope matches `list_my_orders` exactly, and for the same reason: the role
    picks which query runs, so there is no argument through which a caller
    could reach another user's or another store's orders.
        - shopper: the caller's own orders.
        - merchant: the caller's store's orders (ctx.store_id).
        - support: no orders of their own, so return
          {"ok": False, "error": "invalid_argument", ...}, as list_my_orders does.

    Args:
        ctx: The caller's auth context.
        status: One of ORDER_STATUSES, matched case-insensitively after
            stripping. Any other value returns "invalid_argument" naming the
            statuses that are accepted, so the model can retry rather than
            read an empty list as "no such orders".
        limit: Maximum orders to return. Clamped to [1, DEFAULT_ORDER_LIMIT].

    Returns:
        {"ok": True, "status": <normalized>, "orders": [...], "count": n,
        "total_matching": m} where each order is Order.to_public_dict(),
        newest first. `count` is how many orders this result carries and
        `total_matching` how many exist in the caller's scope, so the agent
        can say "12 of 47" instead of implying the page is everything.
        No matches is a success with an empty list and both counts zero.
    """
    if ctx.role == "support":
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": (
                "support staff have no orders of their own; "
                "look up a specific order with get_order instead"
            ),
        }

    normalized = status.strip().lower()
    if normalized not in ORDER_STATUSES:
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": (
                f"unknown order status {status!r}; "
                f"expected one of {', '.join(ORDER_STATUSES)}"
            ),
        }
    limit = max(1, min(int(limit), DEFAULT_ORDER_LIMIT))

    with db.connection() as conn:
        if ctx.role == "shopper":
            orders = db.list_orders_for_user(conn, ctx.user_id, STATUS_SCAN_LIMIT)
        else:
            orders = db.list_orders_for_store(conn, ctx.store_id, STATUS_SCAN_LIMIT)

    matching = [order for order in orders if order.status == normalized]
    payload = [order.to_public_dict() for order in matching[:limit]]
    return {
        "ok": True,
        "status": normalized,
        "orders": payload,
        "count": len(payload),
        "total_matching": len(matching),
    }
