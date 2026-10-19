# DeepSeek 智能 JD 创建

## 现有项目分析与修改边界

检查对象为现有 `outputs/recruiting-copilot` 项目，不是此前的 V2 效果图。

| 部分 | 当前实现 | 本次处理 |
|---|---|---|
| 前端 | 原生 HTML/CSS/JavaScript，`static/app.js` 管理六步页面 | 新增 `static/job-form.js`，只替换创建岗位按钮的页面处理函数 |
| 后端 | Python `ThreadingHTTPServer`，`server.py` 按路径分派 | 新增两个接口，沿用 Host 和请求令牌校验 |
| 数据库 | SQLite，jobs(id,data)、candidates(id,job_id,data)，data 为 JSON | 无数据库迁移、无删除或改写旧记录 |
| 业务 | `core.py` 的岗位保存、候选人状态机、提醒、复盘、确认与材料版本 | 文件与业务逻辑不修改 |
| 原 AI | `ai.py` 使用 AI_API_KEY/AI_BASE_URL/AI_MODEL | 保持不变；JD 使用单独的 DEEPSEEK_API_KEY |
| 文件解析 | `documents.py` 支持文字 PDF/DOCX，扫描件不含 OCR | 保持不变 |
| 启动 | Start.cmd → start.ps1 → server.py，默认端口8765 | 原方式保留，新增隐蔽输入密钥的 Start-DeepSeek.cmd |

不安装新框架或 SDK。使用 Python 标准库调用 OpenAI 兼容 Chat Completions HTTP 协议。服务地址固定为 https://api.deepseek.com，模型固定为 deepseek-flash。

## 操作流程

创建岗位 → 输入口语化需求 → AI 整理 JD → 编辑八类草稿字段 → 填入岗位表单 → 检查原岗位字段 → 勾选人工确认 → 保存岗位。

职责、要求和待确认事项都可逐行修改。人工确认后修改岗位表单，会取消勾选，须重新确认。生成或填入草稿均不写数据库。

原有手工创建方式仍可用，无密钥、接口失败或网络中断时不受影响。不会从岗位、候选人或简历库中附加任何资料到 JD 请求；仅发送用户在新输入框中输入的文字。

## 结构化 JSON 与旧字段映射

```json
{
  "brand": "",
  "title": "",
  "location": "",
  "responsibilities": [],
  "requirements": [],
  "salary": "",
  "working_hours": "",
  "pending_items": []
}
```

brand→brand，title→title，location→city，salary→salary，working_hours→hours。responsibilities、requirements、pending_items 依次排为“岗位职责／任职要求／待确认事项”，合并至原有 jd 字符串。

原 store、mentor、faq、questions、template 字段保持原样。八类 JSON 用于生成草稿，不增加数据库字段或将 JSON 文本塞入新列；如未来需要按职责条目查询，可另行设计迁移。

## 后端接口

- `POST /api/jd-draft`，请求 `{ "text": "虚构口语化JD" }`。成功响应含 draft、warnings、model，不写库。
- `POST /api/job-from-jd`，请求 `{ "confirmed": true, "job": { ...原岗位字段... } }`。缺少布尔确认即拒绝；服务端过滤传输元数据后复用原 Store.action('job', ...) 保存。
- 原 `POST /api/job` 手工创建接口保持可用，不附加新的确认要求。

密钥只从后端进程环境变量 DEEPSEEK_API_KEY 读取。前端不接收密钥；失败时不返回上游原始报错、请求头或响应内容。跨站重定向被禁用，避免 Authorization 被转发。调用不占用数据库锁，同一服务最多同时处理两个 JD 调用，忙时提示稍后重试。

## 防编造与失败处理

- 使用 JSON Output，关闭思考模式，限制输入12000字、输出4096 tokens，并检查字段名、类型、空响应、截断响应及响应体大小。
- 未提供的信息必须为空；非空事实必须能匹配原输入连续片段。未匹配内容被剔除并给出人工核对提示。
- 待确认事项采用字段名列表，例如薪资、工作时间，不生成未经证实的岗位条件。
- 原文片段校验不能证明语义理解一定正确，否定、条件、矛盾仍须人工核对。模型可能漏提取，所以不是自动发布工具。
- 后端连接/读操作超时30秒，并检查读取时限；前端40秒停止等待，支持取消。取消等待后不会应用迟到结果；已开始的上游请求不保证能立即取消，也不自动重试产生额外调用。
- 缺密钥、密钥错误、余额不足、限流、服务异常、网络失败、超时、无效JSON均有明确提示，输入保留在当前页面。尚未保存的草稿不跨刷新持久化。

## Windows 启动

先停止旧 Python 服务，避免新启动的进程无法使用8765端口。原来从窗口启动时按 Ctrl+C；不要同时运行两个服务访问同一个数据库。

推荐双击 `Start-DeepSeek.cmd`，在本机控制台输入密钥（输入隐藏，不写文件、不进入命令历史），保持窗口打开，Edge 访问 http://127.0.0.1:8765 。后台仍然只通过环境变量 DEEPSEEK_API_KEY 获取密钥。

也可以在项目目录的 PowerShell 中运行：

```powershell
.\start-deepseek.ps1
```

该脚本在当前进程已有 DEEPSEEK_API_KEY 时直接使用，否则安全提示输入。不会加载 .env 文件，不会把密钥保存在代码中。修改系统环境变量后，已经运行的 Python 进程不会自动更新，须重新启动。

若需要使用其他空闲端口：

```powershell
$env:COPILOT_PORT='8766'
.\start-deepseek.ps1
```

此时访问 http://127.0.0.1:8766 。不要把密钥粘贴到网页、聊天、源代码或截图中。

当前电脑沿用已有 Python 与文档依赖。其他电脑依旧按 README 安装 Python 3.11+ 和 requirements.txt，无需为本功能额外安装 openai SDK。

## 验证方式与已完成验证

在项目目录运行 `python -m unittest -v`；此电脑可使用已配置的 Python 路径。完整测试含原文档测试依赖 reportlab。

测试使用虚构需求：

> 【虚构测试】星河运动在上海招店长，负责排班和库存管理，需要两年门店经验，薪资还没定。

预期：品牌、岗位、地点、职责、要求可提取；薪资和工作时间留空，列入待确认。可人工改为另一个岗位名称；不勾选确认不能保存；修改表单后确认失效；保存后刷新仍存在。

已通过20项 Python 测试：原7项回归、新接口协议、字段校验、清空无依据值、无密钥、认证/余额/限流/服务错误、超时、错误JSON、禁用重定向、确认保存、无数据库锁阻塞等。

已在隔离数据库和模拟模型服务上使用 Edge 验证：加载状态、生成、编辑、空字段、确认重置、保存、刷新持久化、失败、取消、手工回退、页面无脚本错误，前端与接口返回不含测试密钥。没有上传真实候选人信息。

当前环境未配置真实 DEEPSEEK_API_KEY，因此尚未做真实付费 API 联调；模拟接口测试通过不等于真实服务已经连通。配置后使用上面虚构 JD 完成最后一次验证。

## 官方接口依据

- [DeepSeek 首次 API 调用](https://api-docs.deepseek.com/)
- [JSON Output](https://api-docs.deepseek.com/guides/json_mode/)
- [Chat Completions 参数](https://api-docs.deepseek.com/api/create-chat-completion/)
