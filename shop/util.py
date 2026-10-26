"""Validation, money and date helpers shared by the service layer."""
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

IST = timezone(timedelta(hours=5, minutes=30))

PAYMENT_METHODS = ["Cash", "UPI", "Card", "Bank Transfer", "Cheque"]
EPS = 1e-9


class ApiError(Exception):
    def __init__(self, status, message, field=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.field = field


def bad(message, field=None):
    return ApiError(400, message, field)


def money(x):
    """Round to paise, half up."""
    return float(Decimal(repr(float(x))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def qty_round(x):
    return float(Decimal(repr(float(x))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def today():
    return datetime.now(IST).date().isoformat()


def now_iso():
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")


def v_date(value, field, required=True):
    if value in (None, ""):
        if required:
            raise bad("Date is required", field)
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise bad("Invalid date", field)
    try:
        d = date.fromisoformat(value)
    except ValueError:
        raise bad("Invalid date", field)
    if d.isoformat() > (datetime.now(IST).date() + timedelta(days=1)).isoformat():
        raise bad("Date cannot be in the future", field)
    if d.year < 2000:
        raise bad("Date is too far in the past", field)
    return d.isoformat()


def v_str(value, field, required=False, max_len=200, label=None):
    if value is None:
        value = ""
    if not isinstance(value, (str, int, float)):
        raise bad("Invalid value", field)
    value = str(value).strip()
    if required and not value:
        raise bad("%s is required" % (label or field.replace("_", " ").capitalize()), field)
    if len(value) > max_len:
        raise bad("Too long (max %d characters)" % max_len, field)
    return value


def v_num(value, field, min_value=None, max_value=None, required=True, gt=None, label=None, default=0.0):
    name = label or field.replace("_", " ").capitalize()
    if value in (None, ""):
        if required:
            raise bad("%s is required" % name, field)
        return default
    if isinstance(value, bool):
        raise bad("%s must be a number" % name, field)
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise bad("%s must be a number" % name, field)
    if num != num or num in (float("inf"), float("-inf")):
        raise bad("%s must be a number" % name, field)
    if gt is not None and not num > gt:
        raise bad("%s must be greater than %s" % (name, _fmt(gt)), field)
    if min_value is not None and num < min_value - EPS:
        raise bad("%s cannot be less than %s" % (name, _fmt(min_value)), field)
    if max_value is not None and num > max_value + EPS:
        raise bad("%s cannot be more than %s" % (name, _fmt(max_value)), field)
    return num


def v_int(value, field, required=True, label=None):
    if value in (None, ""):
        if required:
            raise bad("%s is required" % (label or field.replace("_", " ").capitalize()), field)
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        return int(value)
    raise bad("Invalid %s" % (label or field.replace("_", " ")), field)


def v_choice(value, field, choices, label=None):
    if value not in choices:
        raise bad("Select a valid %s" % (label or field.replace("_", " ")), field)
    return value


def v_method(value, field="payment_method"):
    return v_choice(value, field, PAYMENT_METHODS, "payment method")


def account_for(method):
    return "cash" if method == "Cash" else "bank"


def _fmt(n):
    return ("%d" % n) if float(n).is_integer() else str(n)


def jdump(obj):
    return json.dumps(obj, default=str, separators=(",", ":"))


def month_key(d):
    return d[:7]


def fy_start(d=None):
    d = date.fromisoformat(d) if d else datetime.now(IST).date()
    year = d.year if d.month >= 4 else d.year - 1
    return date(year, 4, 1).isoformat()
