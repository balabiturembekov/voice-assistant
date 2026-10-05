import requests
import xml.etree.ElementTree as ET
from typing import Dict, Optional, List
import re
import logging
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)


class AfterbuyClient:
    """Client for AfterBuy API integration"""

    def __init__(
        self,
        partner_id: str,
        partner_token: str,
        account_token: str,
        user_id: str,
        user_password: str,
        timeout=(3, 5),
    ):
        self.timeout = timeout
        self.partner_id = partner_id
        self.partner_token = partner_token
        self.account_token = account_token
        self.user_id = user_id
        self.user_password = user_password
        self.url = "https://api.afterbuy.de/afterbuy/ABInterface.aspx"

    def get_order_by_id(self, order_id: str) -> Optional[Dict]:
        """
        Get order details by OrderID

        Args:
            order_id: The order ID to search for

        Returns:
            Dictionary with parsed order data or None if not found
        """
        xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
<Request>
  <AfterbuyGlobal>
    <PartnerID>{escape(str(self.partner_id))}</PartnerID>
    <PartnerToken>{escape(str(self.partner_token))}</PartnerToken>
    <AccountToken>{escape(str(self.account_token))}</AccountToken>
    <UserID>{escape(str(self.user_id))}</UserID>
    <UserPassword>{escape(str(self.user_password))}</UserPassword>
    <CallName>GetSoldItems</CallName>
    <DetailLevel>1</DetailLevel>
    <ErrorLanguage>DE</ErrorLanguage>
  </AfterbuyGlobal>
  <DataFilter>
    <Filter>
      <FilterName>OrderID</FilterName>
      <FilterValues>
        <FilterValue>{escape(str(order_id))}</FilterValue>
      </FilterValues>
    </Filter>
  </DataFilter>
</Request>"""

        headers = {"Content-Type": "text/xml"}
        try:
            response = requests.post(
                self.url, data=xml_data, headers=headers, timeout=self.timeout
            )

            if response.status_code != 200:
                logger.error(f"AfterBuy API returned status code {response.status_code}")
                return None

            if not response.text:
                logger.error("AfterBuy API returned empty response")
                return None

            return self._parse_order_response(response.text)
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling AfterBuy API: {e}")
            return None

    def get_order_by_invoice_number(self, invoice_number: str) -> Optional[Dict]:
        """
        Get order details by InvoiceNumber (Rechnungsnummer)

        Args:
            invoice_number: The invoice number (Rechnungsnummer) to search for

        Returns:
            Dictionary with parsed order data or None if not found
        """
        xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
<Request>
  <AfterbuyGlobal>
    <PartnerID>{escape(str(self.partner_id))}</PartnerID>
    <PartnerToken>{escape(str(self.partner_token))}</PartnerToken>
    <AccountToken>{escape(str(self.account_token))}</AccountToken>
    <UserID>{escape(str(self.user_id))}</UserID>
    <UserPassword>{escape(str(self.user_password))}</UserPassword>
    <CallName>GetSoldItems</CallName>
    <DetailLevel>1</DetailLevel>
    <ErrorLanguage>DE</ErrorLanguage>
  </AfterbuyGlobal>
  <DataFilter>
    <Filter>
      <FilterName>InvoiceNumber</FilterName>
      <FilterValues>
        <FilterValue>{escape(str(invoice_number))}</FilterValue>
      </FilterValues>
    </Filter>
  </DataFilter>
</Request>"""

        headers = {"Content-Type": "text/xml"}
        try:
            response = requests.post(
                self.url, data=xml_data, headers=headers, timeout=self.timeout
            )

            if response.status_code != 200:
                logger.error(f"AfterBuy API returned status code {response.status_code}")
                return None

            if not response.text:
                logger.error("AfterBuy API returned empty response")
                return None

            return self._parse_order_response(response.text)
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling AfterBuy API: {e}")
            return None

    def _parse_order_response(self, xml_content: str) -> Optional[Dict]:
        """Parse XML response from AfterBuy API"""
        if not xml_content or not xml_content.strip():
            logger.warning("Empty XML content provided to _parse_order_response")
            return None

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            logger.error(f"Error parsing XML: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing XML: {e}")
            return None

        # Check if call was successful
        call_status = (
            root.find("CallStatus").text
            if root.find("CallStatus") is not None
            else None
        )
        if call_status != "Success":
            return None

        # Find the order
        orders = root.find(".//Orders")
        if orders is None or len(orders.findall("Order")) == 0:
            return None

        order = orders.find("Order")
        if order is None:
            logger.warning("Order element not found in XML response")
            return None

        # Parse basic order info
        order_data = {
            "order_id": self._get_text(order, "OrderID"),
            "invoice_number": self._get_text(order, "InvoiceNumber"),
            "order_date": self._get_text(order, "OrderDate"),
            "ebay_account": self._get_text(order, "EbayAccount"),
            "memo": self._get_text(order, "Memo"),
            "invoice_memo": self._get_text(order, "InvoiceMemo"),
            "feedback_link": self._get_text(order, "FeedbackLink"),
        }

        # Parse buyer info
        buyer_info = order.find(".//BillingAddress")
        if buyer_info is not None:
            order_data["buyer"] = {
                "first_name": self._get_text(buyer_info, "FirstName"),
                "last_name": self._get_text(buyer_info, "LastName"),
                "phone": self._get_text(buyer_info, "Phone"),
                "email": self._get_text(buyer_info, "Mail"),
                "street": self._get_text(buyer_info, "Street"),
                "postal_code": self._get_text(buyer_info, "PostalCode"),
                "city": self._get_text(buyer_info, "City"),
                "country": self._get_text(buyer_info, "CountryISO"),
            }

        # Parse payment info
        payment_info = order.find(".//PaymentInfo")
        if payment_info is not None:
            order_data["payment"] = {
                "payment_id": self._get_text(payment_info, "PaymentID"),
                "payment_date": self._get_text(payment_info, "PaymentDate"),
                "already_paid": self._get_text(payment_info, "AlreadyPaid"),
                "full_amount": self._get_text(payment_info, "FullAmount"),
                "invoice_date": self._get_text(payment_info, "InvoiceDate"),
                # e.g. "OTTO-Payments", "Kaufland", "TEMU" for marketplace orders
                "payment_method": self._get_text(payment_info, "PaymentMethod"),
                "payment_function": self._get_text(payment_info, "PaymentFunction"),
            }

        # Parse sold items
        sold_items = order.findall(".//SoldItem")
        items = []
        for item in sold_items:
            items.append(
                {
                    "item_id": self._get_text(item, "ItemID"),
                    "title": self._get_text(item, "ItemTitle"),
                    "quantity": self._get_text(item, "ItemQuantity"),
                    "price": self._get_text(item, "ItemPrice"),
                    "tax_rate": self._get_text(item, "TaxRate"),
                    "weight": self._get_text(item, "ItemWeight"),
                    "platform": self._get_text(item, "ItemPlatformName"),
                    "user_flag": self._get_text(item, "UserDefinedFlag"),
                }
            )

        order_data["items"] = items
        order_data["platform"] = next((i["platform"] for i in items if i["platform"]), None)

        # Parse shipping info
        shipping_info = order.find(".//ShippingInfo")
        if shipping_info is not None:
            order_data["shipping"] = {
                "cost": self._get_text(shipping_info, "ShippingCost"),
                "total_cost": self._get_text(shipping_info, "ShippingTotalCost"),
                "tax_rate": self._get_text(shipping_info, "ShippingTaxRate"),
                # Set by staff when the order is marked as shipped (Versanddatum)
                "delivery_date": self._get_text(shipping_info, "DeliveryDate"),
                "method": self._get_text(shipping_info, "ShippingMethod"),
                "parcel_numbers": [
                    label.text.strip()
                    for label in shipping_info.iter("ParcelLabelNumber")
                    if label.text and label.text.strip()
                ],
            }
        tracking = order.find(".//TrackingLink")
        if tracking is not None and tracking.text and tracking.text.strip():
            order_data.setdefault("shipping", {})["tracking_link"] = tracking.text.strip()

        return order_data

    def _get_text(self, element, tag):
        """Helper method to safely get text from XML element"""
        if element is None:
            return None

        child = element.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        return None
