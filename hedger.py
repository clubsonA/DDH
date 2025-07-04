import asyncio
import os
from dotenv import load_dotenv
from deribit_api import DeribitClient
from logger import logger

load_dotenv()


CURRENCIES = [c.strip().upper() for c in os.getenv("CURRENCIES", "ETH").split(",")]

PORTFOLIO_DELTA_TARGET = float(os.getenv("PORTFOLIO_DELTA_TARGET"))
PORTFOLIO_DELTA_STEP = float(os.getenv("PORTFOLIO_DELTA_STEP"))
PRICE_STEP_PCT = float(os.getenv("PRICE_STEP_PCT"))

DELTA_CHECK_FREQ_IN_SEC = int(os.getenv("DELTA_CHECK_FREQ_IN_SEC", "10"))

MIN_ORDER_SIZE_IN_CONTRACTS = int(os.getenv("MIN_ORDER_SIZE_IN_CONTRACTS", "10"))

def get_portfolio_data(positions):
    delta_options = 0
    delta_future = 0

    future_size = 0
    net_delta_options = 0


    for pos in positions:
        if pos["kind"] == "option":
            delta = pos["delta"] or 0
            logger.debug(f"Delta option: {delta} mark price option: {pos['mark_price']}")
            net_delta = delta  - pos["mark_price"]

            delta_options += delta
            net_delta_options += net_delta
        if pos["kind"] == "future" and pos["instrument_name"].endswith("PERPETUAL"):
            delta_future = pos["delta"] or 0
            future_size = pos["size"]



    return net_delta_options, delta_future, future_size


def calculate_order_size(delta_options, mark_price, current_future_amount, contract_size):
    hedge_target = -delta_options * mark_price
    order_size = hedge_target - current_future_amount
    order_size = int(order_size / contract_size) * contract_size

    return int(order_size)

def hedge_required(abs_portfolio_delta, delta_target, delta_step, mark_price, current_price, price_step_pct):
    # Отклонение от опорной цены в процентах
    price_deviation_pct = abs(mark_price - current_price) / current_price * 100

    if abs_portfolio_delta <= delta_target and not (
        price_step_pct > 0 and price_deviation_pct >= price_step_pct
    ):
        logger.debug(f"price_step_pct > 0 and price_deviation_pct >= price_step_pct: {price_step_pct} > 0 and {price_deviation_pct} >= {price_step_pct}")
        return False

    if delta_step > 0 and (abs_portfolio_delta - delta_target) / delta_step >= 1:
        return True

    if price_step_pct > 0 and price_deviation_pct >= price_step_pct:
        return True

    return False



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
    reference_prices = {currency: 0 for currency in CURRENCIES}

    while True:
        try:
            for currency in CURRENCIES:
                perp_instrument = f"{currency}-PERPETUAL"
                contract_size = contract_sizes[currency]
                mark_price, index_price = await client.get_mark_price(perp_instrument)
                logger.debug(mark_price)

                positions = await client.get_positions(currency)
                delta_options, delta_future, future_size = get_portfolio_data(positions)
                portfolio_delta = round(delta_options + delta_future, 4)

                if reference_prices[currency] == 0:
                    reference_prices[currency] = mark_price

                logger.info(
                    f"[{currency}] Дельта портфеля: {portfolio_delta:.4f} | Дельта фьючерса: {delta_future:.4f} Дельта опциона: {delta_options:.4f} | "
                    f"Market (Index) price: {mark_price} ({index_price}) | "
                    f"Reference price: {reference_prices[currency]}"
                )

                if hedge_required(
                    abs_portfolio_delta=abs(portfolio_delta),
                    delta_target=PORTFOLIO_DELTA_TARGET,
                    delta_step=PORTFOLIO_DELTA_STEP,
                    mark_price=mark_price,
                    current_price=reference_prices[currency],
                    price_step_pct=PRICE_STEP_PCT
                ):
                    order_size = calculate_order_size(delta_options, mark_price, future_size, contract_size)

                    if abs(order_size) >= MIN_ORDER_SIZE_IN_CONTRACTS * contract_size:
                        logger.info(f"[{currency}] Коррекция хеджа (USD): {order_size}")
                        await client.place_order(perp_instrument, order_size)
                        # сбрасываем reference_price на новую опорную точку
                        reference_prices[currency] = mark_price
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
