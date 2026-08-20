# NA2H Web UI 单页重构执行方案

> 状态：implementation-ready，尚未实施
> 目标执行者：LunaMax
> 基线日期：2026-08-19
> 项目：`/home/nuc/NA2H/NotAccess2Hakimi`
> 参考实现：`/home/nuc/NA2H/EasyMultiProvider/easy_multi_provider/web/index.html`

## 1. 落地审判

### Landing Judgment

**Go，但必须分层落地。**

方向正确：NA2H 是一个本地、小规模管理工具，不需要 Dashboard、Credentials、Usage、Settings 四个伪页面，也不需要常驻侧边栏。应改成 EMP 风格的单页控制台。

但第一步不能是视觉重写。当前 Edit 会以空字段覆盖已有密钥，这是数据正确性问题。必须先用后端回归测试固定“留空保留已有密钥”的契约，再更换页面结构，否则新 UI 会建立在错误的更新语义上。

### Bold Direction Kept

最终目标不是“把当前页面美化一下”，而是把 NA2H 的管理界面收敛为一个更可信、更紧凑的本地操作台：

- 一个页面看完服务状态、凭证、测试结果、用量和设置。
- 用户能明确区分“已保存”“可调度”“真实测试成功”三种状态。
- 编辑非敏感字段时永远不会意外清空密钥。
- 所有高延迟操作都有忙碌态、就地结果和明确错误。
- 不引入前端构建系统、框架或新的运行依赖。

### Reality Check

- **真实约束**：现有 YAML 配置格式、`0600` 文件权限、FastAPI 管理 API、SQLite 用量数据、单文件静态 UI、Bearer 登录、现有 AI Studio/Antigravity 调度和测试接口。
- **未经证明的假设**：单页一定比分页更清晰；需要通过 375px 和桌面宽度的真实页面检查验证，而不是只看源码。
- **最高爆炸半径**：凭证更新语义。任何错误都可能覆盖 API Key、Client Secret 或 Refresh Token。
- **最膨胀的部分**：为了一次 UI 重构引入 React/Vue、前端打包、持久化测试历史、数据库迁移或 EMP 的加密 secret store。

### Minimum Viable Move

- **先做**：只修改后端更新模型和测试，让空密钥保留旧值，并在 OAuth 身份字段确实变化时清除缓存 access token。
- **范围**：`routes/admin.py` 与 `tests/test_admin.py`。
- **明确不做**：第一步不改 HTML/CSS，不返回完整 secret，不新增依赖。
- **证明点**：旧页面即使仍提交空密码，也不再损坏凭证；这是后续 UI 重写可以依赖的稳定契约。

### Verification

- **成功标准**：AI Studio 与 Antigravity 的部分更新都保留未填写的 secret；修改 OAuth 字段后旧 token 不再复用。
- **失败信号**：保存 Edit 后配置中的 secret 变空、Test 从可用变为 `invalid_client`、或者更新接口必须把完整 secret 返回浏览器才能工作。
- **最便宜检查**：两条 API 回归测试，完全使用临时配置和假凭证。
- **扩展前置条件**：后端契约测试必须先绿，再替换页面。

### Cut List

- 不引入 React、Vue、Svelte、Tailwind、Vite 或 npm 构建步骤。
- 不复制 EMP 的整份配置 POST 和 `••••••••` 哨兵协议。
- 不迁移 NA2H 的 secret 到 EMP 的加密目录；这是独立安全项目。
- 不保存 Test 历史到 SQLite，不增加 schema migration。
- 不增加多主题、拖拽布局、图表库、动画系统或自定义图标集。
- 不修改聊天适配器协议，只消费现有管理 API 和测试接口。

### Stop Rule

出现以下任一情况就停止视觉扩张，保留已完成的安全更新契约：

- 新页面必须读取或回传完整 secret 才能编辑。
- 单文件 UI 因本次改动超过可理解范围，需要先拆分构建系统才能继续。
- 375px 宽度下核心凭证操作仍需横向滚动才能使用。
- 回归测试无法证明 Edit 不会覆盖旧凭证。
- 重构开始改变 YAML、数据库或推理 API 的兼容行为。

## 2. 当前问题定义

### 2.1 已确认的 Edit 缺陷

当前 NA2H 的数据流是：

1. `GET /api/credentials` 只返回掩码后的 API Key / Refresh Token。
2. Edit Modal 不回填 secret，输入框呈现为空。
3. 前端 `saveCred()` 又要求所有 secret 必填。
4. PUT 路由重新构造整个 credential 对象。
5. 用户为了修改一个字段，被迫重新输入所有 secret；任何复制错误都会覆盖原值。

这不是单纯的“看起来像空”，而是前后端更新契约错误。

### 2.2 已确认的信息架构问题

NA2H 当前只有少量信息，却使用：

- 220px 常驻侧边栏。
- Dashboard / Credentials / Usage / Settings 四个隐藏 section。
- Credentials 内部再分 AI Studio / Antigravity 两个 tab。
- 每次切换 section 单独重新请求数据。

结果是空间利用率低、操作路径长，并且关联信息被拆开：用户在 Credentials 做 Test 后，还要切到 Dashboard 看状态、切到 Usage 看请求结果、切到 Settings 检查 Proxy。

### 2.3 已确认的状态表达问题

当前绿色 `ACTIVE` 来自 `CredentialPool` 的默认可调度状态，不代表：

- OAuth refresh 成功。
- Project discovery 成功。
- 模型推理成功。

Test 结果只显示三秒 Toast，随后页面仍只剩容易误解的 `ACTIVE`。

## 3. EMP 与 NA2H 交互对比

| 维度 | EMP 当前行为 | NA2H 当前行为 | NA2H 目标 |
|---|---|---|---|
| 信息架构 | 单页纵向 section，一次滚动完成操作 | 四个伪页面 + 凭证 tab | 单页纵向 section，无侧栏、无凭证 tab |
| 页面密度 | `max-width:1180px`，表格集中展示 | 主区 `max-width:960px`，大量留白 | 1100-1180px，自适应网格与紧凑列表 |
| 语言 | 中文优先，技术名词保留英文 | 全英文 | 中文优先，API/模型/错误保留英文 |
| 新增入口 | section 工具栏中的明确按钮 | tab 内独立按钮 | Credentials 标题栏同时提供两种新增按钮 |
| Edit 语义 | `留空保持已有值` | 空输入但强制全部重填 | secret 留空保留，非敏感字段回填 |
| Secret 暴露 | 只展示 `credential_set` / `api_key_set` | 展示 token/key 前缀 | 只展示“已设置/未设置”状态，不展示片段 |
| 后端更新 | `merge_web_update()` 保留 omitted secret | PUT 整体替换 credential | endpoint-specific 部分更新，不使用掩码哨兵 |
| 操作反馈 | 按钮 busy/disabled，Modal 内错误，固定 notice | 按钮可重复点击，主要依赖短暂 Toast | 按钮 busy、Modal 内错误、行内 Test 结果、全局 notice |
| 测试入口 | 模型行就地 Test | 凭证行 Test 已新增 | 保留凭证 Test，结果固定在对应行 |
| 状态语义 | 凭据保存、刷新错误分开显示 | `ACTIVE` 容易被当成已验证 | `可调度` 与 `测试成功/失败` 分开显示 |
| Modal | 一个可复用 Modal；提交期间禁用 | 每类表单拼接 HTML；无提交 busy | 一个可复用 Modal；focus、Escape、busy、inline error |
| 配置保存 | 整份公开 state POST，简单但耦合较大 | 细粒度 REST endpoint | 保留 NA2H 细粒度 endpoint，避免整份 state 覆盖 |
| 并发操作 | 一个全局 notice 可能互相覆盖 | Toast 也可能互相覆盖 | Test 结果按 credential ID 独立保存于页面 state |
| 移动端 | 表格横向滚动 | 缺少完整响应式规则 | 小屏切换为纵向 credential cards，不要求横向滚动 |
| 可访问性 | Modal 有 dialog/alert，已有基础 | Modal 缺少 dialog label 与错误区域 | 补 `role=dialog`、`aria-live`、focus restore |
| 维护成本 | 单 HTML，无框架，但 JS 字符串较密 | 单 HTML，无框架 | 继续单 HTML，按 state/render/action 分区而非压成一行 |

## 4. EMP 值得复制与不应复制的部分

### 4.1 直接吸收

1. **单页 section**：没有客户端路由，没有隐藏 page。
2. **系统字体和朴素面板**：不追求 Dashboard 装饰感。
3. **统一 Modal**：标题、正文、提交按钮、处理中状态、错误区域由一个函数管理。
4. **留空保留 secret**：用户只编辑自己想改的字段。
5. **Secret-set 元数据**：显示“已设置”，而不是返回 secret 片段。
6. **操作按钮就地放置**：Test / Edit / Delete 与目标对象同一行。
7. **中文优先**：降低本地运维工具的理解成本。
8. **小屏单列**：表单网格自动降为单列。

### 4.2 不复制

1. **整份配置 POST**：NA2H 已经有细粒度 API，继续使用它们更安全。
2. **`••••••••` 哨兵**：布尔 `*_set` 加 omitted-field 语义更明确。
3. **EMP secret store**：NA2H 本轮只修 UX，不做存储架构迁移。
4. **只有全局 notice**：NA2H 的 Test 是按凭证执行，结果应跟随该行。
5. **移动端横向表格**：凭证操作在小屏必须转成 card。
6. **把所有 JS 压缩成密集单行**：保持单文件不等于牺牲可读性。

### 4.3 在 EMP 基础上继续改进

- Secret 既不返回原值，也不返回伪 secret；只返回是否已设置。
- Update API 以路径中的 ID 为准，不允许在 Edit 中隐式改 ID。
- Test busy/result 使用 `provider:id` 作为键，不受其他操作覆盖。
- `可调度` 标签明确解释为本地池状态，避免冒充远端验证。
- Modal 打开时聚焦首个可编辑字段，Escape 关闭，关闭后焦点回到触发按钮。
- Settings 默认折叠，避免低频配置占据主视觉。

## 5. 目标页面线框

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Hakimi Proxy                                      ● 服务在线        │
│ OpenAI Base URL  http://127.0.0.1:8000/v1     [复制]               │
│ Model           antigravity/gemini-3.7-flash  [复制]               │
├─────────────────────────────────────────────────────────────────────┤
│ 1 / 1 可调度       12 Requests       8.4K Tokens       $0.013       │
├─────────────────────────────────────────────────────────────────────┤
│ Credentials                         [+ AI Studio] [+ Antigravity]    │
│                                                                     │
│ AI Studio                                                           │
│ ┌ ID ─────── 配置 ────── 本地状态 ───── 最近测试 ───── 操作 ─────┐ │
│ │ ai-main    Key 已设置   可调度          尚未测试   Test Edit Del │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ Antigravity                                                         │
│ ┌ ID ─────── Project ─── 配置 ───── 本地状态 ── 最近测试 ── 操作 ┐ │
│ │ my-agy     auto         OAuth 已设置 可调度      401 ...  T E D │ │
│ └─────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│ Usage                                            [刷新]              │
│ 按凭证统计                         按模型统计                         │
├─────────────────────────────────────────────────────────────────────┤
│ ▸ Settings                                                        │
└─────────────────────────────────────────────────────────────────────┘
```

移动端（小于 760px）：

- 顶部统计改成 2×2 或单列。
- 每条 credential 变成 card。
- 操作按钮换行，但保持 Test 第一、Edit 第二、Delete 最后。
- Usage 两张表纵向排列；超宽数据允许内容换行，不要求整个页面横向滚动。

## 6. 目标交互规范

### 6.1 页面加载

登录成功后并行读取：

- `GET /healthz`
- `GET /api/config`
- `GET /api/credentials`
- `GET /api/usage/summary`

前端单一内存状态：

```javascript
const state = {
  health: null,
  config: null,
  credentials: {aistudio: [], antigravity: []},
  usage: null,
  busy: new Set(),
  testResults: new Map(),
};
```

约束：

- `busy` 与 `testResults` 只存在浏览器内存，不写数据库。
- 单个 section 刷新失败不应清空其他已经加载的数据。
- 页面顶部显示最近一次全局操作结果；Test 同时保留行内结果。

### 6.2 新增 AI Studio

字段：

- ID：必填、创建后不可修改。
- API Key：必填，`type=password`。
- Project：可选。
- Account：可选。

提交时：

- 按钮显示“保存中…”并禁用。
- 失败显示在 Modal 内，不关闭 Modal。
- 成功关闭 Modal、刷新 credentials，并显示“AI Studio 凭证已添加”。

### 6.3 编辑 AI Studio

回填：

- ID（readonly）
- Project
- Account

不回填：

- API Key

API Key 标签：

```text
API Key（已设置；留空保留当前值）
```

保存规则：

- 空 `api_key`：保留旧值。
- 非空 `api_key`：替换旧值。
- Project / Account 按当前输入更新，允许主动清空。

### 6.4 新增 Antigravity

字段：

- ID：必填。
- Client ID：必填。
- Client Secret：必填，`type=password`。
- Refresh Token：必填，`type=password`。
- Project：可选；空值表示自动 discovery。
- Auto Onboard：checkbox，默认关闭，并说明它会修改远端账户状态。

### 6.5 编辑 Antigravity

回填：

- ID（readonly）
- Client ID（不是 secret）
- Project
- Auto Onboard

不回填：

- Client Secret
- Refresh Token

标签分别显示：

```text
Client Secret（已设置；留空保留当前值）
Refresh Token（已设置；留空保留当前值）
```

保存规则：

- 空 secret：保留旧值。
- 任一 OAuth 身份字段被非空新值替换：清空 `access_token` 和 `expires_at`。
- OAuth 身份字段变化且 Project 仍等于旧值或未提交时，清空旧 `project`，让下一次 Test 重新 discovery。
- 如果用户在同一次编辑中明确输入了一个不同的新 Project，则保留这个新值，不要求二次编辑。
- 只修改 `auto_onboard` 或 project 时不清空 OAuth secret。

### 6.6 Test

每条凭证独立维护：

```javascript
busy.add(`test:${provider}:${id}`)
testResults.set(`${provider}:${id}`, result)
```

交互：

1. 点击后按钮显示“测试中…”并禁用。
2. 其他凭证仍可操作。
3. 成功结果显示在该行：`成功 · gemini-3.7-flash · 820ms`。
4. 失败结果显示在该行：`失败 · OAuth token refresh failed: 401`。
5. 结果保留到页面刷新，不写入 config 或 DB。

Test 不应修改 credential pool 的 cooldown/disabled 状态；它是诊断动作，不是正常调度请求。

### 6.7 Settings

使用原生 `<details>`，默认折叠：

- Host
- Port
- Auth Token
- Max Retries
- Cooldown
- Database Path
- Upstream Proxy
- Config File（readonly）

低风险第一版可以保留现有 Auth Token round-trip 行为，但 UI 必须使用 `type=password`。更安全的后续改进是：

- `GET /api/config` 返回 `auth_token_set`，不返回真实 token。
- 空 token 表示保留。
- 明确的“清除 Auth Token”checkbox 才能清空。

这一项不得阻塞 credential Edit 修复；如实现会扩大登录兼容风险，拆成后续提交。

### 6.8 Modal 与反馈

统一 Modal 必须包含：

- `role="dialog"`
- `aria-modal="true"`
- 标题 ID 与 `aria-labelledby`
- `role="alert"` / `aria-live="polite"` 的错误区域
- 提交期间 disabled 按钮
- Escape 关闭
- 点击 backdrop 关闭
- 关闭后恢复触发按钮焦点

全局 notice 适合保存、删除和加载；Test 同时需要行内结果。

## 7. 后端契约设计

### 7.1 Create 与 Update 分离

不要让同一个 Pydantic model 同时服务创建和部分更新。

建议模型：

```python
class AIStudioCredCreate(BaseModel):
    id: str
    api_key: str
    project: str = ""
    account: str = ""

class AIStudioCredUpdate(BaseModel):
    api_key: str | None = None
    project: str | None = None
    account: str | None = None

class AntigravityCredCreate(BaseModel):
    id: str
    client_id: str
    client_secret: str
    refresh_token: str
    project: str = ""
    auto_onboard: bool = False

class AntigravityCredUpdate(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    refresh_token: str | None = None
    project: str | None = None
    auto_onboard: bool | None = None
```

规则：

- 路径中的 `cred_id` 是唯一身份；Update body 不包含可变 ID。
- Secret 字段 `None` 或 `""` 都表示保留旧值。
- 非 secret 字段 `None` 表示保留；空字符串表示明确清空。
- Create 对必填字段执行 `.strip()` 后的非空校验。
- OAuth 字段变化时，Project 合并规则为：请求明确提供了不同的新值则采用新值；否则清空旧值并重新 discovery。

### 7.2 Credential list 响应

AI Studio：

```json
{
  "id": "ai-main",
  "kind": "aistudio",
  "api_key_set": true,
  "project": "project-a",
  "account": "user@example.com",
  "state": "active",
  "failure_count": 0,
  "cooldown_remaining": 0
}
```

Antigravity：

```json
{
  "id": "my-agy",
  "kind": "antigravity",
  "client_id": "...apps.googleusercontent.com",
  "client_secret_set": true,
  "refresh_token_set": true,
  "project": "",
  "auto_onboard": false,
  "state": "active",
  "failure_count": 0,
  "cooldown_remaining": 0
}
```

禁止返回：

- API Key 的任何片段。
- Client Secret 的任何片段。
- Refresh Token 的任何片段。
- Access Token。

### 7.3 Test 响应

成功响应增加可观测但不持久化的信息：

```json
{
  "status": "ok",
  "credential_id": "my-agy",
  "provider": "antigravity",
  "model": "antigravity/gemini-3.7-flash",
  "latency_ms": 820
}
```

失败继续使用非 2xx，并保持现有 `error.message`，可附加：

```json
{
  "error": {
    "message": "OAuth token refresh failed: 401",
    "type": "RuntimeError"
  },
  "credential_id": "my-agy",
  "provider": "antigravity",
  "latency_ms": 810
}
```

不要为“错误阶段”新建复杂异常层级；当前 message 已包含 OAuth / project / upstream 语义。只有真实错误仍无法定位时，才考虑结构化 `stage`。

## 8. 前端结构设计

继续使用：

- 一个 `index.html`
- 原生 HTML/CSS/JavaScript
- FastAPI 现有静态响应

建议脚本区顺序：

1. state 与 DOM helper
2. API / auth
3. load / refresh
4. renderHeader / renderStats
5. renderCredentials
6. renderUsage
7. renderSettings
8. Modal
9. credential actions
10. test actions
11. settings actions
12. formatting / escape helper
13. init

必须保留统一 `esc()`，任何 API 数据进入 `innerHTML` 前都经过转义。

删除：

- `.app` flex sidebar 布局。
- `.sidebar*`、`.nav-item*`、`.section.active`。
- `nav()`。
- Credentials tab、`ctab()` 与 hidden provider panel。
- `sidebarFooter`。

新增：

- `<main>` 最大宽度容器。
- 语义化 `<section>`。
- `.toolbar`。
- `.credential-table` 与移动端 `.credential-card` 规则。
- `.status-notice`。
- `.test-result-success` / `.test-result-error`。
- `<details>` Settings。

## 9. 文件级改动清单

### `src/hakimi_proxy/routes/admin.py`

- 分离 Create / Update models。
- Update 合并旧 credential，不再整体覆盖。
- OAuth 字段变化时清理 runtime token/project。
- List 返回 `*_set`，移除 secret 片段。
- Test 返回 latency 和稳定 error type。
- 不改变配置路径、文件权限或 adapter API。

### `src/hakimi_proxy/web/index.html`

- 替换 sidebar/page/tab HTML 与 CSS。
- 改成 EMP 风格的单页 sections。
- 中文化用户可见文案。
- 新统一 Modal 与 busy/error 行为。
- Edit 使用 secret-set 状态和 blank-preserve 语义。
- Test 结果行内显示。
- Settings 改为折叠区。
- 补移动端和 accessibility。

### `tests/test_admin.py`

新增或调整：

- AI Studio 空 API Key update 保留旧 key。
- Antigravity 空 secret update 保留旧值。
- 更新 Client ID/Secret/Refresh Token 清空 access token、expiry、project。
- Create 空必填字段被拒绝。
- List 不包含任何 secret 内容，只包含 `*_set`。
- Test 使用被点击的精确 credential。
- Test 成功/失败包含稳定字段和 latency。
- Web UI 不再含 sidebar/nav/tab，包含单页 sections 与 leave-blank 文案。

### `README.md`

- Web UI 描述从分页导航改为单页控制台。
- 说明 Edit secret 留空保留。
- 说明 `可调度` 不等于远端 Test 成功。

### 不应修改

- `src/hakimi_proxy/adapters/*`，除非现有错误信息不能满足 Test 显示。
- `src/hakimi_proxy/config.py` 的 YAML schema。
- SQLite metering schema。
- `config.yaml` / `config.local.yaml` 中的真实凭证。
- EMP 仓库。

## 10. 分阶段实施与提交顺序

### Commit 1 — `fix(admin): preserve omitted credential secrets`

1. 先写失败测试。
2. 分离 Create / Update models。
3. 实现 blank/omitted secret 保留。
4. 实现 OAuth 变化后的 token/project reset。
5. 运行 `tests/test_admin.py`。

这是最小垂直切片；即使后续 UI 重构取消，也必须保留。

### Commit 2 — `refactor(admin): expose credential set metadata`

1. List 改为 `*_set`。
2. 删除 secret preview。
3. 扩充 Test response 的 latency/error type。
4. 更新 API 测试。

### Commit 3 — `refactor(web): replace paged shell with one page`

1. 删除 sidebar、nav、tabs、hidden sections。
2. 建立 header、stats、credentials、usage、settings sections。
3. 先复用现有 action 函数，确保 CRUD 仍可用。
4. 验证桌面和 375px 布局。

不要在这个提交同时重写后端。

### Commit 4 — `fix(web): make credential editing safe and explicit`

1. Create/Edit Modal 分离语义。
2. 回填安全字段。
3. Secret 输入显示“留空保留”。
4. busy、inline error、focus 管理。
5. 行内 Test result。

### Commit 5 — `docs: document the single-page admin workflow`

1. 更新 README。
2. 全套验证。
3. 对照本计划逐项勾验收标准。

如果用户不要求实际提交 Git，LunaMax 不应主动 stage/commit；上述 commit 仅表示逻辑切片。

## 11. 自动化测试矩阵

| 场景 | 初始状态 | 操作 | 预期 |
|---|---|---|---|
| AI Edit 不换 key | 已有 key | PUT `api_key=""`，改 project | key 保留，project 更新 |
| AI Edit 换 key | 已有 key | PUT 新 key | key 替换 |
| AGY Edit 不换 OAuth | 三项 OAuth 已有 | PUT secret/token 空，改 auto_onboard | OAuth 保留，flag 更新 |
| AGY 换 Client Secret | 已有 access token/project | PUT 新 secret | access token 清空、expiry=0、project 清空 |
| AGY 创建缺字段 | 无 | POST 空 secret | 4xx，配置不写入 |
| List redaction | 配置含假 secret marker | GET credentials | 响应无 marker，`*_set=true` |
| Test 精确选择 | 两条同 provider credential | 点击第二条 Test | mock 只收到第二条 ID |
| Test timeout | mock 抛空 ConnectTimeout | Test | UI/API 显示 `ConnectTimeout` |
| Test upstream error | mock 401/403 | Test | 显示上游 HTTP 状态，不触发本地登录页 |
| HTML shell | 新 UI | GET `/` | 无 sidebar/nav/tab，有全部单页 sections |

完整自动验证：

```bash
UV_CACHE_DIR=/tmp/na2h-uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/na2h-uv-cache uv run python -m compileall -q src tests
git diff --check
```

内联 JavaScript 语法检查继续使用 Node `new Function()` 解析 `<script>` 内容，不新增 npm 依赖。

## 12. 手工验收矩阵

### 桌面

- 1440×900：所有核心 section 在同一页面，内容宽度不过度拉伸。
- 打开 Edit：安全字段有当前值，secret 显示“已设置；留空保留”。
- 不填写 secret 保存：Test 行为不因 Edit 退化。
- Test：按钮进入 busy；成功/失败固定显示在本行。
- Settings：默认折叠，展开后 proxy 可见并可保存。

### 移动端

- 375×812：无页面级横向滚动。
- credential 卡片的 Test/Edit/Delete 均可见且可点击。
- Modal 不超出视口，内容可滚动。
- 软键盘出现时提交按钮仍可通过滚动访问。

### 错误路径

- OAuth `invalid_client`：显示完整可行动错误，不显示空白。
- Proxy ConnectTimeout：显示异常类型。
- 401 本地 Bearer：进入登录视图。
- 上游 401/403：作为 Test 错误显示，不误判为本地登录过期。
- 重复 ID：Modal 保持打开并显示 409 文案。

## 13. 验收标准

全部满足才算实施完成：

- [x] 页面无 sidebar、无 page 切换、无 provider tab。
- [x] Health、统计、两类 Credentials、Usage、Settings 在一个页面。
- [x] AI Studio 与 Antigravity 都能安全部分编辑。
- [x] 不填写 secret 不会修改已有 secret。
- [x] API 响应不包含 secret 片段。
- [x] OAuth 身份变化会清除旧 runtime token/project。
- [x] `可调度` 与 Test 成功/失败分开显示。
- [x] Test 按钮有 busy 状态和行内结果。
- [x] Modal 错误可见、Escape 可关闭、焦点可恢复。
- [ ] 375px 宽度无页面级横向滚动（需实际浏览器验收）。
- [x] 不增加运行或前端依赖。
- [x] 配置 YAML 与 SQLite 无迁移。
- [x] 完整测试、compileall、JavaScript parse、diff check 全部通过。
- [x] 未读取、打印或修改真实 secret 内容。

## 14. LunaMax 执行约束

1. 开始前先读本文件、`task_plan.md`、`findings.md`、`progress.md`。
2. 当前 worktree 已有大量未提交 AGY/测试改动；不得覆盖、还原或格式化无关文件。
3. 先做 Commit 1 的测试驱动安全切片；测试绿后才能改 HTML。
4. 不读取或输出 `config.yaml` / `config.local.yaml` 的 secret。
5. 不对真实上游执行 Test；自动化使用 mock，真实按钮由用户验收。
6. 不引入框架、包管理或新依赖。
7. 每完成一个逻辑切片更新 `progress.md`；发现方案与代码不符时先记录再调整。
8. 不主动 stage、commit 或 push，除非用户另行明确授权。

## 15. 下一步

LunaMax 的第一条行动应当是：

> 在 `tests/test_admin.py` 写出“空 secret 更新保留旧值”和“OAuth 身份变化清除缓存 token/project”两条失败测试，只修改 `routes/admin.py` 让它们通过；此时不碰 `index.html`。

这是整个方向的第一个可证伪证明点，也是最容易单独回退和审查的切片。
