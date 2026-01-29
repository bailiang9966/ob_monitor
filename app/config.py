CONFIG = {
    'BTCUSDT': {
        'futures': {10:150,20: 300, 50: 500},
        'spot': {10:15,20: 35, 50: 80}
    },
    'ETHUSDT': {
        'futures': {1: 5000, 5: 20000, 10: 50000},
        'spot': {1: 800, 5: 2000, 10: 5000}
    }
}

# 币安WebSocket URL
BINANCE_WS_URL = {
    'spot': 'wss://stream.binance.com:9443/ws',
    'futures': 'wss://fstream.binance.com/ws'
}