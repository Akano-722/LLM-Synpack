import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="SynPack AI Control Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ParseTaskRequest(BaseModel):
    message: str = Field(..., description="用户输入的自然语言救援任务")
    currentRobot: Optional[str] = "A"
    currentRobotId: Optional[int] = 1
    multiMode: Optional[bool] = False
    connectedRobots: Optional[List[str]] = []
    robotStatus: Optional[Dict[str, Any]] = {}


ALLOWED_ACTIONS = {
    "stand": {"cmd": "k up", "description": "站立待命"},
    "sit": {"cmd": "k sit", "description": "坐下"},
    "rest": {"cmd": "k rest", "description": "休息/趴下"},
    "balance": {"cmd": "k balance", "description": "恢复平衡"},
    "forward": {"cmd": "k wkF", "description": "向前搜索"},
    "backward": {"cmd": "k bk", "description": "后退"},
    "turn_left": {"cmd": "k trL", "description": "左转"},
    "turn_right": {"cmd": "k trR", "description": "右转"},
    "stop": {"cmd": "d", "description": "停止"},
    "detect_life": {"cmd": "detect_life", "description": "开启生命探测/救援搜索"},
}

ROBOT_LETTERS = ["A", "B", "C", "D", "E"]


def make_action(name: str) -> Dict[str, str]:
    item = ALLOWED_ACTIONS[name]
    return {"name": name, "cmd": item["cmd"], "description": item["description"]}


def normalize_robot_name(text: Optional[str], default: str = "A") -> str:
    if not text:
        return default
    text = str(text).upper()
    for letter in ROBOT_LETTERS:
        if letter in text:
            return letter
    return default


def contains_any(text: str, words: List[str]) -> bool:
    return any(word in text for word in words)


def rule_based_parse(req: ParseTaskRequest) -> Dict[str, Any]:
    """第一版兜底规则解析。先保证前后端链路能跑，再接真实大模型。"""
    text = req.message.strip()
    current_robot = normalize_robot_name(req.currentRobot, "A")

    # 多机任务判断
    multi_words = ["多机", "协同", "同步", "编队", "分别", "A和B", "A 和 B", "AB", "两只", "多只"]
    mentioned = [letter for letter in ROBOT_LETTERS if re.search(rf"\b{letter}\b|{letter}号|机器狗{letter}", text, re.IGNORECASE)]
    is_multi = bool(req.multiMode) or contains_any(text, multi_words) or len(mentioned) >= 2

    if is_multi:
        targets = mentioned or ["A", "B"]
        assignments = []
        for target in targets[:5]:
            actions = [make_action("balance")]
            if target in ["A", "C", "E"]:
                if contains_any(text, ["左", "左侧", "两侧", "分别"]):
                    actions.append(make_action("turn_left"))
            else:
                if contains_any(text, ["右", "右侧", "两侧", "分别"]):
                    actions.append(make_action("turn_right"))

            if contains_any(text, ["搜索", "巡检", "前进", "靠近", "搜救"]):
                actions.append(make_action("forward"))
            if contains_any(text, ["生命", "被困", "救援", "探测", "扫描"]):
                actions.append(make_action("detect_life"))
            if contains_any(text, ["待命", "原地", "不动"]):
                actions = [make_action("stand")]

            assignments.append({
                "target": target,
                "task": "协同搜救任务",
                "actions": actions,
            })

        return {
            "intent": "multi_robot_task",
            "mode": "multi",
            "target": ",".join(targets),
            "risk_level": "high",
            "need_confirm": True,
            "assignments": assignments,
            "reason": "任务涉及多机协同或同步移动，必须人工确认后执行。",
        }

    # 单机任务
    actions: List[Dict[str, str]] = []

    if contains_any(text, ["平衡", "恢复", "复位"]):
        actions.append(make_action("balance"))
    if contains_any(text, ["站立", "起来", "待命"]):
        actions.append(make_action("stand"))
    if contains_any(text, ["坐下", "坐"]):
        actions.append(make_action("sit"))
    if contains_any(text, ["趴下", "休息", "卧倒"]):
        actions.append(make_action("rest"))
    if contains_any(text, ["左转", "左侧", "向左"]):
        actions.append(make_action("turn_left"))
    if contains_any(text, ["右转", "右侧", "向右"]):
        actions.append(make_action("turn_right"))
    if contains_any(text, ["后退", "撤退", "往后"]):
        actions.append(make_action("backward"))
    if contains_any(text, ["前进", "搜索", "巡检", "靠近", "搜救", "扫描"]):
        actions.append(make_action("forward"))
    if contains_any(text, ["生命", "被困", "救援", "探测", "扫描"]):
        actions.append(make_action("detect_life"))
    if contains_any(text, ["停止", "停下", "急停"]):
        actions.append(make_action("stop"))

    if not actions:
        actions = [make_action("stand")]

    moving_cmds = {"k wkF", "k bk", "k trL", "k trR"}
    has_motion = any(action["cmd"] in moving_cmds for action in actions)
    risk_level = "medium" if has_motion else "low"

    return {
        "intent": "rescue_task",
        "mode": "single",
        "target": current_robot,
        "risk_level": risk_level,
        "need_confirm": True,
        "actions": actions,
        "reason": "已将自然语言任务解析为机器狗动作序列。",
    }


def extract_json_from_text(text: str) -> Dict[str, Any]:
    """兼容模型偶尔把 JSON 包在代码块里的坏毛病。机器也会乱吐，真是学坏了。"""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def build_llm_prompt(req: ParseTaskRequest) -> str:
    return f"""
你是 SynPack 协同救援系统的任务解析模型。
你的职责是把用户自然语言转成机器狗可执行的严格 JSON。
禁止输出闲聊。禁止输出 Markdown。只能输出 JSON。

当前视角机器狗：{req.currentRobot or 'A'}
是否多机同步：{req.multiMode}
已连接机器狗：{req.connectedRobots}

可用机器狗编号：A, B, C, D, E。

可用动作，只能使用以下 cmd：
- stand: k up
- sit: k sit
- rest: k rest
- balance: k balance
- forward: k wkF
- backward: k bk
- turn_left: k trL
- turn_right: k trR
- stop: d
- detect_life: detect_life

输出格式之一，单机任务：
{{
  "intent": "rescue_task",
  "mode": "single",
  "target": "A",
  "risk_level": "low | medium | high",
  "need_confirm": true,
  "actions": [
    {{"name": "balance", "cmd": "k balance", "description": "恢复平衡"}}
  ],
  "reason": "一句话说明原因"
}}

输出格式之二，多机任务：
{{
  "intent": "multi_robot_task",
  "mode": "multi",
  "target": "A,B",
  "risk_level": "high",
  "need_confirm": true,
  "assignments": [
    {{
      "target": "A",
      "task": "左侧搜索",
      "actions": [
        {{"name": "balance", "cmd": "k balance", "description": "恢复平衡"}}
      ]
    }}
  ],
  "reason": "一句话说明原因"
}}

规则：
1. 涉及移动，risk_level 至少为 medium。
2. 涉及多机，risk_level 必须为 high。
3. 指令模糊时，need_confirm 为 true。
4. 不允许输出可用动作之外的 cmd。

用户任务：{req.message}
""".strip()


def validate_plan(plan: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    """基础校验，避免模型输出奇怪命令把狗送去追月亮。"""
    allowed_cmds = {item["cmd"] for item in ALLOWED_ACTIONS.values()}

    def clean_action(action: Dict[str, Any]) -> Optional[Dict[str, str]]:
        cmd = action.get("cmd")
        if cmd not in allowed_cmds:
            return None
        name = str(action.get("name") or cmd)
        desc = str(action.get("description") or name)
        return {"name": name, "cmd": cmd, "description": desc}

    if plan.get("mode") == "multi" or plan.get("assignments"):
        assignments = []
        for item in plan.get("assignments", []):
            target = normalize_robot_name(item.get("target"), "A")
            actions = [clean_action(a) for a in item.get("actions", []) if isinstance(a, dict)]
            actions = [a for a in actions if a]
            if actions:
                assignments.append({
                    "target": target,
                    "task": str(item.get("task") or "协同任务"),
                    "actions": actions,
                })
        if not assignments:
            return fallback
        return {
            "intent": "multi_robot_task",
            "mode": "multi",
            "target": ",".join(item["target"] for item in assignments),
            "risk_level": "high",
            "need_confirm": True,
            "assignments": assignments,
            "reason": str(plan.get("reason") or "大模型已生成多机协同任务。"),
        }

    actions = [clean_action(a) for a in plan.get("actions", []) if isinstance(a, dict)]
    actions = [a for a in actions if a]
    if not actions:
        return fallback

    moving_cmds = {"k wkF", "k bk", "k trL", "k trR"}
    has_motion = any(a["cmd"] in moving_cmds for a in actions)
    risk = plan.get("risk_level") or ("medium" if has_motion else "low")
    if risk not in ["low", "medium", "high"]:
        risk = "medium" if has_motion else "low"

    return {
        "intent": "rescue_task",
        "mode": "single",
        "target": normalize_robot_name(plan.get("target"), fallback.get("target", "A")),
        "risk_level": risk,
        "need_confirm": True,
        "actions": actions,
        "reason": str(plan.get("reason") or "大模型已生成动作序列。"),
    }


async def llm_parse(req: ParseTaskRequest, fallback: Dict[str, Any]) -> Dict[str, Any]:
    provider = os.getenv("LLM_PROVIDER", "mock").lower().strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()

    # 默认 mock/rule 模式，部署后立刻能演示。
    if provider in ["", "mock", "rule"] or not api_key:
        return fallback

    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    timeout = float(os.getenv("LLM_TIMEOUT", "25"))

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只输出严格 JSON，不输出 Markdown。"},
            {"role": "user", "content": build_llm_prompt(req)},
        ],
        "temperature": 0.1,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"]
    parsed = extract_json_from_text(content)
    return validate_plan(parsed, fallback)


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "radar_ai_v1.html")


@app.get("/health")
def health():
    return {"status": "ok", "service": "synpack-ai-server"}


@app.post("/api/ai/parse-task")
async def parse_task(req: ParseTaskRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")

    fallback = rule_based_parse(req)

    try:
        plan = await llm_parse(req, fallback)
        return JSONResponse(plan)
    except Exception as exc:
        # 大模型挂了也不影响演示，直接降级规则解析。人类演示最怕现场翻车。
        fallback["reason"] = f"大模型接口暂不可用，已降级为规则解析：{str(exc)[:120]}"
        fallback["llm_fallback"] = True
        return JSONResponse(fallback)
