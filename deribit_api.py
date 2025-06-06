import json
import os
import ssl
import certifi

from dotenv import load_dotenv
from websockets.legacy.client import connect
from logger import logger

load_dotenv()

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
WS_URL = os.getenv("API_URL")  # wss://test.deribit.com/ws/api/v2
CURRENCY = os.getenv("CURRENCY", "ETH").upper()

ssl_context = ssl.create_default_context(cafile=certifi.where())


class DeribitClient:
    def __init__(self):
        self.ws = None
        self._id_counter = 100  # начальное значение ID, чтобы избежать пересечений
        self.has_trading_permissions = False

    def _next_id(self):
        self._id_counter += 1
        return self._id_counter

    async def connect(self):
        try:
            self.ws = await connect(WS_URL, ssl=ssl_context)
            auth_success = await self.authenticate()
            return auth_success
        except Exception as e:
            logger.error("❌ Ошибка подключения:", e)
            return False

    async def authenticate(self):
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "public/auth",
            "params": {
                "grant_type": "client_credentials",
                "client_id": API_KEY,
                "client_secret": API_SECRET
            }
        }
        response = await self.send_request(req)
        auth_success = False
        if "result" in response:
            scopes = response["result"]["scope"].split()
            auth_success = True
            if "trade:read_write" in scopes:
                self.has_trading_permissions = True
            else:
                self.has_trading_permissions = False
        else:
            logger.error("❌ Auth failed:", response)
            self.has_trading_permissions = False

        return auth_success

    def is_ws_open(self):
        return self.ws and not self.ws.closed

    async def send_request(self, request_dict):
        if not self.is_ws_open():
            logger.warning("🔄 WebSocket закрыт. Выполняем реконнект...")
            await self.connect()

        await self.ws.send(json.dumps(request_dict))

        while True:
            response_raw = await self.ws.recv()
            response = json.loads(response_raw)
            if response.get("id") == request_dict["id"]:
                return response

    async def get_positions(self):
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "private/get_positions",
            "params": {
                "currency": CURRENCY,
                "kind": "any"
            }
        }
        response = await self.send_request(req)
        return response.get("result", [])

    async def place_order(self, instrument_name, usd_amount):
        direction = "buy" if usd_amount > 0 else "sell"
        amount = round(abs(usd_amount))
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": f"private/{direction}",
            "params": {
                "instrument_name": instrument_name,
                "amount": amount,
                "type": "market"
            }
        }

        response = await self.send_request(req)
        logger.info(f"📤 Отправлен рыночный ордер:  {instrument_name} {direction.upper()}  объемом {amount} USD")

    async def close(self):
        if self.ws:
            await self.ws.close()
