import requests
import xml.etree.ElementTree as ET
from typing import Dict, Optional, List
import re


class AfterbuyClient:
    """Client for AfterBuy API integration"""

    def __init__(
        self,
        partner_id: str,
        partner_token: str,
        account_token: str,
        user_id: str,
        user_password: str,
    ):
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
    <PartnerID>{self.partner_id}</PartnerID>
    <PartnerToken>{self.partner_token}</PartnerToken>
    <AccountToken>{self.account_token}</AccountToken>
    <UserID>{self.user_id}</UserID>
    <UserPassword>{self.user_password}</UserPassword>
    <CallName>GetSoldItems</CallName>
    <DetailLevel>1</DetailLevel>
    <ErrorLanguage>DE</ErrorLanguage>
  </AfterbuyGlobal>
  <DataFilter>
    <Filter>
      <FilterName>OrderID</FilterName>
      <FilterValues>
        <FilterValue>{order_id}</FilterValue>
      </FilterValues>
    </Filter>
  </DataFilter>
</Request>"""

        headers = {"Content-Type": "text/xml"}
        try:
            response = requests.post(
                self.url, data=xml_data, headers=headers, timeout=30
            )

            if response.status_code != 200:
                print(f"AfterBuy API returned status code {response.status_code}")
                return None

            if not response.text:
                print("AfterBuy API returned empty response")
                return None

            return self._parse_order_response(response.text)
        except requests.exceptions.RequestException as e:
            print(f"Error calling AfterBuy API: {e}")
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
    <PartnerID>{self.partner_id}</PartnerID>
    <PartnerToken>{self.partner_token}</PartnerToken>
    <AccountToken>{self.account_token}</AccountToken>
    <UserID>{self.user_id}</UserID>
    <UserPassword>{self.user_password}</UserPassword>
    <CallName>GetSoldItems</CallName>
    <DetailLevel>1</DetailLevel>
    <ErrorLanguage>DE</ErrorLanguage>
  </AfterbuyGlobal>
  <DataFilter>
    <Filter>
      <FilterName>InvoiceNumber</FilterName>
      <FilterValues>
        <FilterValue>{invoice_number}</FilterValue>
      </FilterValues>
    </Filter>
  </DataFilter>
</Request>"""

        headers = {"Content-Type": "text/xml"}
        try:
            response = requests.post(
                self.url, data=xml_data, headers=headers, timeout=30
            )

            if response.status_code != 200:
                print(f"AfterBuy API returned status code {response.status_code}")
                return None

            if not response.text:
                print("AfterBuy API returned empty response")
                return None

            return self._parse_order_response(response.text)
        except requests.exceptions.RequestException as e:
            print(f"Error calling AfterBuy API: {e}")
            return None

    def _parse_order_response(self, xml_content: str) -> Optional[Dict]:
        """Parse XML response from AfterBuy API"""
        if not xml_content or not xml_content.strip():
            print("Empty XML content provided to _parse_order_response")
            return None

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            print(f"Error parsing XML: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error parsing XML: {e}")
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
            print("Order element not found in XML response")
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
                }
            )

        order_data["items"] = items

        # Parse shipping info
        shipping_info = order.find(".//ShippingInfo")
        if shipping_info is not None:
            order_data["shipping"] = {
                "cost": self._get_text(shipping_info, "ShippingCost"),
                "total_cost": self._get_text(shipping_info, "ShippingTotalCost"),
                "tax_rate": self._get_text(shipping_info, "ShippingTaxRate"),
            }

        return order_data

    def parse_memo(self, memo_text: str) -> Dict:
        """
        Parse the Memo field which contains structured order information

        Example memo:
        20.10.2025
        Rayan Daouk
        131629 Anzahlung 15 .
        1.680,00 EUR
        https://farm01.afterbuy.de/afterbuy/shop/shopvorschau.aspx?id=180772819

        Returns:
            Dictionary with parsed memo data
        """
        if not memo_text:
            return {}

        lines = [line.strip() for line in memo_text.strip().split("\n") if line.strip()]

        result = {
            "raw_memo": memo_text,
            "date": None,
            "customer_name": None,
            "order_info": None,
            "amount": None,
            "amount_value": None,
            "link": None,
        }

        for i, line in enumerate(lines):
            # Check if line is a date (DD.MM.YYYY)
            if re.match(r"\d{2}\.\d{2}\.\d{4}", line):
                result["date"] = line

            # Check if line is an amount (e.g., "1.680,00 EUR" or "1,680.00 EUR")
            elif re.match(r"[\d.,]+\s*EUR", line.upper()):
                result["amount"] = line
                # Extract numeric value
                amount_clean = (
                    line.replace(".", "").replace(",", ".").replace("EUR", "").strip()
                )
                try:
                    result["amount_value"] = float(amount_clean)
                except:
                    pass

            # Check if line is a URL
            elif line.startswith("http://") or line.startswith("https://"):
                result["link"] = line

            # Check if line contains order number and payment type (e.g., "131629 Anzahlung 15 %")
            elif re.search(r"\d+.*Anzahlung", line, re.IGNORECASE):
                result["order_info"] = line
                # Try to extract payment percentage
                percent_match = re.search(r"(\d+)\s*%", line)
                if percent_match:
                    result["payment_percent"] = percent_match.group(1)

            # If previous line was date, this is likely customer name
            elif i > 0 and re.match(r"\d{2}\.\d{2}\.\d{4}", lines[i - 1]):
                result["customer_name"] = line

        return result

    def _get_text(self, element, tag):
        """Helper method to safely get text from XML element"""
        if element is None:
            return None

        child = element.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        return None


def create_client_from_config(config):
    """Create AfterbuyClient from config"""
    # These should be added to config.py or .env
    import os
    from dotenv import load_dotenv

    load_dotenv()

    return AfterbuyClient(
        partner_id=os.getenv("AFTERBUY_PARTNER_ID", "113464"),
        partner_token=os.getenv(
            "AFTERBUY_PARTNER_TOKEN", "6722d455-4d02-4da3-97ef-f5dfcf73656d"
        ),
        account_token=os.getenv(
            "AFTERBUY_ACCOUNT_TOKEN", "53217733-1987-4cf8-a065-2c2591e4765c"
        ),
        user_id=os.getenv("AFTERBUY_USER_ID", "Balabi"),
        user_password=os.getenv("AFTERBUY_USER_PASSWORD", "Parol4Balabi2025!"),
    )
