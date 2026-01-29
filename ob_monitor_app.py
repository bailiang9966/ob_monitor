from flask import Flask
from flask_socketio import SocketIO
import os
from app.services import websocket_service
from app.blueprints.ob import ob_bp

# 创建Flask应用
app = Flask(__name__)

# 初始化SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_interval=25, ping_timeout=60)

# 注册蓝图
app.register_blueprint(ob_bp)



# 客户端连接事件
@socketio.event
def connect():
    print('Client connected')

# 客户端断开连接事件
@socketio.event
def disconnect():
    print('Client disconnected')

if __name__ == '__main__':
    try:
        # 启动WebSocket连接
        print("Starting WebSocket connections...")
        websocket_service.start_websockets()
        print("WebSocket connections started successfully")
        
        # 启动深度数据推送任务
        print("Starting depth data push task...")
        # 使用普通线程启动后台任务
        import threading
        import time
        def start_background_tasks():
            while True:
                try:
                    # 获取深度数据
                    btc_data = websocket_service.get_symbol_depth('BTCUSDT')
                    eth_data = websocket_service.get_symbol_depth('ETHUSDT')
                    
                    # 推送深度数据
                    socketio.emit('depth_update', {
                        'BTC': btc_data,
                        'ETH': eth_data
                    })
                    
                    # 暂时注释掉交易量提醒逻辑
                    # # 检查交易量阈值
                    # try:
                    #     # 检查BTC交易量
                    #     btc_alerts = websocket_service.check_volume_thresholds('BTCUSDT')
                    #     if btc_alerts:
                    #         for alert in btc_alerts:
                    #             socketio.emit('volume_alert', alert)
                    #     
                    #     # 检查ETH交易量
                    #     eth_alerts = websocket_service.check_volume_thresholds('ETHUSDT')
                    #     if eth_alerts:
                    #         for alert in eth_alerts:
                    #             socketio.emit('volume_alert', alert)
                    # except Exception as e:
                    #     print(f"交易量阈值检查错误: {e}")
                except Exception:
                    pass
                
                time.sleep(1)
        
        # 启动后台任务线程
        bg_thread = threading.Thread(target=start_background_tasks)
        bg_thread.daemon = True
        bg_thread.start()
        print("Depth data push task started successfully")
        
        # 启动Flask应用
        print("Starting Flask application...")
        socketio.run(app, debug=False, host='127.0.0.1', port=5000)
    except Exception as e:
        print(f"Error starting application: {e}")
        import traceback
        traceback.print_exc()