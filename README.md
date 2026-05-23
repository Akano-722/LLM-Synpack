# SynPack 协同救援系统 · FastAPI + Zeabur 部署版

这个工程用于把 `radar_ai_v1.html` 前端页面和 FastAPI 后端 API 合并部署到 Zeabur 的同一个服务里。

前端页面负责展示雷达态势、机器狗状态和 AI 任务指挥面板。
后端负责接收自然语言任务，调用大模型或规则解析，返回机器狗可执行的 JSON 动作计划。

## 目录结构

```text
synpack-fastapi-zeabur-src/
├── src/
│   ├── __init__.py
│   ├── main.py
│   └── radar_ai_v1.html
├── Dockerfile
├── requirements.txt
├── .dockerignore
├── .env.example
└── README.md
```

注意：后端代码放在 `src/` 文件夹里，Dockerfile 仍然放在项目根目录。Zeabur 部署时选择这个仓库根目录即可。

## 本地运行

先进入项目根目录：

```bash
cd synpack-fastapi-zeabur-src
```

安装依赖：

```bash
pip install -r requirements.txt
```

启动服务：

```bash
uvicorn src.main:app --reload --host 0.0.0.0 --port 3007
```

浏览器打开：

```text
http://127.0.0.1:3007/
```

不要双击打开 `radar_ai_v1.html`。必须通过 FastAPI 地址打开，否则前端请求 `/api/ai/parse-task` 会找不到后端。

## Zeabur 部署

1. 把整个项目上传到 GitHub。
2. Zeabur 新建服务，选择该 GitHub 仓库。
3. 构建方式选择 Dockerfile。
4. 端口配置填写：

```text
3007
```

5. 协议选择 HTTP。
6. 部署完成后访问 Zeabur 分配的公网域名。

访问入口：

```text
https://你的服务域名/
```

AI 解析接口：

```text
https://你的服务域名/api/ai/parse-task
```

## Zeabur 环境变量

第一版如果只想先演示，不接真实大模型，可以这样：

```text
PORT=3007
LLM_PROVIDER=mock
CORS_ALLOW_ORIGINS=*
```

如果要接真实大模型 API，填写：

```text
PORT=3007
LLM_PROVIDER=openai_compatible
LLM_API_KEY=你的大模型APIKey
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_TIMEOUT=25
CORS_ALLOW_ORIGINS=*
```

如果你使用 DeepSeek 这类兼容 OpenAI 格式的接口，可以改成类似：

```text
LLM_PROVIDER=openai_compatible
LLM_API_KEY=你的DeepSeek_APIKey
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

具体 `BASE_URL` 和 `MODEL` 以你使用的平台为准。别乱填，后端不会替人类猜宇宙奥秘。

## API 说明

### GET /

返回前端页面。

### GET /health

健康检查。

返回示例：

```json
{
  "status": "ok",
  "service": "synpack-ai-server"
}
```

### POST /api/ai/parse-task

请求示例：

```json
{
  "message": "让A号机器狗恢复平衡后向前搜索，发现被困人员后停止",
  "currentRobot": "A",
  "currentRobotId": 1,
  "multiMode": false,
  "connectedRobots": ["A"],
  "robotStatus": {}
}
```

返回示例：

```json
{
  "intent": "rescue_task",
  "mode": "single",
  "target": "A",
  "risk_level": "medium",
  "need_confirm": true,
  "actions": [
    {
      "name": "balance",
      "cmd": "k balance",
      "description": "恢复平衡"
    },
    {
      "name": "forward",
      "cmd": "k wkF",
      "description": "向前搜索"
    }
  ],
  "reason": "已将自然语言任务解析为机器狗动作序列。"
}
```

## 大模型解析逻辑

后端支持两种模式。

### mock 模式

不调用真实大模型，只用规则解析。

适合第一版演示和链路测试。

```text
LLM_PROVIDER=mock
```

### openai_compatible 模式

调用兼容 OpenAI `/chat/completions` 格式的大模型接口。

```text
LLM_PROVIDER=openai_compatible
LLM_API_KEY=你的APIKey
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

如果大模型接口失败，后端会自动降级到规则解析，防止现场演示炸成烟花。

## 前端执行逻辑

前端 AI 面板流程：

```text
输入自然语言任务
↓
调用 /api/ai/parse-task
↓
展示 AI 任务计划
↓
用户点击确认执行
↓
复用原页面 WebSocket 指令通道
↓
发送 k balance / k wkF / d 等机器狗命令
```

第一版先做“解析-预览-确认-执行”。不要一上来让大模型全自动控制机器狗，除非你特别想给答辩老师表演电子生物发疯。

## 常见问题

### 1. Zeabur 访问页面空白

先看日志是否有 Python 报错。
再访问：

```text
https://你的域名/health
```

如果 `/health` 正常，说明后端启动了，问题多半在前端文件路径。
本工程已用 `BASE_DIR / "radar_ai_v1.html"` 固定路径，正常不会丢。

### 2. 端口不对

本工程默认端口是 `3007`。
Zeabur 端口配置也填 `3007`。

### 3. API Key 放在哪里

放 Zeabur 的环境变量里，不要写进前端，不要写进 GitHub。
把 API Key 写进前端等于把钱包挂门口，路人看了都想劝你冷静。

### 4. 前端连接机器狗失败

这个工程只负责托管前端和 AI 解析接口。
机器狗 WebSocket 仍然需要机器狗本体在网络上可访问。
如果公网页面要直接连局域网机器狗 IP，浏览器和网络环境可能会拦，需要后续再做 ROS/MCP 网关。

## 后续升级建议

第一版：AI 解析 + 计划预览 + 确认执行。

第二版：后端接 MCP，由后端统一转发机器狗控制命令。

第三版：加入 ROS 状态回传、任务日志持久化、多机调度策略。

第四版：接入真实生命探测数据和地图定位。
