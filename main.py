from flask import Flask
from flask_socketio import SocketIO
import os
from app.services import  websocket_service
from app.blueprints.ob import ob_bp

# 创建Flask应用
app = Flask(__name__)

# 初始化SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_interval=25, ping_timeout=60)

# 注册蓝图
app.register_blueprint(ob_bp)

# 传递 SocketIO 实例给 websocket_service
websocket_service.set_socketio_instance(socketio)

# 客户端连接事件
@socketio.event
def connect():
    print('Client connected')

# 客户端断开连接事件
@socketio.event
def disconnect():
    print('Client disconnected')

def start_websocket_services():
    """在后台线程中启动WebSocket服务"""
    try:
        # 启动WebSocket连接
        print("Starting WebSocket connections...")
        websocket_service.start_websockets()
        print("WebSocket connections started successfully")
    except Exception as e:
        print(f"Error starting WebSocket services: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    try:
        # 启动一个后台线程，在后台线程中启动WebSocket服务
        import threading
        ws_thread = threading.Thread(target=start_websocket_services)
        ws_thread.daemon = True
        ws_thread.start()
        
        # 启动Flask应用
        print("Starting Flask application...")
        socketio.run(app, debug=False, host='127.0.0.1', port=5000)
    except Exception as e:
        print(f"Error starting application: {e}")
        import traceback
        traceback.print_exc()