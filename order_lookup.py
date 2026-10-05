"""
Order lookup in Afterbuy with a Redis cache for found orders
"""
import logging

from afterbuy_client import AfterbuyClient
from config import Config
from jobs_queue import cache_get, cache_set

logger = logging.getLogger(__name__)


def get_order_from_afterbuy(order_number):
    """
    Get order data from AfterBuy API by Rechnungsnummer (InvoiceNumber) or OrderID

    Args:
        order_number: The invoice number (Rechnungsnummer) or order ID to look up

    Returns:
        Dictionary with order data or None if not found
    """
    cache_key = f"afterbuy:order:{order_number}"
    cached = cache_get(cache_key)
    if cached:
        logger.info(f"Order {order_number} served from Afterbuy cache")
        return cached

    order_data = _fetch_order_from_afterbuy(order_number)
    # Only hits are cached: None also means "Afterbuy timed out"
    if order_data:
        cache_set(cache_key, order_data, Config.AFTERBUY_CACHE_TTL)
    return order_data


def _fetch_order_from_afterbuy(order_number):
    try:
        afterbuy_client = AfterbuyClient(
            partner_id=Config.AFTERBUY_PARTNER_ID,
            partner_token=Config.AFTERBUY_PARTNER_TOKEN,
            account_token=Config.AFTERBUY_ACCOUNT_TOKEN,
            user_id=Config.AFTERBUY_USER_ID,
            user_password=Config.AFTERBUY_USER_PASSWORD,
            timeout=(Config.AFTERBUY_CONNECT_TIMEOUT, Config.AFTERBUY_READ_TIMEOUT),
        )

        # First try to find by InvoiceNumber (Rechnungsnummer)
        order_data = afterbuy_client.get_order_by_invoice_number(order_number)

        if order_data:
            logger.info(
                f"Successfully retrieved order by Rechnungsnummer {order_number} from AfterBuy"
            )
            return order_data

        # If not found, try by OrderID
        order_data = afterbuy_client.get_order_by_id(order_number)

        if order_data:
            logger.info(
                f"Successfully retrieved order by OrderID {order_number} from AfterBuy"
            )
            return order_data
        else:
            logger.warning(
                f"Order {order_number} not found in AfterBuy (tried both Rechnungsnummer and OrderID)"
            )
            return None

    except Exception as e:
        logger.error(f"Error retrieving order {order_number} from AfterBuy: {str(e)}")
        return None
