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
import time

from octobot_commons.config_util import has_invalid_default_config_value
from octobot_commons.constants import CONFIG_ENABLED_OPTION, CONFIG_WILDCARD, MIN_EVAL_TIME_FRAME
from octobot_commons.enums import PriceIndexes
from octobot_commons.logging.logging_util import get_logger
from octobot_commons.symbol_util import split_symbol
from octobot_commons.time_frame_manager import TimeFrameManager
from octobot_commons.timestamp_util import is_valid_timestamp

from octobot_trading.channels import BALANCE_CHANNEL, OHLCV_CHANNEL, ORDER_BOOK_CHANNEL, RECENT_TRADES_CHANNEL, \
    TICKER_CHANNEL, ORDERS_CHANNEL
from octobot_trading.channels.exchange_channel import ExchangeChannel, ExchangeChannels
from octobot_trading.constants import CONFIG_TRADER, CONFIG_CRYPTO_CURRENCIES, CONFIG_CRYPTO_PAIRS, \
    CONFIG_CRYPTO_QUOTE, CONFIG_CRYPTO_ADD, CONFIG_EXCHANGE_WEB_SOCKET, CONFIG_EXCHANGES, CONFIG_EXCHANGE_SECRET, \
    CONFIG_EXCHANGE_KEY
from octobot_trading.exchanges.backtesting.exchange_simulator import ExchangeSimulator
from octobot_trading.exchanges.data.exchange_personal_data import ExchangePersonalData
from octobot_trading.exchanges.data.exchange_symbols_data import ExchangeSymbolsData
from octobot_trading.exchanges.rest_exchange import RestExchange
from octobot_trading.exchanges.websockets.abstract_websocket import AbstractWebsocket
from octobot_trading.producers.balance_updater import BalanceUpdater
from octobot_trading.producers.ohlcv_updater import OHLCVUpdater
from octobot_trading.producers.order_book_updater import OrderBookUpdater
from octobot_trading.producers.orders_updater import OrdersUpdater
from octobot_trading.producers.recent_trade_updater import RecentTradeUpdater
from octobot_trading.producers.ticker_updater import TickerUpdater
from octobot_trading.util import is_trader_simulator_enabled
from octobot_trading.util.initializable import Initializable


class ExchangeManager(Initializable):
    WEB_SOCKET_RESET_MIN_INTERVAL = 15

    def __init__(self, config, exchange_class_string, is_simulated=False, rest_only=False, ignore_config=False):
        super().__init__()
        self.config = config
        self.exchange_class_string = exchange_class_string
        self.rest_only = rest_only
        self.ignore_config = ignore_config
        self.logger = get_logger(self.__class__.__name__)

        self.is_ready = False
        self.is_simulated = is_simulated
        self.is_trader_simulated = is_trader_simulator_enabled(self.config)

        self.trader = None
        self.exchange = None

        self.client_symbols = []
        self.client_time_frames = {}

        self.cryptocurrencies_traded_pairs = {}
        self.traded_pairs = []
        self.time_frames = []

        self.exchange_personal_data = ExchangePersonalData(self)
        self.exchange_symbols_data = ExchangeSymbolsData(self)

    async def initialize_impl(self):
        await self.create_exchanges()

    def register_trader(self, trader):
        self.trader = trader
        self.exchange_personal_data.initialize()

    def _load_constants(self):
        self._load_config_symbols_and_time_frames()
        self._set_config_time_frame()
        self._set_config_traded_pairs()

    def need_user_stream(self):
        return self.config[CONFIG_TRADER][CONFIG_ENABLED_OPTION]

    def reset_exchange_symbols_data(self):
        self.exchange_symbols_data = ExchangeSymbolsData(self)

    def reset_exchange_personal_data(self):
        self.exchange_personal_data = ExchangePersonalData(self)

    async def create_exchanges(self):
        self.exchange_type = RestExchange.create_exchange_type(self.exchange_class_string)

        if not self.is_simulated:
            # create REST based on ccxt exchange
            self.exchange = RestExchange(self.config, self.exchange_type, self)
            await self.exchange.initialize()

            self._load_constants()
            await self._create_exchange_channels()

            # create Websocket exchange if possible
            if not self.rest_only:

                # search for websocket
                if self.check_web_socket_config(self.exchange.name):
                    self.exchange_web_socket = self._search_and_create_websocket(AbstractWebsocket)

        # if simulated : create exchange simulator instance
        else:
            self.exchange = ExchangeSimulator(self.config, self.exchange_type, self)
            self._set_config_traded_pairs()

        # create exchange producers if necessaary
        await self._create_exchange_producers()
        self.is_ready = True

    async def _create_exchange_channels(self):  # TODO filter creation
        for exchange_channel_class in ExchangeChannel.__subclasses__():
            exchange_channel = exchange_channel_class(self)
            ExchangeChannels.set_chan(exchange_channel, name=exchange_channel_class.get_name())
            await exchange_channel.start()

    async def _create_exchange_producers(self):  # TODO filter creation
        await BalanceUpdater(ExchangeChannels.get_chan(BALANCE_CHANNEL, self.exchange.name)).run()
        await OHLCVUpdater(ExchangeChannels.get_chan(OHLCV_CHANNEL, self.exchange.name)).run()
        await OrderBookUpdater(ExchangeChannels.get_chan(ORDER_BOOK_CHANNEL, self.exchange.name)).run()
        await RecentTradeUpdater(ExchangeChannels.get_chan(RECENT_TRADES_CHANNEL, self.exchange.name)).run()
        await TickerUpdater(ExchangeChannels.get_chan(TICKER_CHANNEL, self.exchange.name)).run()
        await OrdersUpdater(ExchangeChannels.get_chan(ORDERS_CHANNEL, self.exchange.name)).run()

    def _search_and_create_websocket(self, websocket_class):
        for socket_manager in websocket_class.__subclasses__():
            # add websocket exchange if available
            if socket_manager.has_name(self.exchange.name):
                exchange_web_socket = socket_manager.get_websocket_client(self.config, self)

                # init websocket
                try:
                    exchange_web_socket.init_web_sockets(self.time_frames, self.traded_pairs)

                    # start the websocket
                    exchange_web_socket.start_sockets()

                    return exchange_web_socket
                except Exception as e:
                    self.logger.error(f"Fail to init websocket for {websocket_class} : {e}")
                    raise e
        return None

    def did_not_just_try_to_reset_web_socket(self):
        if self.last_web_socket_reset is None:
            return True
        else:
            return time.time() - self.last_web_socket_reset > self.WEB_SOCKET_RESET_MIN_INTERVAL

    def reset_websocket_exchange(self):
        if self.did_not_just_try_to_reset_web_socket():
            # set web socket reset time
            self.last_web_socket_reset = time.time()

            # clear databases
            # self.reset_symbols_data()
            self.reset_exchange_personal_data()

            # close and restart websockets
            if self.websocket_available():
                self.exchange_web_socket.close_and_restart_sockets()

            # databases will be filled at the next calls similarly to bot startup process

    # Exchange configuration functions
    def check_config(self, exchange_name):
        if CONFIG_EXCHANGE_KEY not in self.config[CONFIG_EXCHANGES][exchange_name] \
                or CONFIG_EXCHANGE_SECRET not in self.config[CONFIG_EXCHANGES][exchange_name]:
            return False
        else:
            return True

    def force_disable_web_socket(self, exchange_name):
        return CONFIG_EXCHANGE_WEB_SOCKET in self.config[CONFIG_EXCHANGES][exchange_name] \
               and not self.config[CONFIG_EXCHANGES][exchange_name][CONFIG_EXCHANGE_WEB_SOCKET]

    def check_web_socket_config(self, exchange_name):
        return not self.force_disable_web_socket(exchange_name)

    def enabled(self):
        # if we can get candlestick data
        if self.is_simulated or self.exchange.name in self.config[CONFIG_EXCHANGES]:
            return True
        else:
            self.logger.warning(f"Exchange {self.exchange.name} is currently disabled")
            return False

    def get_exchange_symbol_id(self, symbol, with_fixer=False):
        return self.exchange.get_market_status(symbol, with_fixer=with_fixer)["id"]

    def get_exchange_symbol(self, symbol, with_fixer=False):
        return self.exchange.get_market_status(symbol, with_fixer=with_fixer)["symbol"]

    def _load_config_symbols_and_time_frames(self):
        client = self.exchange.client
        if client:
            self.client_symbols = client.symbols
            self.client_time_frames[CONFIG_WILDCARD] = client.timeframes if hasattr(client, "timeframes") else {}
        else:
            self.logger.error("Failed to load client from REST exchange")
            self._raise_exchange_load_error()

    # SYMBOLS
    def _set_config_traded_pairs(self):
        self.cryptocurrencies_traded_pairs = {}
        for cryptocurrency in self.config[CONFIG_CRYPTO_CURRENCIES]:
            if self.config[CONFIG_CRYPTO_CURRENCIES][cryptocurrency][CONFIG_CRYPTO_PAIRS]:
                if self.config[CONFIG_CRYPTO_CURRENCIES][cryptocurrency][CONFIG_CRYPTO_PAIRS] != CONFIG_WILDCARD:
                    self.cryptocurrencies_traded_pairs[cryptocurrency] = []
                    for symbol in self.config[CONFIG_CRYPTO_CURRENCIES][cryptocurrency][CONFIG_CRYPTO_PAIRS]:
                        if self.symbol_exists(symbol):
                            self.cryptocurrencies_traded_pairs[cryptocurrency].append(symbol)
                        else:
                            self.logger.error(f"{self.exchange.name} is not supporting the "
                                              f"{symbol} trading pair.")

                else:
                    self.cryptocurrencies_traded_pairs[cryptocurrency] = self._create_wildcard_symbol_list(
                        self.config[CONFIG_CRYPTO_CURRENCIES][cryptocurrency][CONFIG_CRYPTO_QUOTE])

                    # additionnal pairs
                    if CONFIG_CRYPTO_ADD in self.config[CONFIG_CRYPTO_CURRENCIES][cryptocurrency]:
                        self.cryptocurrencies_traded_pairs[cryptocurrency] += self._add_tradable_symbols(cryptocurrency)

                # add to global traded pairs
                if not self.cryptocurrencies_traded_pairs[cryptocurrency]:
                    self.logger.error(f"{self.exchange.name} is not supporting any {cryptocurrency} trading pair "
                                      f"from current configuration.")
                self.traded_pairs += self.cryptocurrencies_traded_pairs[cryptocurrency]
            else:
                self.logger.error(f"Current configuration for {cryptocurrency} is not including any trading pair, "
                                  f"this asset can't be traded and related orders won't be loaded. "
                                  f"OctoBot requires at least one trading pair in configuration to handle an asset. "
                                  f"You can add trading pair(s) for each asset in the configuration section.")

    def get_traded_pairs(self, cryptocurrency=None):
        if cryptocurrency:
            if cryptocurrency in self.cryptocurrencies_traded_pairs:
                return self.cryptocurrencies_traded_pairs[cryptocurrency]
            else:
                return []
        return self.traded_pairs

    def symbol_exists(self, symbol):
        if self.client_symbols is None:
            self.logger.error(f"Failed to load available symbols from REST exchange, impossible to check if "
                              f"{symbol} exists on {self.exchange.name}")
            return False
        return symbol in self.client_symbols

    def _create_wildcard_symbol_list(self, cryptocurrency):
        return [s for s in (self._is_tradable_with_cryptocurrency(symbol, cryptocurrency)
                            for symbol in self.client_symbols) if s is not None]

    def _add_tradable_symbols(self, cryptocurrency):
        return [
            symbol
            for symbol in self.config[CONFIG_CRYPTO_CURRENCIES][cryptocurrency][CONFIG_CRYPTO_ADD]
            if self.symbol_exists(symbol) and symbol not in self.cryptocurrencies_traded_pairs[cryptocurrency]
        ]

    @staticmethod
    def _is_tradable_with_cryptocurrency(symbol, cryptocurrency):
        return symbol if split_symbol(symbol)[1] == cryptocurrency else None

    # TIME FRAMES
    def _set_config_time_frame(self):
        for time_frame in TimeFrameManager.get_config_time_frame(self.config):
            if self.time_frame_exists(time_frame.value):
                self.time_frames.append(time_frame)
        # add shortest timeframe for realtime evaluators
        client_shortest_time_frame = TimeFrameManager.find_min_time_frame(
            self.client_time_frames[CONFIG_WILDCARD], MIN_EVAL_TIME_FRAME)
        if client_shortest_time_frame not in self.time_frames:
            self.time_frames.append(client_shortest_time_frame)

        self.time_frames = TimeFrameManager.sort_time_frames(self.time_frames, reverse=True)

    def time_frame_exists(self, time_frame, symbol=None):
        if CONFIG_WILDCARD in self.client_time_frames or symbol is None:
            return time_frame in self.client_time_frames[CONFIG_WILDCARD]
        else:
            # should only happen in backtesting (or with an exchange with different timeframes per symbol)
            return time_frame in self.client_time_frames[symbol]

    def get_rate_limit(self):
        return self.exchange_type.rateLimit / 1000

    @staticmethod
    def need_to_uniformize_timestamp(timestamp):
        return not is_valid_timestamp(timestamp)

    def uniformize_candles_if_necessary(self, candle_or_candles):
        if candle_or_candles:
            if isinstance(candle_or_candles[0], list):
                if self.need_to_uniformize_timestamp(candle_or_candles[0][PriceIndexes.IND_PRICE_TIME.value]):
                    self._uniformize_candles_timestamps(candle_or_candles)
            else:
                if self.need_to_uniformize_timestamp(candle_or_candles[PriceIndexes.IND_PRICE_TIME.value]):
                    self._uniformize_candle_timestamps(candle_or_candles)
            return candle_or_candles

    def _uniformize_candles_timestamps(self, candles):
        for candle in candles:
            self._uniformize_candle_timestamps(candle)

    def _uniformize_candle_timestamps(self, candle):
        candle[PriceIndexes.IND_PRICE_TIME.value] = \
            self.exchange.get_uniform_timestamp(candle[PriceIndexes.IND_PRICE_TIME.value])

    # Exceptions
    def _raise_exchange_load_error(self):
        raise Exception(f"{self.exchange} - Failed to load exchange instances")

    def get_exchange_name(self):
        return self.exchange_type.__name__

    def should_decrypt_token(self, logger):
        if has_invalid_default_config_value(
                self.config[CONFIG_EXCHANGES][self.get_exchange_name()][CONFIG_EXCHANGE_KEY],
                self.config[CONFIG_EXCHANGES][self.get_exchange_name()][CONFIG_EXCHANGE_SECRET]):
            logger.warning("Exchange configuration tokens are not set yet, to use OctoBot's real trader's features, "
                           "please enter your api tokens in exchange configuration")
            return False
        return True

    @staticmethod
    def handle_token_error(error, logger):
        logger.error(f"Exchange configuration tokens are invalid : please check your configuration ! "
                     f"({error.__class__.__name__})")

    def get_symbol_data(self, symbol):
        return self.exchange_symbols_data.get_exchange_symbol_data(symbol)