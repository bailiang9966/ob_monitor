import websocket
import json
import threading
import time
from app.config import BINANCE_WS_URL, CONFIG

# 订单簿配置
PRICE_RANGE_MULTIPLIER = 1.5  # 价格范围乘数
FALLBACK_MAX_DEPTH = 200  # 无法获取价格时的备用深度限制

# 存储深度数据
depth_data = {
    'BTCUSDT': {
        'spot': {'bids': [], 'asks': []},
        'futures': {'bids': [], 'asks': []}
    },
    'ETHUSDT': {
        'spot': {'bids': [], 'asks': []},
        'futures': {'bids': [], 'asks': []}
    }
}

# 存储最新价格数据
last_price_data = {
    'BTCUSDT': {
        'spot': 0,
        'futures': 0
    },
    'ETHUSDT': {
        'spot': 0,
        'futures': 0
    }
}

# 线程锁
lock = threading.Lock()

# 初始化订单簿
def init_order_book(symbol, market):
    with lock:
        if symbol not in depth_data:
            depth_data[symbol] = {}
        if market not in depth_data[symbol]:
            depth_data[symbol][market] = {
                'bids': [],  # 买单，价格从高到低
                'asks': []  # 卖单，价格从低到高
            }

# 获取币种的最大价格范围
def get_max_price_range(symbol):
    """
    根据配置文件中的最大档位计算价格范围
    返回: 最大价格范围（正数）
    """
    max_range = 0
    
    if symbol in CONFIG:
        symbol_config = CONFIG[symbol]
        for market_config in symbol_config.values():
            # 找到最大的档位值
            if market_config:
                max_step = max(market_config.keys())
                if max_step > max_range:
                    max_range = max_step
    
    # 应用价格范围乘数
    return max_range * PRICE_RANGE_MULTIPLIER

# 限制订单簿深度（基于价格范围）
def limit_order_book_depth(order_book, symbol, current_price):
    """
    限制订单簿深度，确保覆盖足够的价格范围
    基于配置中的最大档位计算价格范围
    """
    # 保存原始订单数量
    original_bids_count = len(order_book['bids'])
    original_asks_count = len(order_book['asks'])
    
    # 如果没有订单，直接返回
    if original_bids_count == 0 and original_asks_count == 0:
        return
    
    if current_price <= 0:
        # 如果没有当前价格，使用备用深度限制
        if len(order_book['bids']) > FALLBACK_MAX_DEPTH:
            order_book['bids'] = order_book['bids'][:FALLBACK_MAX_DEPTH]
        if len(order_book['asks']) > FALLBACK_MAX_DEPTH:
            order_book['asks'] = order_book['asks'][:FALLBACK_MAX_DEPTH]
        return
    
    # 计算价格范围
    max_price_range = get_max_price_range(symbol)
    if max_price_range <= 0:
        # 如果无法计算价格范围，使用备用深度限制
        if len(order_book['bids']) > FALLBACK_MAX_DEPTH:
            order_book['bids'] = order_book['bids'][:FALLBACK_MAX_DEPTH]
        if len(order_book['asks']) > FALLBACK_MAX_DEPTH:
            order_book['asks'] = order_book['asks'][:FALLBACK_MAX_DEPTH]
        return
    
    # 计算价格上下限
    min_price = current_price - max_price_range
    max_price = current_price + max_price_range
    
    # 筛选买单（价格 >= 最低价）
    filtered_bids = []
    for bid in order_book['bids']:
        bid_price = bid[0]
        if bid_price >= min_price:
            filtered_bids.append(bid)
        else:
            # 买单按价格从高到低排序，低于最低价的可以停止遍历
            break
    
    # 筛选卖单（价格 <= 最高价）
    filtered_asks = []
    for ask in order_book['asks']:
        ask_price = ask[0]
        if ask_price <= max_price:
            filtered_asks.append(ask)
        else:
            # 卖单按价格从低到高排序，高于最高价的可以停止遍历
            break
    
    # 确保不会将订单簿设置为空列表，除非确实没有订单
    if filtered_bids:
        order_book['bids'] = filtered_bids
    elif original_bids_count > 0:
        # 如果筛选后没有买单，但原始订单簿有买单，保留所有买单
        pass
    
    if filtered_asks:
        order_book['asks'] = filtered_asks
    elif original_asks_count > 0:
        # 如果筛选后没有卖单，但原始订单簿有卖单，保留所有卖单
        pass
    
    # 确保至少保留一些订单，即使价格范围外
    if len(order_book['bids']) > 50:
        order_book['bids'] = order_book['bids'][:50]
    if len(order_book['asks']) > 50:
        order_book['asks'] = order_book['asks'][:50]

# 更新订单簿
def update_order_book(symbol, market, data):
    try:
        # 快速检查是否需要更新
        bids = data.get('b', [])
        asks = data.get('a', [])
        if not bids and not asks:
            return
        
        # 使用锁保护共享数据
        with lock:
            # 初始化订单簿
            if symbol not in depth_data:
                depth_data[symbol] = {}
            if market not in depth_data[symbol]:
                depth_data[symbol][market] = {
                    'bids': [],
                    'asks': []
                }
            order_book = depth_data[symbol][market]
            
            # 处理买单
            for price_str, quantity_str in bids:
                price = float(price_str)
                quantity = float(quantity_str)
                # 查找现有订单
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
            
            # 处理卖单
            for price_str, quantity_str in asks:
                price = float(price_str)
                quantity = float(quantity_str)
                # 查找现有订单
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
            
            # 排序
            order_book['bids'].sort(key=lambda x: x[0], reverse=True)
            order_book['asks'].sort(key=lambda x: x[0])
        

    except Exception:
        pass

# 更新最新价格
def update_last_price(symbol, market, data):
    try:
        if 'c' not in data:
            return
        
        price = float(data['c'])
        
        # 使用锁保护共享数据
        with lock:
            if symbol not in last_price_data:
                last_price_data[symbol] = {
                    'spot': 0,
                    'futures': 0
                }
            last_price_data[symbol][market] = price
        

    except Exception:
        pass

# WebSocket回调函数
def on_message(ws, message, symbol, market):
    try:
        data = json.loads(message)
        if 'e' in data and data['e'] == 'depthUpdate':
            # 更新订单簿
            update_order_book(symbol, market, data)
        elif 'c' in data:
            # 更新最新价格（只要有最新价格字段就更新）
            update_last_price(symbol, market, data)
    except Exception as e:
        pass

# 创建WebSocket连接（每个市场一个连接，订阅多个币种）
def create_websocket(market, reconnect_attempts=0):
    def on_message_wrapper(ws, message):
        # 解析消息，根据深度更新消息中的s字段确定交易对
        try:
            data = json.loads(message)
            # 处理订阅确认消息
            if 'result' in data:
                return
            # 处理深度更新消息和ticker消息
            if 's' in data:
                symbol = data['s']
                on_message(ws, message, symbol, market)
        except Exception as e:
            print(f"WebSocket消息处理错误 ({market}): {e}")
    
    def on_error(ws, error):
        print(f"WebSocket错误 ({market}): {error}")
    
    def on_close(ws, close_status_code, close_msg):
        # 指数退避重连
        max_reconnect_delay = 60
        reconnect_delay = min(max_reconnect_delay, 2 ** reconnect_attempts)
        print(f"WebSocket连接关闭 ({market})，{reconnect_delay}秒后重连...")
        time.sleep(reconnect_delay)
        create_websocket(market, reconnect_attempts + 1)
    
    def on_open(ws):
        # 重置重连尝试次数
        print(f"WebSocket连接已打开 ({market})")
        # 订阅多个币种的深度数据和ticker数据
        subscribe_message = {
            "method": "SUBSCRIBE",
            "params": [
                "btcusdt@depth@100ms",
                "ethusdt@depth@100ms",
                "btcusdt@ticker",
                "ethusdt@ticker"
            ],
            "id": 1
        }
        ws.send(json.dumps(subscribe_message))
    
    ws_url = BINANCE_WS_URL[market]
    ws = websocket.WebSocketApp(ws_url, 
                                on_open=on_open,
                                on_message=on_message_wrapper,
                                on_error=on_error,
                                on_close=on_close)
    
    # 启动WebSocket线程
    thread = threading.Thread(target=ws.run_forever)
    thread.daemon = True
    thread.start()
    
    return ws

# 启动所有WebSocket连接
def start_websockets():
    markets = ['spot', 'futures']
    
    for market in markets:
        create_websocket(market)
        time.sleep(0.1)

# 获取深度数据
def get_depth_data():
    with lock:
        return depth_data.copy()

# 计算指定价格区间内的交易量
def calculate_volume_in_range(orders, price_range, is_ask):
    """
    计算指定价格区间内的交易量
    orders: 订单列表（买单或卖单）
    price_range: 价格区间 (min_price, max_price)
    is_ask: 是否为卖单
    """
    volume = 0
    min_price, max_price = price_range
    
    for order in orders:
        price, quantity = order
        if is_ask:
            # 卖单，价格从低到高排序，检查是否在区间内
            if price >= min_price and price <= max_price:
                volume += quantity
            elif price > max_price:
                # 卖单已按价格从低到高排序，超出最大值后可停止遍历
                break
        else:
            # 买单，价格从高到低排序，检查是否在区间内
            if price >= min_price and price <= max_price:
                volume += quantity
            elif price < min_price:
                # 买单已按价格从高到低排序，低于最小值后可停止遍历
                break
    
    return volume

# 检查交易量是否超过阈值
def check_volume_thresholds(symbol):
    """
    检查交易量是否超过阈值
    返回提醒消息列表
    """
    alerts = []
    
    # 获取深度数据和最新价格
    data = get_symbol_depth(symbol)
    
    # 检查配置是否存在
    if symbol not in CONFIG:
        return alerts
    
    config = CONFIG[symbol]
    
    # 遍历市场
    for market, market_config in config.items():
        if market not in data:
            continue
        
        market_data = data[market]
        last_price = market_data.get('last_price', 0)
        
        if last_price == 0:
            continue
        
        # 遍历档位配置
        for price_step, threshold in market_config.items():
            # 计算卖单区间（上方最近的价格区间）
            ask_min_price = last_price
            ask_max_price = last_price + price_step
            ask_volume = calculate_volume_in_range(market_data.get('asks', []), (ask_min_price, ask_max_price), True)
            
            # 检查卖单交易量
            if ask_volume > threshold:
                alerts.append({
                    'symbol': symbol,
                    'market': market,
                    'type': 'ask',
                    'price_range': f"{ask_min_price:.2f}-{ask_max_price:.2f}",
                    'volume': ask_volume,
                    'threshold': threshold,
                    'message': f"{symbol} {market} 卖单在区间 {ask_min_price:.2f}-{ask_max_price:.2f} 内交易量 {ask_volume:.2f} 超过阈值 {threshold}"
                })
            
            # 计算买单区间（下方最近的价格区间）
            bid_min_price = last_price - price_step
            bid_max_price = last_price
            bid_volume = calculate_volume_in_range(market_data.get('bids', []), (bid_min_price, bid_max_price), False)
            
            # 检查买单交易量
            if bid_volume > threshold:
                alerts.append({
                    'symbol': symbol,
                    'market': market,
                    'type': 'bid',
                    'price_range': f"{bid_min_price:.2f}-{bid_max_price:.2f}",
                    'volume': bid_volume,
                    'threshold': threshold,
                    'message': f"{symbol} {market} 买单在区间 {bid_min_price:.2f}-{bid_max_price:.2f} 内交易量 {bid_volume:.2f} 超过阈值 {threshold}"
                })
    
    return alerts

# 获取指定交易对的深度数据和最新价格
def get_symbol_depth(symbol):
    result = {}
    try:
        # 使用锁保护共享数据
        with lock:
            if symbol in depth_data:
                # 快速创建结果
                result = {}
                for market, market_data in depth_data[symbol].items():
                    # 只拷贝必要的数据
                    bids = market_data['bids'][:]  # 浅拷贝
                    asks = market_data['asks'][:]  # 浅拷贝
                    result[market] = {
                    'bids': bids,
                    'asks': asks
                }
                
                # 添加价格数据
                if symbol in last_price_data:
                    for market in result:
                        if market in last_price_data[symbol]:
                            result[market]['last_price'] = last_price_data[symbol][market]
                
                # 处理价格为0的情况
                for market in result:
                    if result[market].get('last_price', 0) == 0:
                        # 尝试从深度数据获取价格
                        if result[market]['asks']:
                            result[market]['last_price'] = result[market]['asks'][0][0]
                        elif result[market]['bids']:
                            result[market]['last_price'] = result[market]['bids'][0][0]
                        else:
                            result[market]['last_price'] = 0
    except Exception:
        pass
    
    return result
