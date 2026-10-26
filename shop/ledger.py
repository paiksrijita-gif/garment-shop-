"""Inventory costing engine.

Every stock change is a row in inventory_movements. Inbound opening stock and
purchases carry a fixed landed value. The cost of everything else (sales,
damage, stock corrections, customer returns) is derived by replaying a
variant's ledger in date order with the configured costing method:

* WAC  - perpetual (moving) weighted-average cost, the default
* FIFO - first in, first out cost layers

Replaying rather than updating incrementally means back-dated entries, voids
and a change of costing method always leave COGS and stock valuation correct.
"""
from collections import deque

from .db import get_setting
from .util import money, qty_round, EPS


def recost_variants(conn, variant_ids):
    method = get_setting(conn, "costing_method") or "WAC"
    for vid in sorted(set(variant_ids)):
        recost_variant(conn, vid, method)


def recost_all(conn):
    method = get_setting(conn, "costing_method") or "WAC"
    for (vid,) in conn.execute("SELECT id FROM variants").fetchall():
        recost_variant(conn, vid, method)


def recost_variant(conn, variant_id, method):
    moves = conn.execute(
        "SELECT id, kind, qty, value, src_item_id FROM inventory_movements "
        "WHERE variant_id = ? AND active = 1 ORDER BY move_date, id",
        (variant_id,),
    ).fetchall()

    qty = 0.0
    value = 0.0
    layers = deque()          # FIFO cost layers: [qty_remaining, unit_cost]
    last_cost = 0.0           # fallback when stock would go negative
    sale_unit_cost = {}       # sale_item_id -> unit cost charged on sale
    updates = []

    for m in moves:
        q = m["qty"]
        kind = m["kind"]
        if q > 0:
            if kind in ("opening", "purchase"):
                in_value = m["value"]
                uc = in_value / q if q else 0.0
            else:
                if kind == "return_in":
                    uc = sale_unit_cost.get(m["src_item_id"], last_cost)
                else:  # positive stock correction enters at current cost
                    uc = (value / qty) if qty > EPS else last_cost
                in_value = money(q * uc)
            qty += q
            value += in_value
            layers.append([q, uc])
            last_cost = uc
            updates.append((uc, in_value, m["id"]))
        else:
            out = -q
            if method == "FIFO":
                cost = 0.0
                need = out
                while need > EPS and layers:
                    layer = layers[0]
                    take = min(need, layer[0])
                    cost += take * layer[1]
                    layer[0] -= take
                    need -= take
                    if layer[0] <= EPS:
                        layers.popleft()
                if need > EPS:
                    cost += need * last_cost
                cost = money(cost)
            else:
                if qty > EPS:
                    if out >= qty - EPS:
                        cost = value + max(0.0, out - qty) * (value / qty)
                    else:
                        cost = out * value / qty
                else:
                    cost = out * last_cost
                cost = money(cost)
                # keep FIFO layers roughly in step so qty stays consistent
                need = out
                while need > EPS and layers:
                    take = min(need, layers[0][0])
                    layers[0][0] -= take
                    need -= take
                    if layers[0][0] <= EPS:
                        layers.popleft()
            uc = cost / out if out else 0.0
            if uc > 0:
                last_cost = uc
            qty -= out
            value -= cost
            if kind == "sale":
                sale_unit_cost[m["src_item_id"]] = uc
            updates.append((uc, -cost, m["id"]))

        if abs(qty) <= EPS:
            qty = 0.0
            value = 0.0
            layers.clear()
        elif method == "FIFO" and qty > 0:
            value = sum(l[0] * l[1] for l in layers)

    conn.executemany("UPDATE inventory_movements SET unit_cost = ?, value = ? WHERE id = ?", updates)
    conn.execute(
        "UPDATE variants SET stock_qty = ?, stock_value = ? WHERE id = ?",
        (qty_round(qty), money(value), variant_id),
    )
    # Propagate derived costs back to the documents that own the movements.
    conn.execute(
        """UPDATE sale_items SET cogs = COALESCE((
             SELECT -SUM(m.value) FROM inventory_movements m
             WHERE m.ref_table = 'sales' AND m.src_item_id = sale_items.id AND m.active = 1), 0)
           WHERE variant_id = ?""",
        (variant_id,),
    )
    conn.execute(
        """UPDATE sale_return_items SET cogs_reversed = ROUND(qty * (
             SELECT CASE WHEN si.qty > 0 THEN si.cogs / si.qty ELSE 0 END
             FROM sale_items si WHERE si.id = sale_return_items.sale_item_id), 2)
           WHERE sale_item_id IN (SELECT id FROM sale_items WHERE variant_id = ?)""",
        (variant_id,),
    )
    conn.execute(
        """UPDATE stock_adjustments SET value = COALESCE((
             SELECT SUM(m.value) FROM inventory_movements m
             WHERE m.ref_table = 'stock_adjustments' AND m.ref_id = stock_adjustments.id AND m.active = 1),
             value)
           WHERE variant_id = ?""",
        (variant_id,),
    )
