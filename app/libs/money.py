"""Money types and coercion.

Every column that holds an amount of money uses :data:`MONEY`
(``NUMERIC(12, 2)``), not ``Float``. Binary floating point cannot represent
most naira-and-kobo values exactly -- ``0.1 + 0.2 != 0.3`` -- and the error
compounds across a ledger that is read, modified and written back on every
credit, debit, settlement and refund.

SQLAlchemy hands ``NUMERIC`` back as :class:`decimal.Decimal`, which will not
mix with ``float`` in arithmetic (``Decimal('1') + 1.0`` raises TypeError).
That is a feature: it turns silent precision loss into a loud error at the
exact line where a float snuck in. Use :func:`to_money` at the boundary --
where a value arrives from a request body, a gateway payload or a float
literal -- and keep it Decimal from there on.

12 digits with 2 after the point tops out at 9,999,999,999.99, which is
comfortably beyond any single Markt transaction while staying well inside the
range PostgreSQL stores compactly.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union

from external.database import db

#: The column type for every monetary amount.
MONEY = db.Numeric(12, 2)

#: Rounding for money: 0.005 goes up, matching how humans (and invoices) round.
#: Python's default is ROUND_HALF_EVEN, which would round 0.005 to 0.00.
CENTS = Decimal("0.01")

Numberish = Union[int, float, str, Decimal, None]


def to_money(value: Numberish) -> Optional[Decimal]:
    """Coerce anything number-shaped to a 2dp Decimal.

    Returns None for None so it can be used on nullable columns.

    Floats are routed through ``str`` deliberately: ``Decimal(0.1)`` captures
    the full binary error (0.1000000000000000055511151231257827...), whereas
    ``Decimal(str(0.1))`` gives exactly ``Decimal('0.1')``.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, float):
        dec = Decimal(str(value))
    else:
        dec = Decimal(value)
    return dec.quantize(CENTS, rounding=ROUND_HALF_UP)


def money_to_float(value: Numberish) -> Optional[float]:
    """For serializers and gateway payloads that require a JSON number.

    Safe at 2dp: every value NUMERIC(12,2) can hold round-trips through a
    float exactly at this precision.
    """
    if value is None:
        return None
    return float(value)


def to_subunit(value: Numberish) -> int:
    """Naira -> kobo, the subunit Paystack expects for every amount field.

    Exact once the input is Decimal: ``Decimal('1234.56') * 100`` is
    ``Decimal('123456.00')``. The old float version evaluated
    ``int(1234.56 * 100)`` as 123455 and silently undercharged by a kobo.
    """
    amount = to_money(value)
    if amount is None:
        raise ValueError("Cannot convert None to a currency subunit")
    return int(amount * 100)
