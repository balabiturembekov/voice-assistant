"""
Order status as Lisa tells it: estimated delivery window, stage, open amount,
caller verification. Pure functions, no Flask/DB.
"""
import logging
import re
from datetime import date, datetime, timedelta

from config import Config

logger = logging.getLogger(__name__)

# Production starts about a week after the order; shipping takes ~2 more weeks
PRODUCTION_START_DELAY = timedelta(weeks=1)
SHIPPING_TIME = timedelta(weeks=2)
WINDOW_HALF_WIDTH = timedelta(days=3)
# Phone numbers are compared by their last digits (+49 176… vs 0176…)
PHONE_MATCH_DIGITS = 9

MONTHS_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]
MONTHS_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Where the delivery information comes from, most reliable first
SOURCE_SHIPPED = "shipped"      # Afterbuy ShippingInfo/DeliveryDate: staff marked it shipped
SOURCE_PLANNED = "planned"      # "KW a - b" written by staff in the Afterbuy memo
SOURCE_ESTIMATED = "estimated"  # formula from the order date (PRODUCTION_WEEKS)

# Orders paid through a marketplace show AlreadyPaid 0,00 in Afterbuy
MARKETPLACES = ("otto", "kaufland", "temu", "ebay", "amazon", "hood")
KW_RANGE = re.compile(r"\bKW\s*(\d{1,2})(?:\s*[-–/]\s*(?:KW\s*)?(\d{1,2}))?", re.IGNORECASE)

STAGE_PRODUCTION = "production"
STAGE_DELIVERY_SOON = "delivery_soon"
STAGE_OVERDUE = "overdue"


def production_weeks():
    """PRODUCTION_WEEKS '8-12' -> (8, 12)"""
    try:
        low, high = (int(part) for part in Config.PRODUCTION_WEEKS.split("-"))
        return low, high
    except ValueError:
        logger.error(f"Invalid PRODUCTION_WEEKS: {Config.PRODUCTION_WEEKS!r}, using 8-12")
        return 8, 12


def parse_order_date(text):
    """Afterbuy '18.10.2025 16:27:55' -> date, None if missing/invalid"""
    if not text:
        return None
    try:
        return datetime.strptime(text.split()[0], "%d.%m.%Y").date()
    except ValueError:
        logger.warning(f"Cannot parse order date: {text!r}")
        return None


def delivery_window(order_date):
    """Estimated (start, end) of delivery for an order date"""
    _, max_weeks = production_weeks()
    expected = order_date + PRODUCTION_START_DELAY + timedelta(weeks=max_weeks) + SHIPPING_TIME
    return expected - WINDOW_HALF_WIDTH, expected + WINDOW_HALF_WIDTH


def delivery_stage(window, today=None):
    today = today or date.today()
    start, end = window
    if today > end:
        return STAGE_OVERDUE
    if today >= start - timedelta(weeks=1):
        return STAGE_DELIVERY_SOON
    return STAGE_PRODUCTION


def promised_weeks(order_data):
    """Last "KW a - b" (or "KW a") in the memo, staff's current delivery promise"""
    matches = KW_RANGE.findall(order_data.get("memo") or "")
    for first, last in reversed(matches):
        a, b = int(first), int(last or first)
        if 1 <= a <= 53 and 1 <= b <= 53:
            return a, b
    return None


def week_window(weeks, order_date):
    """Calendar weeks (a, b) -> (Monday of a, Sunday of b), year inferred from the order date"""
    a, b = weeks
    earliest = order_date - timedelta(days=14)
    for year in (order_date.year, order_date.year + 1):
        try:
            start = date.fromisocalendar(year, a, 1)
        except ValueError:
            continue
        if start >= earliest:
            end_year = year + 1 if b < a else year
            try:
                return start, date.fromisocalendar(end_year, b, 7)
            except ValueError:
                return None
    return None


def delivery_info(order_data, today=None):
    """What Lisa can say about delivery: {source, stage, shipped_on | weeks + window}"""
    shipped_on = parse_order_date((order_data.get("shipping") or {}).get("delivery_date"))
    if shipped_on:
        return {"source": SOURCE_SHIPPED, "shipped_on": shipped_on, "stage": None}

    order_date = parse_order_date(order_data.get("order_date"))
    if order_date is None:
        return None

    weeks = promised_weeks(order_data)
    window = week_window(weeks, order_date) if weeks else None
    if window:
        return {"source": SOURCE_PLANNED, "weeks": weeks, "window": window,
                "stage": delivery_stage(window, today)}

    window = delivery_window(order_date)
    return {"source": SOURCE_ESTIMATED, "weeks": None, "window": window,
            "stage": delivery_stage(window, today)}


def parse_amount(text):
    """Afterbuy amount ('1.680,50', '1680,50' or '1680.50') -> float, None if invalid"""
    if not text:
        return None
    value = str(text).strip()
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(",", ".")
    try:
        return float(value)
    except ValueError:
        logger.warning(f"Cannot parse amount: {text!r}")
        return None


def is_marketplace(order_data):
    """Order sold on Otto, Kaufland, TEMU, eBay, ...: the marketplace collects the money"""
    platform = (order_data.get("platform") or "").lower()
    method = ((order_data.get("payment") or {}).get("payment_method") or "").lower()
    return any(name in platform or name in method for name in MARKETPLACES)


def open_amount(order_data):
    """Outstanding balance (full - paid), 0 if unknown, settled or paid via a marketplace"""
    if is_marketplace(order_data):
        return 0.0
    payment = order_data.get("payment") or {}
    full = parse_amount(payment.get("full_amount"))
    paid = parse_amount(payment.get("already_paid")) or 0.0
    if not full:
        return 0.0
    return max(round(full - paid, 2), 0.0)


def euro_for_speech(amount, language="de"):
    """1680.5 -> '1680 Euro und 50 Cent' (TTS reads it naturally, no 'Komma')"""
    cents_total = int(round(amount * 100))
    euros, cents = divmod(cents_total, 100)
    if language == "de":
        return f"{euros} Euro" + (f" und {cents} Cent" if cents else "")
    return f"{euros} euros" + (f" and {cents} cents" if cents else "")


def date_for_speech(value, language="de"):
    """date(2026, 12, 29) -> '29. Dezember' / 'December 29'"""
    if language == "de":
        return f"{value.day}. {MONTHS_DE[value.month - 1]}"
    return f"{MONTHS_EN[value.month - 1]} {value.day}"


def number_for_speech(number):
    """'24896241' -> '2 4 8 9 6 2 4 1' so it is read digit by digit"""
    return " ".join(str(number))


def _digits(text):
    return re.sub(r"\D", "", text or "")


def phone_matches(caller_number, order_phone):
    caller, stored = _digits(caller_number), _digits(order_phone)
    if len(caller) < PHONE_MATCH_DIGITS or len(stored) < PHONE_MATCH_DIGITS:
        return False
    return caller[-PHONE_MATCH_DIGITS:] == stored[-PHONE_MATCH_DIGITS:]


def postal_code_matches(entered, order_postal_code):
    stored = _digits(order_postal_code)
    return bool(stored) and _digits(entered) == stored


def order_phone(order_data):
    return (order_data.get("buyer") or {}).get("phone")


def order_postal_code(order_data):
    return (order_data.get("buyer") or {}).get("postal_code")
