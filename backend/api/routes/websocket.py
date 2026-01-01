from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Set
import logging
import json

logger = logging.getLogger(__name__)

router = APIRouter()

# 存储活跃的WebSocket连接
active_connections: Dict[str, Set[WebSocket]] = {}


class ConnectionManager:
    """WebSocket连接管理器"""

    @staticmethod
    async def connect(websocket: WebSocket, analysis_id: str):
        """建立连接"""
        await websocket.accept()
        if analysis_id not in active_connections:
            active_connections[analysis_id] = set()
        active_connections[analysis_id].add(websocket)
        logger.info(f"WebSocket connected: {analysis_id}")

    @staticmethod
    async def disconnect(websocket: WebSocket, analysis_id: str):
        """断开连接"""
        if analysis_id in active_connections:
            active_connections[analysis_id].discard(websocket)
            if not active_connections[analysis_id]:
                del active_connections[analysis_id]
        logger.info(f"WebSocket disconnected: {analysis_id}")

    @staticmethod
    async def broadcast(analysis_id: str, message: Dict):
        """广播消息给特定分析任务的所有连接"""
        if analysis_id not in active_connections:
            return

        dead_connections = set()
        for connection in active_connections[analysis_id]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send message: {e}")
                dead_connections.add(connection)

        # 清理死连接
        for conn in dead_connections:
            active_connections[analysis_id].discard(conn)


@router.websocket("/ws/analysis/{analysis_id}")
async def websocket_endpoint(websocket: WebSocket, analysis_id: str):
    """WebSocket端点"""
    await ConnectionManager.connect(websocket, analysis_id)

    try:
        while True:
            # 保持连接活跃（客户端可以发送心跳）
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await ConnectionManager.disconnect(websocket, analysis_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await ConnectionManager.disconnect(websocket, analysis_id)


async def send_progress_update(
    analysis_id: str, stage: str, progress: int, message: str = ""
):
    """发送进度更新（在分析流程中调用）"""
    await ConnectionManager.broadcast(
        analysis_id,
        {
            "type": "progress",
            "stage": stage,
            "progress": progress,
            "message": message,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )
