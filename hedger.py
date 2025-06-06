import asyncio
import os
from dotenv import load_dotenv
from deribit_api import DeribitClient
from logger import logger

load_dotenv()


CURRENCIES = [c.strip().upper() for c in os.getenv("CURRENCY", "ETH").split(",")]

PORTFOLIO_DELTA_TARGET = float(os.getenv("PORTFOLIO_DELTA_TARGET"))
PORTFOLIO_DELTA_STEP = float(os.getenv("PORTFOLIO_DELTA_STEP"))

DELTA_CHECK_FREQ_IN_SEC = int(os.getenv("DELTA_CHECK_FREQ_IN_SEC", "10"))

MIN_ORDER_SIZE = int(os.getenv("MIN_ORDER_SIZE", "10"))

def get_portfolio_data(positions):
    delta_options = 0
    delta_future = 0
    index_price = 0
    future_size = 0

    for pos in positions:
        if pos["kind"] == "option":
            delta = pos["delta"] or 0
            index_price = pos["index_price"]
            delta_options += delta
        if pos["kind"] == "future" and pos["instrument_name"].endswith("PERPETUAL"):
            delta_future = pos["delta"] or 0
            future_size = pos["size"]
            index_price = pos["index_price"]


    return delta_options, delta_future, future_size, index_price


def calculate_order_size(delta_options, index_price, current_future_amount, contract_size):
    hedge_target = -delta_options * index_price
    order_size = hedge_target - current_future_amount
    order_size = int(order_size / contract_size) * contract_size

    return int(order_size)

def hedge_required(abs_portfolio_delta, delta_target, delta_step):
    if abs_portfolio_delta <= delta_target:
        return False

    if delta_step == 0:
        return True  # если шаг не задан, хеджируем при любом превышении

    step = (abs_portfolio_delta - delta_target) / delta_step

    return step >= 1

async def run():
    client = DeribitClient()
    connected = await client.connect()

    if not connected:
        logger.error("❌ Невозможно продолжить — ошибка подключения или авторизации")
        client.close
        return

    if not client.has_trading_permissions:
        logger.error("❌ Данное подключение не имеет права на торговлю")
        client.close
        return

    contract_sizes = {}

    for currency in CURRENCIES:
        instrument_name = f"{currency}-PERPETUAL"
        contract_size = await client.get_contract_size(instrument_name)
        if contract_size <= 0:
            logger.error(f"[{currency}] ❌ Некорректный размер контракта: {contract_size}")
        else:
            contract_sizes[currency] = contract_size

        await asyncio.sleep(0.2)

    logger.info("✅ Подключение и авторизация успешны. Запускаем дельта-хедж")

    while True:
        try:
            for currency in CURRENCIES:

                perp_instrument = f"{currency}-PERPETUAL"
                contract_size = contract_sizes[currency]

                positions = await client.get_positions(currency)
                delta_options, delta_future, future_size, index_price = get_portfolio_data(positions)

                portfolio_delta = round(delta_options + delta_future, 4)

                logger.info(
                    f"[{currency}] Дельта портфеля: {portfolio_delta:.4f} | "
                    f"Дельта опционов: {delta_options:.4f} | "
                    f"Дельта фьючерса: {delta_future:.4f} | "
                    f"Позиция по фьючерсу: {future_size:.0f} | "
                    f"Index price: {index_price}"
                )

                if hedge_required(abs(portfolio_delta), PORTFOLIO_DELTA_TARGET, PORTFOLIO_DELTA_STEP):
                    order_size = calculate_order_size(delta_options, index_price, future_size, contract_size)


                    if abs(order_size) >= MIN_ORDER_SIZE:
                        logger.info(f"[{currency}] Коррекция хеджа (USD): {order_size}")
                        await client.place_order(perp_instrument, order_size)
                    else:
                        logger.warning(f"[{currency}] Объем ордера слишком мал: {order_size}")
                else:
                    logger.info(f"[{currency}] Хеджирование не требуется")

                await asyncio.sleep(0.2)

        except Exception as e:
            logger.exception("❌ Ошибка в основном цикле:")

        await asyncio.sleep(DELTA_CHECK_FREQ_IN_SEC)


if __name__ == "__main__":
    asyncio.run(run())
