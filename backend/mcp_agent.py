"""MCP智能体封装 - 为Web后端使用"""

import os
import json
import asyncio
import re
from typing import Dict, List, Any, AsyncGenerator, Optional
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv, find_dotenv
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient


class MCPConfig:
    """MCP配置管理"""

    def __init__(self, config_file: str = "mcp.json"):
        self.config_file = config_file
        self.default_config = {}

    def load_config(self) -> Dict[str, Any]:
        if Path(self.config_file).exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ 配置文件加载失败，使用默认配置: {e}")

        self.save_config(self.default_config)
        return self.default_config

    def save_config(self, config: Dict[str, Any]):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ 配置文件保存失败: {e}")


class WebMCPAgent:
    """Web版MCP智能体 - 支持流式推送"""

    def __init__(self):
        config_path = Path(__file__).parent / "mcp.json"
        self.config = MCPConfig(str(config_path))
        self.llm = None
        self.llm_tools = None
        self.llm_nontool = None
        self.mcp_client = None
        self.tools = []
        self.tools_by_server = {}
        self.server_configs = {}
        self._used_tool_names = set()

        try:
            load_dotenv(find_dotenv(), override=True)
        except Exception:
            pass

        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.base_url = os.getenv("OPENAI_BASE_URL", "").strip()
        self.model_name = os.getenv("OPENAI_MODEL", os.getenv("OPENAI_MODEL_NAME", "deepseek-chat")).strip()

        self.llm_profiles = self._load_llm_profiles_from_env()
        self.default_profile_id = os.getenv("LLM_DEFAULT", "default").strip() or "default"
        if self.default_profile_id not in self.llm_profiles:
            self.default_profile_id = "default"
        self._llm_cache: Dict[str, Dict[str, Any]] = {}

        try:
            self.temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
        except Exception:
            self.temperature = 0.2
        try:
            self.timeout = int(os.getenv("OPENAI_TIMEOUT", "60"))
        except Exception:
            self.timeout = 60

        if self.api_key and not os.getenv("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = self.api_key
        if self.base_url and not os.getenv("OPENAI_BASE_URL"):
            os.environ["OPENAI_BASE_URL"] = self.base_url

        self.session_contexts: Dict[str, Dict[str, Any]] = {}

    def _load_llm_profiles_from_env(self) -> Dict[str, Dict[str, Any]]:
        profiles: Dict[str, Dict[str, Any]] = {}

        profiles["default"] = {
            "id": "default",
            "label": os.getenv("LLM_DEFAULT_LABEL", "Default"),
            "api_key": os.getenv("OPENAI_API_KEY", "").strip(),
            "base_url": os.getenv("OPENAI_BASE_URL", "").strip(),
            "model": os.getenv("OPENAI_MODEL", os.getenv("OPENAI_MODEL_NAME", "deepseek-chat")).strip(),
            "temperature": float(os.getenv("OPENAI_TEMPERATURE", "0.2")),
            "timeout": int(os.getenv("OPENAI_TIMEOUT", "60")),
        }

        ids_raw = os.getenv("LLM_PROFILES", "").strip()
        if ids_raw:
            for pid in [x.strip() for x in ids_raw.split(",") if x.strip()]:
                api_key = os.getenv(f"LLM_{pid.upper()}_API_KEY", "").strip()
                model_name = os.getenv(f"LLM_{pid.upper()}_MODEL", "").strip()
                if not api_key or not model_name:
                    continue
                base_url = os.getenv(f"LLM_{pid.upper()}_BASE_URL", "").strip()
                label = os.getenv(f"LLM_{pid.upper()}_LABEL", pid)
                try:
                    temperature = float(os.getenv(f"LLM_{pid.upper()}_TEMPERATURE", os.getenv("OPENAI_TEMPERATURE", "0.2")))
                except Exception:
                    temperature = 0.2
                try:
                    timeout = int(os.getenv(f"LLM_{pid.upper()}_TIMEOUT", os.getenv("OPENAI_TIMEOUT", "60")))
                except Exception:
                    timeout = 60
                profiles[pid] = {
                    "id": pid,
                    "label": label,
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": model_name,
                    "temperature": temperature,
                    "timeout": timeout,
                }

        return profiles

    def get_models_info(self) -> Dict[str, Any]:
        profiles = self.llm_profiles or {}
        ids = list(profiles.keys())
        non_default_ids = [pid for pid in ids if pid != "default"]

        if self.default_profile_id and self.default_profile_id != "default" and self.default_profile_id in profiles:
            effective_default = self.default_profile_id
        elif non_default_ids:
            effective_default = non_default_ids[0]
        else:
            effective_default = "default"

        show_ids = non_default_ids if non_default_ids else (["default"] if "default" in profiles else [])

        seen_signatures = set()
        models = []
        for pid in show_ids:
            cfg = profiles.get(pid, {})
            signature = (cfg.get("base_url", "").strip(), cfg.get("model", "").strip())
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            models.append({
                "id": pid,
                "label": cfg.get("label", pid),
                "model": cfg.get("model", ""),
                "is_default": pid == effective_default,
            })

        return {"models": models, "default": effective_default}

    def _get_or_create_llm_instances(self, profile_id: str) -> Dict[str, Any]:
        pid = profile_id or self.default_profile_id
        if pid not in self.llm_profiles:
            pid = self.default_profile_id

        if pid in self._llm_cache:
            return self._llm_cache[pid]

        cfg = self.llm_profiles[pid]

        prev_key = os.getenv("OPENAI_API_KEY")
        prev_base = os.getenv("OPENAI_BASE_URL")
        try:
            if cfg.get("api_key"):
                os.environ["OPENAI_API_KEY"] = cfg["api_key"]
            if cfg.get("base_url"):
                os.environ["OPENAI_BASE_URL"] = cfg["base_url"]

            base_llm = ChatOpenAI(
                model=cfg.get("model", self.model_name),
                temperature=cfg.get("temperature", self.temperature),
                timeout=cfg.get("timeout", self.timeout),
                max_retries=3,
            )
            llm_nontool = ChatOpenAI(
                model=cfg.get("model", self.model_name),
                temperature=cfg.get("temperature", self.temperature),
                timeout=cfg.get("timeout", self.timeout),
                max_retries=3,
            )
            llm_tools = base_llm.bind_tools(self.tools)
        finally:
            if prev_key is not None:
                os.environ["OPENAI_API_KEY"] = prev_key
            if prev_base is not None:
                os.environ["OPENAI_BASE_URL"] = prev_base

        bundle = {"llm": base_llm, "llm_nontool": llm_nontool, "llm_tools": llm_tools}
        self._llm_cache[pid] = bundle
        return bundle

    async def initialize(self):
        try:
            startup_cfg = None
            if self.default_profile_id in self.llm_profiles:
                cfg = self.llm_profiles[self.default_profile_id]
                if cfg.get("api_key") and cfg.get("model"):
                    startup_cfg = cfg

            if startup_cfg is None:
                for _pid, cfg in self.llm_profiles.items():
                    if _pid == "default":
                        continue
                    if cfg.get("api_key") and cfg.get("model"):
                        startup_cfg = cfg
                        break

            if startup_cfg is None and os.getenv("OPENAI_API_KEY"):
                startup_cfg = {
                    "api_key": os.getenv("OPENAI_API_KEY").strip(),
                    "base_url": os.getenv("OPENAI_BASE_URL", "").strip(),
                    "model": self.model_name,
                    "temperature": self.temperature,
                    "timeout": self.timeout,
                }

            if startup_cfg is None:
                raise RuntimeError("缺少可用的模型档位或 OPENAI_API_KEY")

            if startup_cfg.get("api_key"):
                os.environ["OPENAI_API_KEY"] = startup_cfg["api_key"]
            if startup_cfg.get("base_url"):
                os.environ["OPENAI_BASE_URL"] = startup_cfg["base_url"]

            base_llm = ChatOpenAI(
                model=startup_cfg.get("model", self.model_name),
                temperature=startup_cfg.get("temperature", self.temperature),
                timeout=startup_cfg.get("timeout", self.timeout),
                max_retries=3,
            )
            self.llm = base_llm
            self.llm_nontool = ChatOpenAI(
                model=startup_cfg.get("model", self.model_name),
                temperature=startup_cfg.get("temperature", self.temperature),
                timeout=startup_cfg.get("timeout", self.timeout),
                max_retries=3,
            )

            mcp_config = self.config.load_config()
            self.server_configs = mcp_config.get("servers", {})

            if not self.server_configs:
                print("⚠️ 没有配置外部MCP服务器")

            print("🔗 正在连接MCP服务器...")

            import aiohttp
            for server_name, server_config in self.server_configs.items():
                url = server_config.get('url')
                if not url:
                    print(f"⚠️ 服务器 {server_name} 缺少 url 配置，跳过连接测试")
                    continue
                try:
                    print(f"🧪 测试连接到 {server_name}: {url}")
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                            print(f"✅ {server_name} 连接测试成功 (状态: {response.status})")
                except Exception as test_e:
                    print(f"⚠️ {server_name} 连接测试失败: {test_e}")

            import httpx

            def http_client_factory(headers=None, timeout=None, auth=None):
                return httpx.AsyncClient(
                    http2=False,
                    headers=headers,
                    timeout=timeout,
                    auth=auth
                )

            for server_name in self.server_configs:
                server_cfg = dict(self.server_configs[server_name])
                server_cfg['httpx_client_factory'] = http_client_factory
                self.server_configs[server_name] = server_cfg

            self.mcp_client = MultiServerMCPClient(self.server_configs)

            print("🔧 正在逐个获取服务器工具...")
            for server_name in self.server_configs.keys():
                try:
                    print(f"─── 正在从服务器 '{server_name}' 获取工具 ───")
                    server_tools = await self.mcp_client.get_tools(server_name=server_name)
                    sanitized_tools = []
                    for tool in server_tools:
                        try:
                            original_name = getattr(tool, 'name', '') or ''
                            sanitized = self._sanitize_and_uniq_tool_name(original_name)
                            if sanitized != original_name:
                                print(f"🧹 规范化工具名: '{original_name}' -> '{sanitized}'")
                                try:
                                    tool.name = sanitized
                                except Exception:
                                    pass
                            sanitized_tools.append(tool)
                        except Exception as _e:
                            print(f"⚠️ 工具名规范化失败，跳过: {getattr(tool,'name','<unknown>')} - {_e}")
                            sanitized_tools.append(tool)
                    self.tools.extend(sanitized_tools)
                    self.tools_by_server[server_name] = sanitized_tools
                    print(f"✅ 从 {server_name} 获取到 {len(server_tools)} 个工具")
                except Exception as e:
                    print(f"❌ 从服务器 '{server_name}' 获取工具失败: {e}")
                    self.tools_by_server[server_name] = []

            print(f"🔍 配置的服务器: {list(self.server_configs.keys())}")
            print(f"🔍 实际获取到的工具数量: {len(self.tools)}")
            print(f"✅ 成功连接，获取到 {len(self.tools)} 个工具")
            print(f"📊 服务器分组情况: {dict((name, len(tools)) for name, tools in self.tools_by_server.items())}")

            self.llm_tools = base_llm.bind_tools(self.tools)

            print("🤖 Web MCP智能助手已启动！")
            return True

        except Exception as e:
            import traceback
            print(f"❌ 初始化失败: {e}")
            traceback.print_exc()

            if hasattr(self, 'mcp_client') and self.mcp_client:
                try:
                    await self.mcp_client.close()
                except:
                    pass
            return False

    def _get_tools_system_prompt(self) -> str:
        now = datetime.now()
        current_date = now.strftime("%Y年%m月%d日")
        current_weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
        return (
            f"今天是 {current_date}（{current_weekday}）。你是一个有用、无害、诚实的AI助手。\n"
            "- 你可以使用可用的工具来帮助用户解决问题。\n"
            "- 当用户的问题需要获取实时信息、执行特定操作或使用外部服务时，请使用合适的工具。\n"
            "- 对于一般性问题、知识性问题或不需要工具的问题，请直接回答。\n"
            "- 如果决定使用工具，请只输出 tool_calls，不要同时输出自然语言回答。\n"
            "- 如果决定不使用工具，请提供有帮助的中文回答。\n"
            f"今天是 {current_date}（{current_weekday}）。你是一个工具调度器。\n"
            "- 默认不调用工具。只有在确实需要使用工具获取信息时才调用。\n"
            "- 优先直接回答：对纯推理/常识/总结类请求不要调用工具。\n"
            "- 不要无节制的调用工具，除非用户明确要求。\n"
            "- 根据可用工具选择合适的工具来完成任务。\n"
            "- 不要为'尝试/验证'而随意调用工具；若信息不足，返回不调用工具。\n"
            "- 仅在确有必要时，通过 tool_calls 给出函数名与'合法 JSON'参数；不要输出其他内容。\n"
        )

    def _sanitize_and_uniq_tool_name(self, name: str) -> str:
        if not isinstance(name, str):
            name = str(name or "")
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        if not sanitized:
            sanitized = "tool"
        base = sanitized
        index = 1
        while sanitized in self._used_tool_names:
            index += 1
            sanitized = f"{base}_{index}"
        self._used_tool_names.add(sanitized)
        return sanitized

    async def chat_stream(self, user_input: str, history: List[Dict[str, Any]] = None, session_id: Optional[str] = None) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            print(f"🤖 开始处理用户输入: {user_input[:50]}...")
            yield {"type": "status", "content": "开始生成..."}

            profile_id = None
            try:
                if session_id and self.session_contexts.get(session_id):
                    profile_id = self.session_contexts[session_id].get("model") or self.session_contexts[session_id].get("llm_profile")
            except Exception:
                profile_id = None

            llm_bundle = self._get_or_create_llm_instances(profile_id)
            current_llm_tools = llm_bundle.get("llm_tools", self.llm_tools)

            shared_history: List[Dict[str, Any]] = []
            if history:
                for record in history:
                    shared_history.append({"role": "user", "content": record['user_input']})
                    if record.get('ai_response'):
                        shared_history.append({"role": "assistant", "content": record['ai_response']})
            shared_history.append({"role": "user", "content": user_input})

            max_rounds = 25
            round_index = 0
            combined_response_started = False

            while round_index < max_rounds:
                round_index += 1
                print(f"🧠 第 {round_index} 轮推理...")

                tools_messages = [{"role": "system", "content": self._get_tools_system_prompt()}] + shared_history
                tool_calls_check = None
                buffered_chunks: List[str] = []
                response_started = False

                try:
                    async for event in current_llm_tools.astream_events(tools_messages, version="v1"):
                        ev = event.get("event")
                        if ev == "on_chat_model_stream":
                            data = event.get("data", {})
                            chunk = data.get("chunk")
                            if chunk is None:
                                continue
                            try:
                                content_piece = getattr(chunk, 'content', None)
                            except Exception:
                                content_piece = None
                            if content_piece:
                                if not combined_response_started:
                                    yield {"type": "ai_response_start", "content": "AI正在回复..."}
                                    combined_response_started = True
                                response_started = True
                                buffered_chunks.append(content_piece)
                                print(f"📤 [判定LLM流] {content_piece}")
                                yield {"type": "ai_response_chunk", "content": content_piece}
                        elif ev == "on_chat_model_end":
                            data = event.get("data", {})
                            output = data.get("output")
                            try:
                                tool_calls_check = getattr(output, 'tool_calls', None)
                            except Exception:
                                tool_calls_check = None
                except Exception as e:
                    print(f"⚠️ 工具判定失败：{e}")
                    tool_calls_check = None

                if tool_calls_check:
                    if response_started and buffered_chunks:
                        yield {"type": "ai_response_chunk", "content": "\n\n"}
                        buffered_chunks = []

                    tool_calls_to_run = tool_calls_check
                    yield {"type": "tool_plan", "content": f"AI决定调用 {len(tool_calls_to_run)} 个工具", "tool_count": len(tool_calls_to_run)}

                    try:
                        shared_history.append({
                            "role": "assistant",
                            "content": "",
                            "tool_calls": tool_calls_to_run
                        })
                    except Exception:
                        shared_history.append({"role": "assistant", "content": ""})

                    for i, tool_call in enumerate(tool_calls_to_run, 1):
                        if isinstance(tool_call, dict):
                            tool_id = tool_call.get('id') or f"call_{i}"
                            fn = tool_call.get('function') or {}
                            tool_name = fn.get('name') or tool_call.get('name') or ''
                            tool_args_raw = fn.get('arguments') or tool_call.get('args') or {}
                        else:
                            tool_id = getattr(tool_call, 'id', None) or f"call_{i}"
                            tool_name = getattr(tool_call, 'name', '') or ''
                            tool_args_raw = getattr(tool_call, 'args', {}) or {}

                        if isinstance(tool_args_raw, str):
                            try:
                                parsed_args = json.loads(tool_args_raw) if tool_args_raw else {}
                            except Exception:
                                parsed_args = {"$raw": tool_args_raw}
                        elif isinstance(tool_args_raw, dict):
                            parsed_args = tool_args_raw
                        else:
                            parsed_args = {"$raw": str(tool_args_raw)}

                        yield {"type": "tool_start", "tool_id": tool_id, "tool_name": tool_name, "tool_args": parsed_args, "progress": f"{i}/{len(tool_calls_to_run)}"}

                        try:
                            target_tool = next((tool for tool in self.tools if tool.name == tool_name), None)
                            if target_tool is None:
                                error_msg = f"工具 '{tool_name}' 未找到"
                                print(f"❌ {error_msg}")
                                yield {"type": "tool_error", "tool_id": tool_id, "error": error_msg}
                                tool_result = f"错误: {error_msg}"
                            else:
                                tool_result = await target_tool.ainvoke(parsed_args)
                                yield {"type": "tool_end", "tool_id": tool_id, "tool_name": tool_name, "result": str(tool_result)}
                        except Exception as e:
                            error_msg = f"工具执行出错: {e}"
                            print(f"❌ {error_msg}")
                            yield {"type": "tool_error", "tool_id": tool_id, "error": error_msg}
                            tool_result = f"错误: {error_msg}"

                        shared_history.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "name": tool_name,
                            "content": str(tool_result)
                        })

                    continue

                final_text = "".join(buffered_chunks) if buffered_chunks else ""
                if combined_response_started:
                    yield {"type": "ai_response_end", "content": ""}
                else:
                    yield {"type": "ai_response_start", "content": "AI正在回复..."}
                    combined_response_started = True
                    if final_text:
                        print(f"📤 [最终回复流] {final_text}")
                        yield {"type": "ai_response_chunk", "content": final_text}
                    yield {"type": "ai_response_end", "content": ""}
                return

            print(f"⚠️ 达到最大推理轮数({max_rounds})")
            final_text = "已达到最大推理轮数，请缩小问题范围或稍后重试。"
            yield {"type": "ai_response_start", "content": "AI正在回复..."}
            yield {"type": "ai_response_chunk", "content": final_text}
            yield {"type": "ai_response_end", "content": final_text}
            return

        except Exception as e:
            import traceback
            print(f"❌ chat_stream 异常: {e}")
            traceback.print_exc()
            yield {"type": "error", "content": f"处理请求时出错: {str(e)}"}

    def get_tools_info(self) -> Dict[str, Any]:
        if not self.tools_by_server:
            return {"servers": {}, "total_tools": 0, "server_count": 0}

        servers_info = {}
        total_tools = 0

        for server_name, server_tools in self.tools_by_server.items():
            tools_info = []

            for tool in server_tools:
                tool_info = {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {},
                    "required": []
                }

                try:
                    schema = None

                    if hasattr(tool, 'args_schema') and tool.args_schema:
                        if isinstance(tool.args_schema, dict):
                            schema = tool.args_schema
                        elif hasattr(tool.args_schema, 'model_json_schema'):
                            schema = tool.args_schema.model_json_schema()

                    if not schema and hasattr(tool, 'tool_call_schema') and tool.tool_call_schema:
                        schema = tool.tool_call_schema

                    if not schema and hasattr(tool, 'input_schema') and tool.input_schema:
                        if isinstance(tool.input_schema, dict):
                            schema = tool.input_schema
                        elif hasattr(tool.input_schema, 'model_json_schema'):
                            try:
                                schema = tool.input_schema.model_json_schema()
                            except:
                                pass

                    if schema and isinstance(schema, dict):
                        if 'properties' in schema:
                            tool_info["parameters"] = schema['properties']
                            tool_info["required"] = schema.get('required', [])
                        elif 'type' in schema and schema.get('type') == 'object' and 'properties' in schema:
                            tool_info["parameters"] = schema['properties']
                            tool_info["required"] = schema.get('required', [])

                except Exception as e:
                    print(f"⚠️ 获取工具 '{tool.name}' 参数信息失败: {e}")

                tools_info.append(tool_info)

            servers_info[server_name] = {
                "name": server_name,
                "tools": tools_info,
                "tool_count": len(tools_info)
            }

            total_tools += len(tools_info)

        return {
            "servers": servers_info,
            "total_tools": total_tools,
            "server_count": len(servers_info)
        }

    async def close(self):
        try:
            if self.mcp_client and hasattr(self.mcp_client, 'close'):
                await self.mcp_client.close()
        except:
            pass