import asyncio
import os
from dotenv import load_dotenv
from deribit_api import DeribitClient
from logger import logger

load_dotenv()

CURRENCY = os.getenv("CURRENCY", "ETH")
PORTFOLIO_DELTA_TARGET = float(os.getenv("PORTFOLIO_DELTA_TARGET"))
PORTFOLIO_DELTA_STEP = float(os.getenv("PORTFOLIO_DELTA_STEP"))
PERP_INSTRUMENT_NAME = f"{CURRENCY}-PERPETUAL"
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


def calculate_order_size(delta_options, index_price, current_future_amount):
    hedge_target = -delta_options * index_price
    order_size = hedge_target - current_future_amount

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

    contract_size = await client.get_contract_size(PERP_INSTRUMENT_NAME)
    if contract_size <= 0:
        logger.error(f"❌ Некорректный размер контракта: {contract_size}")
        client.close
        return

    logger.info("✅ Подключение и авторизация успешны. Запускаем дельта-хедж")

    while True:
        try:
            positions = await client.get_positions() #Получаем позиции по фьючерсу и опционам

            delta_options, delta_future, future_size, index_price = get_portfolio_data(positions)

            if delta_options == 0:
                logger.info("⏸️ Необходимость в хеджировании отсутсвует. Ждём...")
                await asyncio.sleep(DELTA_CHECK_FREQ_IN_SEC)
                continue

            portfolio_delta = round(delta_options + delta_future, 4)

            logger.info(
                f"Дельта портфеля: {portfolio_delta:.4f} |"
                f"Дельта опционов : {delta_options:.4f} |  "
                f"Дельта фьючерса : {delta_future:.4f} | "
                f"Позиция по фьючерсу: {future_size:.0f} | "
                f"Index price: {index_price}"
                )

            if  hedge_required(abs(portfolio_delta), PORTFOLIO_DELTA_TARGET, PORTFOLIO_DELTA_STEP):
                order_size = calculate_order_size(delta_options, index_price, future_size)
                order_size = int(order_size / contract_size) * contract_size # делаем размер ордера кратным контракту
                if abs(order_size) >= MIN_ORDER_SIZE:
                    logger.info(f"Коррекция хеджа (USD): {order_size}")
                    await client.place_order(PERP_INSTRUMENT_NAME, order_size)
                else:
                   logger.warning(f"Коррекция хеджа невозможна, слишком маленький объем оредра: {order_size}")
            else:
                logger.info("Дельта в пределах нормы ")

        except Exception as e:
            logger.error("❌ Ошибка:", e)

        await asyncio.sleep(DELTA_CHECK_FREQ_IN_SEC)

if __name__ == "__main__":
    asyncio.run(run())
