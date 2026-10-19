# Recruiting Copilot MVP v1.0

面向猎头、RPO 与招聘顾问的 AI 招聘辅助工作台，覆盖岗位整理、候选人初筛、信息补全、电话面试和推荐材料制作。AI 用于整理信息与提供建议，最终推荐决定由招聘人员作出。

本发布来自维护者已完成业务流程及 DeepSeek 调用测试的稳定工作副本。Git 发布名称为 **MVP v1.0**；应用沿用现有 V2 页面、文件名与内部 `2.0` 标识，本次发布不重构业务、不修改网页。

## 实际功能

| 步骤 | 当前实现 |
| --- | --- |
| 岗位与模板 | 手工创建岗位；口语化 JD 经 DeepSeek 整理成结构化草稿；人工编辑、确认后保存；绑定受支持的 Word 模板版本 |
| 简历初筛 | PDF / DOCX 本地文字提取或粘贴原文；本地规则整理；可选 AI 提取草稿；多段教育、工作及门店信息可编辑 |
| 信息补全 | 展示已知信息，单独列出空缺；支持未提供、不适用及重新询问；自动保存结构化信息 |
| 电话安排 | 安排、改期、取消、未接通；岗位问题与缺失信息组成提问卡；T-60 / T-10 页面提醒 |
| 电话复盘 | 分开记录客观数据、沟通信号和主观评价；AI 从客观记录提取补充，逐项确认后才更新字段 |
| 总结与推荐 | 人工选择推荐或不推荐，不推荐要求原因；侧栏归档和重新打开；推荐后导出可编辑 Word |

其他已实现能力：候选人/岗位搜索、同名新增提醒、同一人物关联不同岗位申请、修改前快照、版本冲突检查、数据库备份与恢复、每日服务运行时备份。不同岗位申请的后续修改不会自动同步。

Word 输出依赖本地授权模板；期望薪资、照片、离职原因和主观评价保留空位，交由猎头编辑。内部记录不因导出留白而删除。

## 技术栈与目录

- 后端：Python 标准库 `http.server`、`threading`、`urllib`，不是 Flask / FastAPI。
- 前端：原生 HTML、CSS、JavaScript，无 Node 构建步骤。
- 持久化：SQLite；岗位与候选人保留 JSON 数据，另有修改历史与 Word 模板表。
- 文档：`pypdf` 提取 PDF 文本；`python-docx` 读写 DOCX。
- AI：后端调用 OpenAI 兼容的 Chat Completions 接口；不依赖 OpenAI SDK。

```text
server.py                 HTTP 服务、接口、提醒循环
core.py / store_v2.py      原有流程及 V2 数据操作
profile_v2.py              履历结构、本地提取、缺失项
ai.py                     保留的旧版通用模型适配器
deepseek_jd.py / ai_v2.py   JD 与 V2 AI 功能
documents.py / word_v2.py   简历解析、模板 Word 输出
static/                   现有 V1 / V2 页面和脚本
assets/README.md          本地授权模板的格式要求
requirements*.txt         运行和测试依赖
test_*.py                 使用虚构资料的自动测试
```

## Windows 本地启动

推荐 Python 3.12；代码需要 Python 3.11+ 及支持 `sqlite3.Connection.serialize/deserialize` 的 SQLite 构建。本次检查环境为 Python 3.12.14、pypdf 6.10.0、python-docx 1.2.0；版本范围见依赖文件。

在项目根目录打开 PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\Start-V2.cmd
```

默认用 Edge 打开 `http://127.0.0.1:8765/`。保留的旧版入口为 `/v1`。也可前台运行：

```powershell
.\.venv\Scripts\python.exe server.py
```

第一次启动会创建空的 `data/copilot.sqlite3`。Git 不包含任何已有业务记录。`data/.gitkeep` 仅保证目录存在，避免后台启动脚本写入 PID 时缺少目录。

- `Start-V2.cmd`：后台启动；已存在内部版本为 2.0 的服务时直接打开它。
- `Stop-V2.cmd`：停止本目录 PID 文件指向、且命令行匹配本目录的服务。
- `Start.cmd`：前台启动，便于看到错误。
- 若其他副本占用 8765，先停止对应服务，或设置不同端口；否则可能打开另一副本。不要把“能打开网页”当作已切换目录的证明。

```powershell
$env:COPILOT_PORT = '8766'
.\.venv\Scripts\python.exe server.py
```

## DeepSeek 配置

V2 默认读取后端环境变量 `DEEPSEEK_API_KEY`；地址固定为 `https://api.deepseek.com`，模型为 `deepseek-flash`。接口为 `/chat/completions`，支持 JSON 输出、超时和失败提示。密钥不应放入前端、仓库或文档。

先停止旧服务，再双击 `Start-DeepSeek.cmd`。脚本用隐藏输入读取密钥，只放入本次启动进程的环境，随后前台运行后端；保持该窗口开启。也可以通过操作系统已有的进程环境变量启动。项目**不会自动读取 `.env`**。

不配置密钥时，手工整理、持久化和配置好模板后的 Word 导出仍可使用。点击候选人 AI 操作会提示发送内容；JD 输入、简历原文、电话记录或职业信息会按对应操作传到模型服务。只处理有授权的资料，并人工核查 AI 输出。

旧版 `/v1` 的通用 AI 适配器另用 `AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL`；它们不替代 V2 的 DeepSeek 配置。`COPILOT_DB_PATH` 可指定独立数据库，测试不应指向业务数据库。

## 本地 Word 模板

为避免上传客户内部资料，仓库不包含公司的 Word 模板、Logo、照片、真实简历或生成材料。本机已有模板保留，不删除。

从 Git 克隆后，需自行将获授权且符合既有结构的模板放到 `assets/adidas-store-v1.docx`，或通过第一步上传同结构模板并绑定岗位。默认模板缺失时，其他流程能启动，但默认 Word 导出会失败。格式要求见 [assets/README.md](assets/README.md)。当前不支持任意布局的自动模板映射。

## 检查与测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s . -p "test_*.py"
```

2026-10-18 发布检查：27 项测试通过；仅含拟上传文件的干净副本同样通过 27 项测试，并通过空数据库 HTTP 页面与状态接口检查。Python / JavaScript 语法检查通过。

测试覆盖原流程、JD 人工确认、接口错误、原文依据过滤、缺失信息、提醒、修改冲突、归档、多岗位、模板输出留白和备份恢复。PDF 测试需要 `reportlab`，因此它仅列入开发依赖。Word 测试临时生成虚构模板，不依赖内部资产。

本次发布检查使用虚构资料和模拟模型响应，不发送真实候选人资料、不调用收费模型接口。维护者此前已完成真实接口与实际模板验收；这与自动测试覆盖范围是两回事。

## 数据排除与当前局限

`.gitignore` 只允许代码、启动脚本、经过审核的文档和空目录占位文件进入待提交范围，排除数据库、备份、环境变量文件、密钥、Word/PDF/表格、截图、压缩包、日志、PID、缓存和本地发布审计文件。Private 仓库也不用于备份这些业务资料。

- 当前是 Windows 单人本地 MVP，没有用户登录、多人权限、数据库加密或互联网部署保障；只绑定回环地址，不应直接暴露到公网。
- 提醒依赖服务运行和页面查看，不是系统推送，也不能在关机期间即时提醒。
- PDF 仅提取文字，不含 OCR；复杂排版可能需要人工修正。AI 原文片段检查不能保证语义理解完全正确。
- 部分履历草稿保存在浏览器会话中；这不是完整的离线同步或零丢失保障。数据库与备份需本机妥善保管。
- Word 导出反映当前记录与岗位模板，不是不可变的历史提交包。候选人确认与外部提交仍由人工处理；旧版确认流程保留在 `/v1`。
- 不监控招聘平台、不读取微信、不自动发送材料，也不自动作最终招聘决定。
- 前端和渲染器仍保留现有门店模板名称及适配标签，不意味着与相关品牌存在官方合作；内部文件没有随代码发布。
