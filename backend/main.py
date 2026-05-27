"""FastAPI后端主文件"""

import json
import uuid
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv, find_dotenv
import uvicorn

from mcp_agent import WebMCPAgent
from database import ChatDatabase


mcp_agent = None
chat_db = None


class UserRegister(BaseModel):
    username: str
    email: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    try:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="无效的认证格式")

        token = authorization.split(" ")[1]
        user_info = await chat_db.verify_token(token)

        if not user_info:
            raise HTTPException(status_code=401, detail="无效或过期的令牌")

        return user_info
    except Exception as e:
        raise HTTPException(status_code=401, detail="认证失败")


async def get_optional_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        return None

    try:
        if not authorization.startswith("Bearer "):
            return None

        token = authorization.split(" ")[1]
        return await chat_db.verify_token(token)
    except:
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_agent, chat_db

    print("🚀 启动 MCP Web 智能助手...")

    chat_db = ChatDatabase()
    db_success = await chat_db.initialize()
    if not db_success:
        print("❌ 数据库初始化失败")
        raise Exception("数据库初始化失败")

    mcp_agent = WebMCPAgent()
    mcp_success = await mcp_agent.initialize()

    if not mcp_success:
        print("❌ MCP智能体初始化失败")
        raise Exception("MCP智能体初始化失败")

    print("✅ MCP Web 智能助手启动成功")

    yield

    if mcp_agent:
        await mcp_agent.close()
    if chat_db:
        await chat_db.close()
    print("👋 MCP Web 智能助手已关闭")


try:
    load_dotenv(find_dotenv(), override=False)
except Exception:
    pass

app = FastAPI(
    title="MCP Web智能助手",
    description="基于MCP的智能助手Web版",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectionManager:

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.connection_sessions: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        session_id = str(uuid.uuid4())
        self.active_connections.append(websocket)
        self.connection_sessions[websocket] = session_id
        print(f"📱 新连接建立，会话ID: {session_id}，当前连接数: {len(self.active_connections)}")

        await self.send_personal_message({
            "type": "session_info",
            "session_id": session_id
        }, websocket)

        return session_id

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.connection_sessions:
            session_id = self.connection_sessions[websocket]
            del self.connection_sessions[websocket]
            print(f"📱 连接断开，会话ID: {session_id}，当前连接数: {len(self.active_connections)}")
            try:
                if mcp_agent and hasattr(mcp_agent, 'session_contexts'):
                    mcp_agent.session_contexts.pop(session_id, None)
            except Exception:
                pass

    def get_session_id(self, websocket: WebSocket) -> str:
        return self.connection_sessions.get(websocket, "default")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_text(json.dumps(message, ensure_ascii=False))
        except Exception as e:
            print(f"❌ 发送消息失败: {e}")


manager = ConnectionManager()


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    session_id = await manager.connect(websocket)
    try:
        msid_param = websocket.query_params.get("msid")
        model_param = websocket.query_params.get("model")

        if not hasattr(mcp_agent, 'session_contexts'):
            mcp_agent.session_contexts = {}

        session_ctx = {}
        if msid_param:
            try:
                session_ctx["msid"] = int(msid_param)
                print(f"🔐 已为会话 {session_id} 记录 msid={session_ctx['msid']}")
            except Exception as e:
                print(f"⚠️ 解析 msid 失败: {e}")

        if model_param:
            session_ctx["model"] = str(model_param)
            print(f"🔐 已为会话 {session_id} 记录 model={model_param}")

        mcp_agent.session_contexts[session_id] = session_ctx

    except Exception as _e:
        print(f"❌ 处理 msid 参数异常: {_e}")
        if not hasattr(mcp_agent, 'session_contexts'):
            mcp_agent.session_contexts = {}
        mcp_agent.session_contexts[session_id] = {}

    try:
        while True:
            data = await websocket.receive_text()

            try:
                message = json.loads(data)

                if message.get("type") == "user_msg":
                    user_input = message.get("content", "").strip()

                    if not user_input:
                        await manager.send_personal_message({
                            "type": "error",
                            "content": "用户输入不能为空"
                        }, websocket)
                        continue

                    print(f"📨 收到用户消息: {user_input[:50]}...")

                    await manager.send_personal_message({
                        "type": "user_msg_received",
                        "content": user_input
                    }, websocket)

                    conversation_data = {
                        "user_input": user_input,
                        "mcp_tools_called": [],
                        "mcp_results": [],
                        "ai_response_parts": []
                    }

                    current_session_id = manager.get_session_id(websocket)
                    history = await chat_db.get_chat_history(session_id=current_session_id, limit=10)

                    try:
                        async for response_chunk in mcp_agent.chat_stream(user_input, history=history, session_id=current_session_id):
                            await manager.send_personal_message(response_chunk, websocket)

                            chunk_type = response_chunk.get("type")

                            if chunk_type == "tool_start":
                                tool_call = {
                                    "tool_id": response_chunk.get("tool_id"),
                                    "tool_name": response_chunk.get("tool_name"),
                                    "tool_args": response_chunk.get("tool_args"),
                                    "progress": response_chunk.get("progress")
                                }
                                conversation_data["mcp_tools_called"].append(tool_call)

                            elif chunk_type == "tool_end":
                                tool_result = {
                                    "tool_id": response_chunk.get("tool_id"),
                                    "tool_name": response_chunk.get("tool_name"),
                                    "result": response_chunk.get("result"),
                                    "success": True
                                }
                                conversation_data["mcp_results"].append(tool_result)

                            elif chunk_type == "tool_error":
                                tool_error = {
                                    "tool_id": response_chunk.get("tool_id"),
                                    "error": response_chunk.get("error"),
                                    "success": False
                                }
                                conversation_data["mcp_results"].append(tool_error)

                            elif chunk_type == "ai_response_chunk":
                                conversation_data["ai_response_parts"].append(response_chunk.get("content", ""))

                            elif chunk_type == "ai_thinking_chunk":
                                conversation_data["ai_response_parts"].append(response_chunk.get("content", ""))

                            elif chunk_type == "error":
                                print(f"❌ MCP处理错误: {response_chunk.get('content')}")
                                break

                        ai_response = "".join(conversation_data["ai_response_parts"])

                        if not ai_response and conversation_data["mcp_results"]:
                            error_results = [r for r in conversation_data["mcp_results"] if not r.get("success", True)]
                            if error_results:
                                ai_response = "处理过程中遇到错误：\n" + "\n".join([r.get("error", "未知错误") for r in error_results])

                        print(f"💾 准备保存对话记录，AI回复长度: {len(ai_response)}")

                    except Exception as e:
                        print(f"❌ MCP流式处理异常: {e}")
                        import traceback
                        traceback.print_exc()
                        ai_response = f"处理请求时出错: {str(e)}"
                        conversation_data["ai_response_parts"] = [ai_response]

                    if chat_db:
                        try:
                            msid = mcp_agent.session_contexts.get(current_session_id, {}).get("msid") if hasattr(mcp_agent, 'session_contexts') else None
                            success = await chat_db.save_conversation(
                                user_input=conversation_data["user_input"],
                                mcp_tools_called=conversation_data["mcp_tools_called"],
                                mcp_results=conversation_data["mcp_results"],
                                ai_response=ai_response,
                                session_id=current_session_id,
                                msid=msid
                            )
                            print(f"✅ 对话记录保存成功" if success else f"❌ 对话记录保存失败")
                        except Exception as e:
                            print(f"❌ 保存对话记录异常: {e}")

                elif message.get("type") == "ping":
                    await manager.send_personal_message({
                        "type": "pong",
                        "timestamp": datetime.now().isoformat()
                    }, websocket)

                else:
                    await manager.send_personal_message({
                        "type": "error",
                        "content": f"未知消息类型: {message.get('type')}"
                    }, websocket)

            except json.JSONDecodeError:
                await manager.send_personal_message({
                    "type": "error",
                    "content": "消息格式错误，请发送有效的JSON"
                }, websocket)
            except Exception as e:
                print(f"❌ WebSocket消息处理异常: {e}")
                import traceback
                traceback.print_exc()
                await manager.send_personal_message({
                    "type": "error",
                    "content": f"处理消息时出错: {str(e)}"
                }, websocket)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"❌ WebSocket错误: {e}")
        manager.disconnect(websocket)


@app.get("/")
async def root():
    return {"message": "MCP Web智能助手API", "version": "1.0.0"}


@app.get("/api/tools")
async def get_tools():
    if not mcp_agent:
        raise HTTPException(status_code=503, detail="MCP智能体未初始化")
    try:
        tools_info = mcp_agent.get_tools_info()
        return {"success": True, "data": tools_info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取工具列表失败: {str(e)}")


@app.get("/api/models")
async def get_models():
    if not mcp_agent:
        raise HTTPException(status_code=503, detail="MCP智能体未初始化")
    try:
        return {"success": True, "data": mcp_agent.get_models_info()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取模型列表失败: {str(e)}")


@app.get("/api/history")
async def get_history(limit: int = 50, session_id: str = "default", conversation_id: int = None):
    if not chat_db:
        raise HTTPException(status_code=503, detail="数据库未初始化")

    try:
        records = await chat_db.get_chat_history(session_id=session_id, limit=limit, conversation_id=conversation_id)
        stats = await chat_db.get_stats()

        return {
            "success": True,
            "data": records,
            "total": stats.get("total_records", 0),
            "returned": len(records),
            "session_id": session_id,
            "conversation_id": conversation_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取历史记录失败: {str(e)}")


@app.get("/api/threads")
async def get_threads(msid: int, limit: int = 100):
    if not chat_db:
        raise HTTPException(status_code=503, detail="数据库未初始化")
    try:
        threads = await chat_db.get_threads_by_msid(msid=msid, limit=limit)
        return {"success": True, "data": threads}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取线程列表失败: {str(e)}")


@app.delete("/api/history")
async def clear_history(session_id: str = None):
    if not chat_db:
        raise HTTPException(status_code=503, detail="数据库未初始化")

    try:
        if session_id:
            success = await chat_db.clear_history(session_id=session_id)
            message = f"会话 {session_id} 的聊天历史已清空"
        else:
            success = await chat_db.clear_history()
            message = "所有聊天历史已清空"

        if success:
            return {"success": True, "message": message}
        else:
            raise HTTPException(status_code=500, detail="清空历史记录失败")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清空历史记录失败: {str(e)}")


@app.delete("/api/threads")
async def delete_thread(session_id: str, conversation_id: int):
    if not chat_db:
        raise HTTPException(status_code=503, detail="数据库未初始化")
    try:
        ok = await chat_db.delete_conversation(session_id=session_id, conversation_id=conversation_id)
        if ok:
            return {"success": True}
        raise HTTPException(status_code=500, detail="删除对话线程失败")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除对话线程失败: {str(e)}")


@app.get("/api/status")
async def get_status():
    db_stats = {}
    if chat_db:
        try:
            db_stats = await chat_db.get_stats()
        except Exception as e:
            print(f"⚠️ 获取数据库统计失败: {e}")

    return {
        "success": True,
        "data": {
            "agent_initialized": mcp_agent is not None,
            "database_initialized": chat_db is not None,
            "tools_count": len(mcp_agent.tools) if mcp_agent else 0,
            "active_connections": len(manager.active_connections),
            "chat_records_count": db_stats.get("total_records", 0),
            "chat_sessions_count": db_stats.get("total_sessions", 0),
            "chat_conversations_count": db_stats.get("total_conversations", 0),
            "latest_record": db_stats.get("latest_record"),
            "database_path": db_stats.get("database_path"),
            "timestamp": datetime.now().isoformat()
        }
    }


@app.get("/api/database/stats")
async def get_database_stats():
    if not chat_db:
        raise HTTPException(status_code=503, detail="数据库未初始化")

    try:
        stats = await chat_db.get_stats()
        return {"success": True, "data": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据库统计失败: {str(e)}")


@app.get("/api/share/{session_id}")
async def get_shared_chat(session_id: str, limit: int = 100):
    if not chat_db:
        raise HTTPException(status_code=503, detail="数据库未初始化")

    try:
        records = await chat_db.get_chat_history(session_id=session_id, limit=limit)

        if not records:
            raise HTTPException(status_code=404, detail="未找到该会话的聊天记录")

        stats = await chat_db.get_stats()

        return {
            "success": True,
            "data": records,
            "session_id": session_id,
            "total_records": len(records),
            "shared_at": datetime.now().isoformat(),
            "readonly": True
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取分享聊天记录失败: {str(e)}")


@app.post("/api/auth/register")
async def register(user_data: UserRegister):
    try:
        result = await chat_db.register_user(
            username=user_data.username,
            email=user_data.email,
            password=user_data.password
        )
        return result
    except Exception as e:
        print(f"❌ 注册API错误: {e}")
        raise HTTPException(status_code=500, detail="注册失败")


@app.post("/api/auth/login")
async def login(user_data: UserLogin):
    try:
        result = await chat_db.login_user(
            username=user_data.username,
            password=user_data.password
        )
        return result
    except Exception as e:
        print(f"❌ 登录API错误: {e}")
        raise HTTPException(status_code=500, detail="登录失败")


@app.post("/api/auth/logout")
async def logout(current_user: dict = Depends(get_current_user), authorization: str = Header(...)):
    try:
        token = authorization.split(" ")[1]
        success = await chat_db.logout_user(token)
        if success:
            return {"success": True, "message": "登出成功"}
        else:
            raise HTTPException(status_code=500, detail="登出失败")
    except Exception as e:
        print(f"❌ 登出API错误: {e}")
        raise HTTPException(status_code=500, detail="登出失败")


@app.get("/api/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    try:
        return {
            "success": True,
            "user": {
                "id": current_user["user_id"],
                "username": current_user["username"],
                "email": current_user["email"]
            }
        }
    except Exception as e:
        print(f"❌ 获取用户信息API错误: {e}")
        raise HTTPException(status_code=500, detail="获取用户信息失败")


@app.get("/api/auth/verify")
async def verify_token(current_user: dict = Depends(get_current_user)):
    return {"success": True, "valid": True, "user_id": current_user["user_id"]}


if __name__ == "__main__":
    try:
        port = int(os.getenv("BACKEND_PORT", "8003"))
    except Exception:
        port = 8003
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    )