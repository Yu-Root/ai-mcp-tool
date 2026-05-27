"""SQLite数据库管理"""

import os
import json
import hashlib
import secrets
import jwt
import aiosqlite
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from pathlib import Path


class ChatDatabase:

    def __init__(self, db_path: str = "chat_history.db", secret_key: str = None):
        if not os.path.isabs(db_path):
            db_path = Path(__file__).parent / db_path
        self.db_path = str(db_path)
        self.secret_key = secret_key or secrets.token_urlsafe(32)
        print(f"📁 数据库路径: {self.db_path}")

    async def initialize(self):
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS chat_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                await db.execute("""
                    CREATE TABLE IF NOT EXISTS chat_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT DEFAULT 'default',
                        conversation_id INTEGER,
                        msid INTEGER,
                        user_input TEXT,
                        user_timestamp TIMESTAMP,
                        mcp_tools_called TEXT,
                        mcp_results TEXT,
                        ai_response TEXT,
                        ai_timestamp TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
                    )
                """)

                try:
                    await db.execute("ALTER TABLE chat_records ADD COLUMN msid INTEGER")
                except Exception:
                    pass

                await db.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        email TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        salt TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        last_login TEXT,
                        is_active BOOLEAN DEFAULT 1,
                        profile_data TEXT DEFAULT '{}'
                    )
                """)

                await db.execute("""
                    CREATE TABLE IF NOT EXISTS user_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        session_token TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        is_active BOOLEAN DEFAULT 1,
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )
                """)

                await db.execute("CREATE INDEX IF NOT EXISTS idx_chat_records_session ON chat_records(session_id)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_chat_records_msid ON chat_records(msid)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_chat_records_conversation ON chat_records(conversation_id)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_chat_records_created ON chat_records(created_at)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token ON user_sessions(session_token)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON user_sessions(user_id)")

                await db.commit()
                print("✅ 数据库表结构初始化完成")
                return True

        except Exception as e:
            print(f"❌ 数据库初始化失败: {e}")
            return False

    async def start_conversation(self, session_id: str = "default") -> int:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("INSERT OR IGNORE INTO chat_sessions (session_id) VALUES (?)", (session_id,))

                cursor = await db.execute("""
                    SELECT COALESCE(MAX(conversation_id), 0) + 1 
                    FROM chat_records WHERE session_id = ?
                """, (session_id,))
                conversation_id = (await cursor.fetchone())[0]

                await db.commit()
                return conversation_id

        except Exception as e:
            print(f"❌ 开始对话失败: {e}")
            return 1

    async def save_conversation(
        self,
        user_input: str,
        mcp_tools_called: List[Dict[str, Any]] = None,
        mcp_results: List[Dict[str, Any]] = None,
        ai_response: str = "",
        session_id: str = "default",
        conversation_id: int = None,
        msid: int = None,
    ) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                if conversation_id is None:
                    conversation_id = await self.start_conversation(session_id)

                mcp_tools_json = json.dumps(mcp_tools_called or [], ensure_ascii=False)
                mcp_results_json = json.dumps(mcp_results or [], ensure_ascii=False)

                await db.execute("""
                    INSERT INTO chat_records (
                        session_id, conversation_id, msid,
                        user_input, user_timestamp,
                        mcp_tools_called, mcp_results,
                        ai_response, ai_timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id, conversation_id, msid,
                    user_input, datetime.now().isoformat(),
                    mcp_tools_json, mcp_results_json,
                    ai_response, datetime.now().isoformat()
                ))

                await db.commit()
                print(f"💾 对话记录已保存 (session={session_id}, conversation={conversation_id})")
                return True

        except Exception as e:
            print(f"❌ 保存对话记录失败: {e}")
            return False

    async def get_threads_by_msid(self, msid: int, limit: int = 100) -> List[Dict[str, Any]]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    SELECT session_id, conversation_id,
                           MIN(created_at) AS first_time,
                           MAX(created_at) AS last_time,
                           COUNT(*) AS message_count,
                           COALESCE(
                               (SELECT user_input FROM chat_records cr2 
                                WHERE cr2.session_id = cr.session_id AND cr2.conversation_id = cr.conversation_id 
                                ORDER BY cr2.created_at ASC LIMIT 1),
                               ''
                           ) AS first_user_input
                    FROM chat_records cr
                    WHERE msid = ?
                    GROUP BY session_id, conversation_id
                    ORDER BY last_time DESC
                    LIMIT ?
                    """, (msid, limit))
                rows = await cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            print(f"❌ 获取线程列表失败: {e}")
            return []

    async def get_chat_history(
        self,
        session_id: str = "default",
        limit: int = 50,
        conversation_id: int = None
    ) -> List[Dict[str, Any]]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                if conversation_id is not None:
                    cursor = await db.execute("""
                        SELECT * FROM chat_records
                        WHERE session_id = ? AND conversation_id = ?
                        ORDER BY created_at ASC
                    """, (session_id, conversation_id))
                else:
                    cursor = await db.execute("""
                        SELECT * FROM (
                            SELECT * FROM chat_records
                            WHERE session_id = ?
                            ORDER BY created_at DESC
                            LIMIT ?
                        ) ORDER BY created_at ASC
                    """, (session_id, limit))

                rows = await cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]

                records = []
                for row in rows:
                    record = dict(zip(columns, row))
                    try:
                        record['mcp_tools_called'] = json.loads(record['mcp_tools_called'] or '[]')
                        record['mcp_results'] = json.loads(record['mcp_results'] or '[]')
                    except json.JSONDecodeError:
                        record['mcp_tools_called'] = []
                        record['mcp_results'] = []
                    records.append(record)

                if conversation_id is None:
                    records.reverse()

                return records

        except Exception as e:
            print(f"❌ 获取聊天历史失败: {e}")
            return []

    async def clear_history(self, session_id: str = "default") -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("DELETE FROM chat_records WHERE session_id = ?", (session_id,))
                await db.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
                await db.commit()
                print(f"🗑️ 已清空会话 {session_id} 的聊天历史")
                return True

        except Exception as e:
            print(f"❌ 清空聊天历史失败: {e}")
            return False

    async def delete_conversation(self, session_id: str, conversation_id: int) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "DELETE FROM chat_records WHERE session_id = ? AND conversation_id = ?",
                    (session_id, conversation_id),
                )
                await db.commit()
                return True
        except Exception as e:
            print(f"❌ 删除对话线程失败: {e}")
            return False

    async def get_stats(self) -> Dict[str, Any]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("SELECT COUNT(*) FROM chat_records")
                total_records = (await cursor.fetchone())[0]

                cursor = await db.execute("SELECT COUNT(DISTINCT session_id) FROM chat_records")
                total_sessions = (await cursor.fetchone())[0]

                cursor = await db.execute("SELECT COUNT(DISTINCT conversation_id) FROM chat_records")
                total_conversations = (await cursor.fetchone())[0]

                cursor = await db.execute("SELECT MAX(created_at) FROM chat_records")
                latest_record = (await cursor.fetchone())[0]

                return {
                    "total_records": total_records,
                    "total_sessions": total_sessions,
                    "total_conversations": total_conversations,
                    "latest_record": latest_record,
                    "database_path": self.db_path
                }

        except Exception as e:
            print(f"❌ 获取统计信息失败: {e}")
            return {}

    async def close(self):
        pass

    def _hash_password(self, password: str, salt: str = None) -> tuple[str, str]:
        if salt is None:
            salt = secrets.token_hex(16)

        password_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        ).hex()

        return password_hash, salt

    def _verify_password(self, password: str, password_hash: str, salt: str) -> bool:
        computed_hash, _ = self._hash_password(password, salt)
        return computed_hash == password_hash

    def _generate_jwt_token(self, user_id: int, username: str) -> str:
        payload = {
            'user_id': user_id,
            'username': username,
            'exp': datetime.utcnow() + timedelta(days=7),
            'iat': datetime.utcnow()
        }
        return jwt.encode(payload, self.secret_key, algorithm='HS256')

    def _verify_jwt_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=['HS256'])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    async def register_user(self, username: str, email: str, password: str) -> Dict[str, Any]:
        try:
            if not username or len(username) < 3:
                return {"success": False, "message": "用户名至少需要3个字符"}

            if not email or '@' not in email:
                return {"success": False, "message": "请输入有效的邮箱地址"}

            if not password or len(password) < 6:
                return {"success": False, "message": "密码至少需要6个字符"}

            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "SELECT id FROM users WHERE username = ? OR email = ?",
                    (username, email)
                )
                existing_user = await cursor.fetchone()

                if existing_user:
                    return {"success": False, "message": "用户名或邮箱已存在"}

                password_hash, salt = self._hash_password(password)

                cursor = await db.execute("""
                    INSERT INTO users (username, email, password_hash, salt, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (username, email, password_hash, salt, datetime.now().isoformat()))

                user_id = cursor.lastrowid
                await db.commit()

                print(f"✅ 用户注册成功: {username} (ID: {user_id})")
                return {
                    "success": True,
                    "message": "注册成功",
                    "user_id": user_id,
                    "username": username
                }

        except Exception as e:
            print(f"❌ 用户注册失败: {e}")
            return {"success": False, "message": f"注册失败: {str(e)}"}

    async def login_user(self, username: str, password: str) -> Dict[str, Any]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    SELECT id, username, email, password_hash, salt, is_active
                    FROM users WHERE username = ? OR email = ?
                """, (username, username))

                user = await cursor.fetchone()

                if not user:
                    return {"success": False, "message": "用户名或密码错误"}

                user_id, db_username, email, password_hash, salt, is_active = user

                if not is_active:
                    return {"success": False, "message": "账户已被禁用"}

                if not self._verify_password(password, password_hash, salt):
                    return {"success": False, "message": "用户名或密码错误"}

                token = self._generate_jwt_token(user_id, db_username)

                await db.execute(
                    "UPDATE users SET last_login = ? WHERE id = ?",
                    (datetime.now().isoformat(), user_id)
                )

                await db.execute("""
                    INSERT INTO user_sessions (user_id, session_token, created_at, expires_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    user_id, token,
                    datetime.now().isoformat(),
                    (datetime.now() + timedelta(days=7)).isoformat()
                ))

                await db.commit()

                print(f"✅ 用户登录成功: {db_username} (ID: {user_id})")
                return {
                    "success": True,
                    "message": "登录成功",
                    "token": token,
                    "user": {
                        "id": user_id,
                        "username": db_username,
                        "email": email
                    }
                }

        except Exception as e:
            print(f"❌ 用户登录失败: {e}")
            return {"success": False, "message": f"登录失败: {str(e)}"}

    async def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            payload = self._verify_jwt_token(token)
            if not payload:
                return None

            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    SELECT us.id, us.user_id, u.username, u.email, u.is_active
                    FROM user_sessions us
                    JOIN users u ON us.user_id = u.id
                    WHERE us.session_token = ? AND us.is_active = 1 AND us.expires_at > ?
                """, (token, datetime.now().isoformat()))

                session = await cursor.fetchone()

                if not session:
                    return None

                session_id, user_id, username, email, is_active = session

                if not is_active:
                    return None

                return {
                    "user_id": user_id,
                    "username": username,
                    "email": email,
                    "session_id": session_id
                }

        except Exception as e:
            print(f"❌ 令牌验证失败: {e}")
            return None

    async def logout_user(self, token: str) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE user_sessions SET is_active = 0 WHERE session_token = ?",
                    (token,)
                )
                await db.commit()

                print(f"✅ 用户登出成功")
                return True

        except Exception as e:
            print(f"❌ 用户登出失败: {e}")
            return False