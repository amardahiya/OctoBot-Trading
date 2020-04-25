#  Drakkar-Software OctoBot-Trading
#  Copyright (c) Drakkar-Software, All rights reserved.
#
#  This library is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3.0 of the License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library.

import pytest
from octobot_backtesting.constants import BACKTESTING_DATA_TRADES
from octobot_commons.constants import HOURS_TO_SECONDS
from octobot_commons.enums import TimeFrames, PriceIndexes

from octobot_trading.constants import CONFIG_SIMULATOR, CONFIG_SIMULATOR_FEES, CONFIG_SIMULATOR_FEES_MAKER, \
    CONFIG_SIMULATOR_FEES_TAKER
from octobot_trading.enums import FeePropertyColumns, ExchangeConstantsMarketPropertyColumns, TraderOrderType, \
    ExchangeConstantsOrderColumns

# Import required fixtures
from tests import event_loop
from tests.exchanges import simulated_trader, backtesting_config, backtesting_config, simulated_exchange_manager, \
                            DEFAULT_BACKTESTING_SYMBOL, DEFAULT_BACKTESTING_TF

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


def _get_start_index_for_timeframe(nb_candles, min_limit, timeframe_multiplier):
    return int(nb_candles - (nb_candles - min_limit) / timeframe_multiplier) - 1


def _assert_fee(fee, currency, price, rate, fee_type):
    assert fee[FeePropertyColumns.CURRENCY.value] == currency
    assert fee[FeePropertyColumns.COST.value] == price
    assert fee[FeePropertyColumns.RATE.value] == rate
    assert fee[FeePropertyColumns.TYPE.value] == fee_type


async def test_multiple_get_symbol_prices(simulated_trader):
    _, exchange_inst, trader_inst = simulated_trader

    first_data = await exchange_inst.exchange.get_symbol_prices(
        DEFAULT_BACKTESTING_SYMBOL,
        DEFAULT_BACKTESTING_TF,
        return_list=False)

    second_data = await exchange_inst.exchange.get_symbol_prices(
        DEFAULT_BACKTESTING_SYMBOL,
        DEFAULT_BACKTESTING_TF,
        return_list=False)

    # different arrays
    assert first_data is not second_data

    # second is first with DEFAULT_TF difference
    assert first_data[PriceIndexes.IND_PRICE_CLOSE.value][0] == second_data[PriceIndexes.IND_PRICE_CLOSE.value][0]
    assert first_data[PriceIndexes.IND_PRICE_TIME.value][0] == second_data[
        PriceIndexes.IND_PRICE_TIME.value][0]

    # end is end -1 with DEFAULT_TF difference
    assert first_data[PriceIndexes.IND_PRICE_CLOSE.value][-1] == second_data[PriceIndexes.IND_PRICE_CLOSE.value][-2]
    assert first_data[PriceIndexes.IND_PRICE_TIME.value][-1] + HOURS_TO_SECONDS == second_data[
        PriceIndexes.IND_PRICE_TIME.value][-1]


async def test_get_recent_trades(simulated_trader):
    _, exchange_inst, trader_inst = simulated_trader

    await exchange_inst.exchange.get_recent_trades(DEFAULT_BACKTESTING_SYMBOL)


async def test_get_all_currencies_price_ticker(simulated_trader):
    _, exchange_inst, trader_inst = simulated_trader

    await exchange_inst.exchange.get_all_currencies_price_ticker()


async def test_get_trade_fee(simulated_trader):
    _, exchange_inst, trader_inst = simulated_trader

    # force fees
    exchange_inst.config[CONFIG_SIMULATOR][CONFIG_SIMULATOR_FEES] = {
        CONFIG_SIMULATOR_FEES_MAKER: 0.05,
        CONFIG_SIMULATOR_FEES_TAKER: 0.1
    }

    buy_market_fee = exchange_inst.get_trade_fee("BTC/USD", TraderOrderType.BUY_MARKET,
                                                 10, 100, ExchangeConstantsMarketPropertyColumns.TAKER.value)
    _assert_fee(buy_market_fee, "BTC", 0.01, 0.001, ExchangeConstantsMarketPropertyColumns.TAKER.value)

    sell_market_fee = exchange_inst.get_trade_fee(
        "BTC/USD", TraderOrderType.SELL_MARKET, 10, 100, ExchangeConstantsMarketPropertyColumns.TAKER.value)
    _assert_fee(sell_market_fee, "USD", 1, 0.001, ExchangeConstantsMarketPropertyColumns.TAKER.value)

    buy_limit_fee = exchange_inst.get_trade_fee("BTC/USD", TraderOrderType.BUY_LIMIT,
                                                10, 100, ExchangeConstantsMarketPropertyColumns.MAKER.value)
    _assert_fee(buy_limit_fee, "BTC", 0.005, 0.0005, ExchangeConstantsMarketPropertyColumns.MAKER.value)

    sell_limit_fee = exchange_inst.get_trade_fee("BTC/USD", TraderOrderType.SELL_LIMIT,
                                                 10, 100, ExchangeConstantsMarketPropertyColumns.TAKER.value)
    _assert_fee(sell_limit_fee, "USD", 1, 0.001, ExchangeConstantsMarketPropertyColumns.TAKER.value)


# async def test_should_update_data(simulated_trader):
#     _, exchange_inst, trader_inst = simulated_trader
#
#     # first call
#     assert exchange_simulator.should_update_data(TimeFrames.ONE_HOUR, DEFAULT_BACKTESTING_SYMBOL)
#     assert exchange_simulator.should_update_data(TimeFrames.FOUR_HOURS, DEFAULT_BACKTESTING_SYMBOL)
#     assert exchange_simulator.should_update_data(TimeFrames.ONE_DAY, DEFAULT_BACKTESTING_SYMBOL)
#
#     # call get prices
#     await exchange_inst.get_symbol_prices(DEFAULT_BACKTESTING_SYMBOL, TimeFrames.ONE_HOUR)
#     await exchange_inst.get_symbol_prices(DEFAULT_BACKTESTING_SYMBOL, TimeFrames.FOUR_HOURS)
#     await exchange_inst.get_symbol_prices(DEFAULT_BACKTESTING_SYMBOL, TimeFrames.ONE_DAY)
#
#     # call with trader without order
#     assert exchange_simulator.should_update_data(TimeFrames.ONE_HOUR, DEFAULT_BACKTESTING_SYMBOL)
#     assert not exchange_simulator.should_update_data(TimeFrames.FOUR_HOURS, DEFAULT_BACKTESTING_SYMBOL)
#     assert not exchange_simulator.should_update_data(TimeFrames.ONE_DAY, DEFAULT_BACKTESTING_SYMBOL)
#     await exchange_inst.get_symbol_prices(DEFAULT_BACKTESTING_SYMBOL, TimeFrames.ONE_HOUR)
#
#
# async def test_init_candles_offset(simulated_trader):
#     _, exchange_inst, trader_inst = simulated_trader
#
#     timeframes = [TimeFrames.THIRTY_MINUTES, TimeFrames.ONE_HOUR, TimeFrames.TWO_HOURS,
#                   TimeFrames.FOUR_HOURS, TimeFrames.ONE_DAY]
#     exchange_simulator.init_candles_offset(timeframes, DEFAULT_BACKTESTING_SYMBOL)
#
#     offsets = exchange_simulator.time_frames_offset[DEFAULT_BACKTESTING_SYMBOL]
#     ohlcv = exchange_simulator.data[DEFAULT_BACKTESTING_SYMBOL][BACKTESTING_DATA_OHLCV]
#     assert ohlcv is exchange_simulator.get_ohlcv(DEFAULT_BACKTESTING_SYMBOL)
#     nb_candles = len(ohlcv[TimeFrames.THIRTY_MINUTES.value])
#     assert offsets[TimeFrames.THIRTY_MINUTES.value] == \
#            self._get_start_index_for_timeframe(nb_candles, exchange_simulator.MIN_LIMIT, 1) + 1
#     assert offsets[TimeFrames.ONE_HOUR.value] == \
#            self._get_start_index_for_timeframe(nb_candles, exchange_simulator.MIN_LIMIT, 2)
#     assert offsets[TimeFrames.TWO_HOURS.value] == \
#            self._get_start_index_for_timeframe(nb_candles, exchange_simulator.MIN_LIMIT, 4)
#     assert offsets[TimeFrames.FOUR_HOURS.value] == \
#            self._get_start_index_for_timeframe(nb_candles, exchange_simulator.MIN_LIMIT, 8)
#     assert offsets[TimeFrames.ONE_DAY.value] == 244
#
#
# async def test_select_trades(simulated_trader):
#     _, exchange_inst, trader_inst = simulated_trader
#     trades = [
#         {
#             ExchangeConstantsOrderColumns.TIMESTAMP.value: 1549413007896,
#             ExchangeConstantsOrderColumns.PRICE.value: "3415.30000"
#         },
#         {
#             ExchangeConstantsOrderColumns.TIMESTAMP.value: 1549413032879,
#             ExchangeConstantsOrderColumns.PRICE.value: "3415.30000"
#         },
#         {
#             ExchangeConstantsOrderColumns.TIMESTAMP.value: 1549413032922,
#             ExchangeConstantsOrderColumns.PRICE.value: "3415.90000"
#         }
#     ]
#     exchange_simulator.data[DEFAULT_BACKTESTING_SYMBOL][BACKTESTING_DATA_TRADES] = trades
#     assert exchange_simulator.select_trades(10, 10, DEFAULT_BACKTESTING_SYMBOL) == []
#     assert exchange_simulator.select_trades(1549413007896, -1, DEFAULT_BACKTESTING_SYMBOL) == []
#     with pytest.raises(KeyError):
#         assert exchange_simulator.select_trades(1549413007.896, 1549413032.879, "ETH/USD") == []
#     assert exchange_simulator.select_trades(exchange_simulator.get_uniform_timestamp(1549413007896),
#                                             exchange_simulator.get_uniform_timestamp(1549413032879),
#                                             DEFAULT_BACKTESTING_SYMBOL) == [
#                {
#                    ExchangeConstantsOrderColumns.TIMESTAMP.value: exchange_simulator.get_uniform_timestamp(
#                        1549413007896),
#                    ExchangeConstantsOrderColumns.PRICE.value: 3415.30000
#                },
#                {
#                    ExchangeConstantsOrderColumns.TIMESTAMP.value: exchange_simulator.get_uniform_timestamp(
#                        1549413032879),
#                    ExchangeConstantsOrderColumns.PRICE.value: 3415.30000
#                }
#            ]
#     assert exchange_simulator.select_trades(exchange_simulator.get_uniform_timestamp(1549413007896),
#                                             -1, DEFAULT_BACKTESTING_SYMBOL) == [
#                {
#                    ExchangeConstantsOrderColumns.TIMESTAMP.value: exchange_simulator.get_uniform_timestamp(
#                        1549413007896),
#                    ExchangeConstantsOrderColumns.PRICE.value: 3415.30000
#                },
#                {
#                    ExchangeConstantsOrderColumns.TIMESTAMP.value: exchange_simulator.get_uniform_timestamp(
#                        1549413032879),
#                    ExchangeConstantsOrderColumns.PRICE.value: 3415.30000
#                },
#                {
#                    ExchangeConstantsOrderColumns.TIMESTAMP.value: exchange_simulator.get_uniform_timestamp(
#                        1549413032922),
#                    ExchangeConstantsOrderColumns.PRICE.value: 3415.90000
#                }
#            ]
