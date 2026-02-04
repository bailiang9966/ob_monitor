import asyncio
import aiohttp
import json
import time
import threading
from app.config import BINANCE_WS_URL, CONFIG

class WebSocketService:
    def __init__(self):
        """
        初始化WebSocket服务
        """
        self.socketio_instance = None
        self.last_push_time = 0
        self.depth_data = {
            'BTCUSDT': {
                'spot': {'bids': [], 'asks': []},
                'futures': {'bids': [], 'asks': []}
            },
            'ETHUSDT': {
                'spot': {'bids': [], 'asks': []},
                'futures': {'bids': [], 'asks': []}
            }
        }
        self.last_price_data = {
            'BTCUSDT': {'spot': 0, 'futures': 0},
            'ETHUSDT': {'spot': 0, 'futures': 0}
        }
        self.last_pushed_data = {}
        self.processed_data_cache = {}
        self.MIN_PUSH_INTERVAL = 0.1
        self.lock = threading.Lock()
        self.ws_connections = {}
    
    def set_socketio_instance(self, sio):
        """
        设置SocketIO实例
        """
        self.socketio_instance = sio
    
    def update_order_book(self, symbol, market, data):
        """
        更新订单簿
        """
        try:
            bids = data.get('b', [])
            asks = data.get('a', [])
            if not bids and not asks:

                return
            with self.lock:
                if symbol not in self.depth_data:
                    self.depth_data[symbol] = {}
                if market not in self.depth_data[symbol]:
                    self.depth_data[symbol][market] = {
                        'bids': [],
                        'asks': []
                    }
                order_book = self.depth_data[symbol][market]
                for price_str, quantity_str in bids:
                    price = float(price_str)
                    quantity = float(quantity_str)
                    found = False
                    for i, (p, q) in enumerate(order_book['bids']):
                        if p == price:
                            if quantity > 0:
                                order_book['bids'][i] = [price, quantity]
                            else:
                                order_book['bids'].pop(i)
                            found = True
                            break
                    if not found and quantity > 0:
                        order_book['bids'].append([price, quantity])
                for price_str, quantity_str in asks:
                    price = float(price_str)
                    quantity = float(quantity_str)
                    found = False
                    for i, (p, q) in enumerate(order_book['asks']):
                        if p == price:
                            if quantity > 0:
                                order_book['asks'][i] = [price, quantity]
                            else:
                                order_book['asks'].pop(i)
                            found = True
                            break
                    if not found and quantity > 0:
                        order_book['asks'].append([price, quantity])
                order_book['bids'].sort(key=lambda x: x[0], reverse=True)
                order_book['asks'].sort(key=lambda x: x[0])
                current_price = 0
                if order_book['asks']:
                    current_price = order_book['asks'][0][0]  # 卖一价
                elif order_book['bids']:
                    current_price = order_book['bids'][0][0]  # 买一价
                if current_price > 0:
                    # 限制订单簿深度，只保存距离当前价0.5%的数据
                    self.limit_order_book_depth(order_book, current_price)
                    if symbol not in self.last_price_data:
                        self.last_price_data[symbol] = {
                            'spot': 0,
                            'futures': 0
                        }
                    self.last_price_data[symbol][market] = current_price
        except Exception:
            pass
    
    def update_last_price(self, symbol, market, data):
        """
        更新最新价格
        """
        try:
            if 'c' not in data:
                return
            price = float(data['c'])
            with self.lock:
                if symbol not in self.last_price_data:
                    self.last_price_data[symbol] = {
                        'spot': 0,
                        'futures': 0
                    }
                self.last_price_data[symbol][market] = price
        except Exception:
            pass
    
    async def process_message(self, message, symbol, market):
        """
        处理消息
        """
        try:
            data = json.loads(message)
            if 'e' in data and data['e'] == 'depthUpdate':
                # 深度更新消息，会计算并更新最新价格（卖一价或买一价）
                self.update_order_book(symbol, market, data)
            elif 'c' in data:
                # ticker消息，只作为备用价格来源
                # 不再直接更新价格，而是让深度更新消息来更新价格
                pass
            # 每100ms最多推送一次，避免过于频繁的推送
            current_time = time.time()
            if self.socketio_instance and current_time - self.last_push_time > self.MIN_PUSH_INTERVAL:
                await self.push_updated_data()
            return True
        except Exception as e:
            print(f"处理消息错误: {e}")
            return False
    
    async def push_updated_data(self):
        """
        推送更新后的数据
        """
        try:
            # 获取深度数据
            btc_data = self.get_symbol_depth('BTCUSDT')
            eth_data = self.get_symbol_depth('ETHUSDT')
            # 处理深度数据，使用缓存避免重复计算
            processed_btc = self.get_cached_processed_data('BTC', btc_data)
            processed_eth = self.get_cached_processed_data('ETH', eth_data)
            # 构建推送数据
            push_data = {
                'BTC': processed_btc,
                'ETH': processed_eth
            }
            # 直接推送数据
            self.socketio_instance.emit('depth_update', push_data)
            # 更新上次推送时间和数据
            self.update_last_pushed_data(push_data)
            self.last_push_time = time.time()
        except Exception as e:
            print(f"推送数据错误: {e}")
    
    def get_cached_processed_data(self, symbol, depth_data):
        """
        获取缓存的处理后数据
        """
        # 生成缓存键
        cache_key = f"{symbol}_{int(time.time() / 0.1)}"  # 每100ms更新一次缓存
        with self.lock:
            if cache_key in self.processed_data_cache:
                return self.processed_data_cache[cache_key]
            # 处理数据
            processed_data = self.process_symbol_depth(symbol, depth_data)
            # 更新缓存
            self.processed_data_cache[cache_key] = processed_data
            # 清理过期缓存
            self.clean_expired_cache()
            return processed_data
    
    def clean_expired_cache(self):
        """
        清理过期缓存
        """
        current_time = int(time.time() / 0.1)
        expired_keys = []
        for key in self.processed_data_cache:
            try:
                # 提取时间戳
                timestamp = int(key.split('_')[-1])
                if current_time - timestamp > 5:  # 清理5秒前的缓存
                    expired_keys.append(key)
            except:
                pass
        for key in expired_keys:
            if key in self.processed_data_cache:
                del self.processed_data_cache[key]
    
    def update_last_pushed_data(self, data):
        """
        更新上次推送的数据
        """
        self.last_pushed_data = data.copy()
    
    def limit_order_book_depth(self, order_book, current_price):
        """
        限制订单簿深度，只保存距离当前价0.5%的数据
        """
        if current_price <= 0:
            return
        
        # 计算价格范围（当前价格的±0.5%）
        price_range = current_price * 0.005
        min_price = current_price - price_range
        max_price = current_price + price_range
        
        # 筛选买单（价格 >= 最低价）
        filtered_bids = []
        for bid in order_book['bids']:
            bid_price = bid[0]
            if bid_price >= min_price:
                filtered_bids.append(bid)
            else:
                break
        
        # 筛选卖单（价格 <= 最高价）
        filtered_asks = []
        for ask in order_book['asks']:
            ask_price = ask[0]
            if ask_price <= max_price:
                filtered_asks.append(ask)
            else:
                break
        
        # 更新订单簿
        order_book['bids'] = filtered_bids
        order_book['asks'] = filtered_asks
    
    async def create_websocket_async(self, market):
        """
        创建WebSocket连接
        """
        ws_url = BINANCE_WS_URL[market]
        # 增加重连延迟，避免频繁重连
        reconnect_delay = 1
        max_reconnect_delay = 30
        
        while True:
            session = aiohttp.ClientSession()
            try:
                # 使用更合适的参数设置
                async with session.ws_connect(
                    ws_url, 
                    timeout=10,
                    autoclose=False,  # 不自动关闭连接
                    autoping=True,    # 自动发送ping消息
                    heartbeat=30,     # 每30秒发送一次ping
                    receive_timeout=45  # 45秒内没有收到消息则超时
                ) as ws:
                    print(f"{market} 市场WebSocket连接打开")
                    self.ws_connections[market] = ws
                    
                    # 订阅多个币种的深度数据和ticker数据，使用100ms间隔
                    subscribe_message = {
                        "method": "SUBSCRIBE",
                        "params": [
                            # "btcusdt@depth@100ms",
                            # "ethusdt@depth@100ms",
                            "btcusdt@depth",
                            "ethusdt@depth",
                            # "btcusdt@ticker",
                            # "ethusdt@ticker"
                        ],
                        "id": 1
                    }
                    await ws.send_json(subscribe_message)
                    
                    # 重置重连延迟
                    reconnect_delay = 1
                    
                    # 处理消息
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                                if 's' in data:
                                    symbol = data['s']
                                    await self.process_message(msg.data, symbol, market)
                            except Exception as e:
                                print(f"处理消息错误: {e}")
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            print(f"{market} 市场WebSocket连接关闭")
                            break
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            print(f"{market} 市场WebSocket错误: {ws.exception()}")
                            break
                        elif msg.type == aiohttp.WSMsgType.PING:
                            # 回复ping信息
                            await ws.pong()
                        elif msg.type == aiohttp.WSMsgType.PONG:
                            # 收到pong信息，无需处理
                            pass
            except Exception as e:
                print(f"{market} 市场WebSocket连接错误: {e}")
            finally:
                if market in self.ws_connections:
                    del self.ws_connections[market]
                await session.close()
                
                # 重连
                print(f"{market} 市场WebSocket正在重连...")
                # 使用指数退避重连策略
                await asyncio.sleep(reconnect_delay)
                # 增加重连延迟
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
    
    async def start_websockets_async(self):
        """
        启动WebSocket连接
        """
        print("开始启动异步WebSocket连接...")
        markets = ['spot', 'futures']
        tasks = []
        for market in markets:
            task = asyncio.create_task(self.create_websocket_async(market))
            tasks.append(task)
            # 添加小延迟，避免同时连接导致的消息集中到达
            await asyncio.sleep(0.1)
        await asyncio.gather(*tasks)
    
    def start_websockets_thread(self):
        """
        启动WebSocket线程
        """
        def run_async():
            asyncio.run(self.start_websockets_async())
        thread = threading.Thread(target=run_async)
        thread.daemon = True
        thread.start()
    
    def calculate_price_levels(self, bids, asks, current_price, price_step, level_count):
        """
        计算档位区间的挂单量
        """
        ask_levels = []
        for i in range(1, level_count + 1):
            level_price = current_price + (i * price_step)
            level_quantity = 0
            for ask in asks:
                price = ask[0]
                quantity = ask[1]
                if price >= level_price - price_step and price < level_price:
                    level_quantity += quantity
                elif price >= level_price:
                    break
            ask_levels.append({
                'price': level_price,
                'quantity': level_quantity
            })
        bid_levels = []
        for i in range(1, level_count + 1):
            level_price = current_price - (i * price_step)
            level_quantity = 0
            for bid in bids:
                price = bid[0]
                quantity = bid[1]
                if price <= level_price + price_step and price > level_price:
                    level_quantity += quantity
                elif price <= level_price:
                    break
            bid_levels.append({
                'price': level_price,
                'quantity': level_quantity
            })
        bid_levels.sort(key=lambda x: x['price'], reverse=True)
        return {'ask_levels': ask_levels, 'bid_levels': bid_levels}
    
    def process_symbol_depth(self, symbol, depth_data):
        """
        处理单个交易对的深度数据
        """
        result = {}
        for market, market_data in depth_data.items():
            bids = market_data.get('bids', [])
            asks = market_data.get('asks', [])
            current_price = market_data.get('last_price', 0)
            if not bids or not asks or current_price == 0:
                result[market] = {
                    'last_price': current_price,
                    'levels': {}
                }
                continue
            levels = {}
            symbol_config = CONFIG.get(symbol + 'USDT', {})
            market_config = symbol_config.get(market, {})
            steps = list(market_config.keys()) if market_config else []
            # 使用配置中的步长档位
            for step in steps:
                levels[step] = self.calculate_price_levels(bids, asks, current_price, step, 2)
            result[market] = {
                'last_price': current_price,
                'levels': levels
            }
        return result
    

    
    def start_websockets(self):
        """
        启动所有WebSocket连接
        """
        print("开始启动WebSocket连接...")
        self.start_websockets_thread()
        print("WebSocket连接启动完成")
    
    def get_depth_data(self):
        """
        获取深度数据
        """
        with self.lock:
            return self.depth_data.copy()
    
    def calculate_volume_in_range(self, orders, price_range, is_ask):
        """
        计算指定价格区间内的交易量
        """
        volume = 0
        min_price, max_price = price_range
        for order in orders:
            price, quantity = order
            if is_ask:
                if price >= min_price and price <= max_price:
                    volume += quantity
                elif price > max_price:
                    break
            else:
                if price >= min_price and price <= max_price:
                    volume += quantity
                elif price < min_price:
                    break
        return volume
    
    def get_symbol_depth(self, symbol):
        """
        获取指定交易对的深度数据和最新价格
        """
        result = {}
        try:
            with self.lock:
                if symbol in self.depth_data:
                    result = {}
                    for market, market_data in self.depth_data[symbol].items():
                        bids = market_data['bids'][:]
                        asks = market_data['asks'][:]
                        result[market] = {
                            'bids': bids,
                            'asks': asks
                        }
                    if symbol in self.last_price_data:
                        for market in result:
                            if market in self.last_price_data[symbol]:
                                result[market]['last_price'] = self.last_price_data[symbol][market]
                    for market in result:
                        if result[market].get('last_price', 0) == 0:
                            if result[market]['asks']:
                                result[market]['last_price'] = result[market]['asks'][0][0]
                            elif result[market]['bids']:
                                result[market]['last_price'] = result[market]['bids'][0][0]
                            else:
                                result[market]['last_price'] = 0
        except Exception:
            pass
        return result

# 创建WebSocket服务实例
websocket_service = WebSocketService()

# 导出方法
def set_socketio_instance(sio):
    websocket_service.set_socketio_instance(sio)

def start_websockets():
    websocket_service.start_websockets()

def get_depth_data():
    return websocket_service.get_depth_data()

def get_symbol_depth(symbol):
    return websocket_service.get_symbol_depth(symbol)
