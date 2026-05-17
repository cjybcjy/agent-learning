# MGFS Web Dashboard 设计文档

> 方案: **A — FastAPI + HTMX + Jinja2**
> 目标: 替代 CLI 与飞书推送，成为 MGFS 唯一人机交互界面

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                      Browser (User)                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ 投研视图      │  │ 运维视图      │  │  左侧导航栏       │  │
│  │ · 单票评估    │  │ · 配置中心    │  │                  │  │
│  │ · 生态雷达    │  │ · 实盘流水线  │  │                  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────┘  │
│         │                 │                                  │
│         └────────┬────────┘                                  │
│                  │ HTMX (AJAX + 局部刷新)                     │
└──────────────────┼──────────────────────────────────────────┘
                   │
┌──────────────────┼──────────────────────────────────────────┐
│           FastAPI Web Server (Python)                        │
│  ┌───────────────┴─────────────────────────────────────┐    │
│  │  Router Layer                                        │    │
│  │  /dashboard/*  → HTML 页面 (Jinja2)                  │    │
│  │  /api/eval/*   → REST API (JSON)                     │    │
│  └───────────────┬─────────────────────────────────────┘    │
│                  │                                           │
│  ┌───────────────┼──────────────┐  ┌──────────────────┐    │
│  │  投研服务层    │              │  │  运维服务层       │    │
│  │  EvalService  │              │  │  ConfigService   │    │
│  │  ScanService  │              │  │  PipelineService │    │
│  └───────┬───────┘              │  └────────┬─────────┘    │
│          │                       │           │              │
│          └───────────┬───────────┘           │              │
│                      │                       │              │
│  ┌───────────────────┴───────────────────────┴──────────┐  │
│  │              Core Domain (现有代码, 零修改)             │  │
│  │  MGFSOrchestrator · EcosystemScanner · ConfigLoader   │  │
│  │  MGFSRepository · ArchetypeRouter · ZoneMapper        │  │
│  │  All Plugins (Moat · Valuation · Policy · Timing)     │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

**关键原则:**
- 前端零 JS 框架。所有交互由 HTMX 属性驱动 (`hx-post`, `hx-target`, `hx-swap`, `hx-trigger`)。
- 后端直接复用现有 `MGFSOrchestrator`、`EcosystemScanner`、`MGFSRepository`。不修改核心计分逻辑。
- YAML 配置热加载：编辑 → 校验 → 写入磁盘 → 重新 `build_orchestrator()` → 新请求自动使用新配置。

---

## 2. 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| Web 框架 | FastAPI | 路由、依赖注入、后台任务 (BackgroundTasks) |
| 模板引擎 | Jinja2 | 服务端渲染 HTML 片段 |
| 前端交互 | HTMX 2.x | 通过属性驱动 AJAX，无需手写 JS |
| CSS 框架 | Tailwind CSS (CDN) |  Utility-first，快速布局 |
| 图表 | ECharts (CDN) | 雷达图、柱状图、历史趋势 |
| 图标 | Lucide Icons (CDN) | 轻量图标库 |
| 任务队列 | FastAPI BackgroundTasks + 内存 dict | 扫描进度状态机 |

---

## 3. 路由设计

### 3.1 页面路由 (返回完整 HTML)

| 路由 | 视图 | 说明 |
|------|------|------|
| `GET /` | 重定向 → `/dashboard/research` | 默认进入投研视图 |
| `GET /dashboard/research` | 投研视图 | 包含单票评估舱 + 生态雷达舱 |
| `GET /dashboard/ops` | 运维视图 | 包含配置中心 + 实盘流水线 |

### 3.2 API 路由 (返回 HTML 片段 或 JSON)

| 路由 | 方法 | 返回 | 说明 |
|------|------|------|------|
| `/api/eval/single` | POST | HTML 片段 | 单票评估，返回决策卡片 |
| `/api/eval/share-lark` | POST | JSON | 将指定决策推送至飞书 |
| `/api/scan/start` | POST | JSON `{task_id}` | 启动生态扫描任务 |
| `/api/scan/progress/{task_id}` | GET | HTML 片段 | 查询扫描进度 (轮询) |
| `/api/scan/result/{task_id}` | GET | HTML 片段 | 获取扫描结果矩阵 |
| `/api/config/load/{filename}` | GET | JSON | 加载 YAML 内容 |
| `/api/config/save/{filename}` | POST | JSON | 保存 YAML，触发校验 |
| `/api/config/validate` | POST | JSON | 独立校验 YAML 语法 |
| `/api/pipeline/history` | GET | HTML 片段 | 历史记录列表 |
| `/api/pipeline/export/{batch_id}` | GET | CSV 文件 | 导出 CSV |
| `/api/pipeline/trigger` | POST | JSON | 手动触发大盘巡检 |
| `/api/health` | GET | JSON | 系统健康状态 |

---

## 4. 页面结构

### 4.1 左侧导航栏 (Layout 共享)

```html
<aside class="w-64 bg-slate-900 text-white flex flex-col">
  <div class="p-4 text-xl font-bold">MGFS 投研系统</div>
  <nav class="flex-1">
    <a href="/dashboard/research" class="nav-item active">
      <i data-lucide="line-chart"></i> 投研视图
    </a>
    <a href="/dashboard/ops" class="nav-item">
      <i data-lucide="settings"></i> 运维视图
    </a>
  </nav>
  <div class="p-4 text-xs text-slate-400">
    版本: v1.0 | 分支: company_value_analysis
  </div>
</aside>
```

### 4.2 投研视图 (`/dashboard/research`)

**单票评估舱 (Single Evaluator)**

```html
<section id="single-eval" class="bg-white rounded-lg shadow p-6 mb-6">
  <h2 class="text-lg font-bold mb-4">单票评估</h2>
  <form hx-post="/api/eval/single"
        hx-target="#eval-result"
        hx-swap="innerHTML"
        hx-indicator="#eval-loading">
    <div class="flex gap-4">
      <input name="symbol" placeholder="股票代码 (如 600519)" required
             class="border rounded px-3 py-2 w-48">
      <select name="market" class="border rounded px-3 py-2 w-32">
        <option value="A_SHARE">A股</option>
        <option value="HK">港股</option>
        <option value="US">美股</option>
      </select>
      <select name="policy" class="border rounded px-3 py-2 w-32">
        <option value="neutral">政策: 中性</option>
        <option value="favorable">政策:  favorable</option>
      </select>
      <button type="submit" class="bg-blue-600 text-white px-4 py-2 rounded">
        评估
      </button>
    </div>
  </form>
  <div id="eval-loading" class="htmx-indicator mt-4 text-gray-500">
    评估中...
  </div>
  <div id="eval-result" class="mt-4">
    <!-- HTMX 填充决策卡片 -->
  </div>
</section>
```

**决策卡片 (由 `/api/eval/single` 返回的 HTML 片段)**

直接复用 `build_feishu_card()` 的配色逻辑，渲染为网页卡片：

```html
<div class="rounded-lg border-l-4 p-4" style="border-color: {{ alert_color }}">
  <div class="flex justify-between items-center mb-2">
    <h3 class="text-xl font-bold">{{ rating_emoji }} {{ symbol }} — {{ rating }}</h3>
    <button hx-post="/api/eval/share-lark"
            hx-vals='{"symbol": "{{ symbol }}", "market": "{{ market }}"}'
            class="text-sm bg-green-600 text-white px-3 py-1 rounded">
      一键同步飞书群
    </button>
  </div>
  <div class="grid grid-cols-2 gap-4 text-sm">
    <div>最终得分: <strong>{{ final_score }}</strong></div>
    <div>综合置信度: <strong>{{ overall_confidence }}</strong></div>
    <div>护城河: {{ moat_score }}</div>
    <div>估值: {{ valuation_zone }}</div>
  </div>
  {% if circuit_breakers %}
  <div class="mt-2 text-red-600 text-sm">
    {% for cb in circuit_breakers %}🔴 {{ cb.message }}<br>{% endfor %}
  </div>
  {% endif %}
</div>
```

**生态雷达舱 (Ecosystem Scanner)**

```html
<section id="eco-scan" class="bg-white rounded-lg shadow p-6">
  <h2 class="text-lg font-bold mb-4">生态雷达</h2>
  <form hx-post="/api/scan/start"
        hx-target="#scan-task-id"
        hx-swap="innerHTML"
        hx-on::after-request="startPolling()">
    <div class="flex gap-4 mb-4">
      <select name="theme" required class="border rounded px-3 py-2 w-64">
        <option value="">选择宏观主题...</option>
        <option value="AI_Compute_Infrastructure">AI 算力基建</option>
        <option value="New_Energy_Materials">新能源材料</option>
        <option value="Consumer_Staples">消费必需品</option>
        <option value="Financial_Services">金融服务</option>
        <option value="Advanced_Manufacturing">先进制造</option>
      </select>
      <input name="roles" placeholder="角色过滤 (如 symbiotic_infra)"
             class="border rounded px-3 py-2 w-64">
      <button type="submit" class="bg-blue-600 text-white px-4 py-2 rounded">
        启动扫描
      </button>
    </div>
  </form>

  <!-- 任务 ID 容器 -->
  <div id="scan-task-id" class="hidden"></div>

  <!-- 进度区域 -->
  <div id="scan-progress" class="mt-4 hidden">
    <div class="flex items-center gap-2 text-sm text-gray-600">
      <div class="w-48 bg-gray-200 rounded-full h-2">
        <div id="progress-bar" class="bg-blue-600 h-2 rounded-full transition-all"
             style="width: 0%"></div>
      </div>
      <span id="progress-text">准备中...</span>
    </div>
  </div>

  <!-- 结果矩阵 -->
  <div id="scan-result" class="mt-4">
    <!-- HTMX 轮询填充 -->
  </div>
</section>
```

**前端轮询脚本 (页面底部，唯一的手写 JS)**

```html
<script>
function startPolling() {
  const taskId = document.getElementById('scan-task-id').textContent.trim();
  if (!taskId) return;

  document.getElementById('scan-progress').classList.remove('hidden');

  // HTMX 轮询: 每 2 秒查询进度
  const progressDiv = document.getElementById('scan-progress');
  progressDiv.setAttribute('hx-get', `/api/scan/progress/${taskId}`);
  progressDiv.setAttribute('hx-trigger', 'every 2s');
  progressDiv.setAttribute('hx-target', '#progress-text');
  progressDiv.setAttribute('hx-swap', 'innerHTML');
  htmx.process(progressDiv);

  // 当进度完成时，自动获取结果
  // 由后端在进度响应中返回 hx-trigger 属性控制
}
</script>
```

> **设计决策说明:** 使用 HTMX 轮询 (`hx-trigger="every 2s"`) 而非 WebSocket。原因:
> - 扫描几十只股票耗时 30s–2min，轮询 2s 间隔足够
> - WebSocket 增加连接管理复杂度，对一次性任务没有必要
> - 若未来需要实时推送，可在不改动前端架构的前提下升级

### 4.3 运维视图 (`/dashboard/ops`)

**配置中心 (Config Manager)**

```html
<section class="bg-white rounded-lg shadow p-6 mb-6">
  <h2 class="text-lg font-bold mb-4">配置中心</h2>
  <div class="flex gap-4 mb-4">
    <button hx-get="/api/config/load/moat_static_base.yaml"
            hx-target="#config-editor"
            class="px-3 py-1 border rounded hover:bg-gray-50">
      护城河配置
    </button>
    <button hx-get="/api/config/load/valuation_sector_routing.yaml"
            hx-target="#config-editor"
            class="px-3 py-1 border rounded hover:bg-gray-50">
      估值路由
    </button>
    <button hx-get="/api/config/load/policy_whitelist.yaml"
            hx-target="#config-editor"
            class="px-3 py-1 border rounded hover:bg-gray-50">
      政策白名单
    </button>
    <button hx-get="/api/config/load/ecosystem_themes.yaml"
            hx-target="#config-editor"
            class="px-3 py-1 border rounded hover:bg-gray-50">
      生态主题
    </button>
  </div>

  <form hx-post="/api/config/save"
        hx-target="#config-status"
        hx-swap="innerHTML">
    <input type="hidden" name="filename" id="config-filename" value="">
    <textarea name="content" id="config-editor" rows="20"
              class="w-full font-mono text-sm border rounded p-3 bg-slate-50"></textarea>
    <div class="flex gap-4 mt-4">
      <button type="button"
              hx-post="/api/config/validate"
              hx-include="[name='content']"
              hx-target="#config-status"
              class="px-4 py-2 border rounded hover:bg-gray-50">
        🔍 预校验
      </button>
      <button type="submit"
              class="bg-blue-600 text-white px-4 py-2 rounded">
        💾 保存并热加载
      </button>
    </div>
  </form>

  <div id="config-status" class="mt-4"></div>
</section>
```

**配置校验与热加载流程:**

```
用户点击"保存"
    │
    ▼
POST /api/config/save
    │
    ├── Step 1: YAML 语法校验 (yaml.safe_load)
    │   └── 失败 → 返回红色错误提示，不写入磁盘
    │
    ├── Step 2: Schema 校验 (检查必填字段、分数范围 0-100、权重和为 1)
    │   └── 失败 → 返回黄色警告 + 具体错误位置
    │
    ├── Step 3: 备份旧文件 (文件名 + .backup.YYYYMMDD_HHMMSS)
    │
    ├── Step 4: 写入新文件
    │
    └── Step 5: 热加载
        └── 调用 build_orchestrator() 重建内存中的 orchestrator
        └── 返回绿色成功提示: "配置已更新，新请求自动生效"
```

**实盘流水线 (Pipeline Monitor)**

```html
<section class="bg-white rounded-lg shadow p-6">
  <h2 class="text-lg font-bold mb-4">实盘流水线</h2>

  <div class="flex justify-between items-center mb-4">
    <div class="flex gap-2">
      <button hx-post="/api/pipeline/trigger"
              hx-target="#pipeline-status"
              class="bg-green-600 text-white px-4 py-2 rounded">
        ▶ 立即执行大盘巡检
      </button>
    </div>
    <div id="pipeline-status"></div>
  </div>

  <table class="w-full text-sm">
    <thead class="bg-gray-100">
      <tr>
        <th class="p-2 text-left">批次 ID</th>
        <th class="p-2 text-left">时间</th>
        <th class="p-2 text-left">标的数</th>
        <th class="p-2 text-left">Strong Buy</th>
        <th class="p-2 text-left">操作</th>
      </tr>
    </thead>
    <tbody hx-get="/api/pipeline/history"
           hx-trigger="load, every 30s"
           hx-swap="innerHTML">
      <!-- HTMX 自动填充 -->
    </tbody>
  </table>
</section>
```

---

## 5. 异步扫描进度机制 (轮询方案)

### 5.1 为什么选轮询而非 WebSocket

| 维度 | HTMX 轮询 | WebSocket |
|------|-----------|-----------|
| 复杂度 | 低 (属性驱动) | 高 (连接管理 + 心跳) |
| 适用场景 | 一次性任务 (30s–2min) | 实时数据流 (持续推送) |
| 服务器资源 | HTTP 短连接，无状态 | 长连接，需维护状态 |
| 扩展性 | 可随时升级至 SSE/WS | 架构锁定 |

**结论:** 生态扫描是一次性批处理任务，轮询足够。若未来需要实时监控行情，可增量引入 SSE。

### 5.2 扫描任务状态机

```python
class ScanTaskStatus(Enum):
    PENDING = "pending"      # 任务已创建，未开始
    RUNNING = "running"      # 正在评估
    COMPLETED = "completed"  # 完成，结果就绪
    FAILED = "failed"        # 异常终止

# 内存存储 (进程级，重启丢失 — 可接受)
_scan_tasks: dict[str, dict] = {}
```

### 5.3 后端任务执行流程

```python
@app.post("/api/scan/start")
async def start_scan(request: ScanRequest, background: BackgroundTasks):
    task_id = str(uuid.uuid4())[:8]
    _scan_tasks[task_id] = {
        "status": ScanTaskStatus.PENDING,
        "total": 0,
        "completed": 0,
        "reports": [],
        "error": None,
    }
    # 后台执行，立即返回 task_id
    background.add_task(_run_scan, task_id, request)
    return {"task_id": task_id}


def _run_scan(task_id: str, request: ScanRequest):
    _scan_tasks[task_id]["status"] = ScanTaskStatus.RUNNING
    try:
        scanner = EcosystemScanner(orchestrator, moat_config_path)
        candidates = scanner._get_candidates_by_theme(request.theme)
        _scan_tasks[task_id]["total"] = len(candidates)

        reports = []
        for i, target in enumerate(candidates):
            report = orchestrator.evaluate(target, policy_rating=request.policy)
            reports.append(report)
            _scan_tasks[task_id]["completed"] = i + 1
            # 让出 GIL，使进度查询能及时响应
            time.sleep(0.01)

        # 过滤 + 排序
        filtered = _apply_filters(reports, request)
        _scan_tasks[task_id]["reports"] = filtered
        _scan_tasks[task_id]["status"] = ScanTaskStatus.COMPLETED
    except Exception as e:
        _scan_tasks[task_id]["status"] = ScanTaskStatus.FAILED
        _scan_tasks[task_id]["error"] = str(e)
```

### 5.4 前端轮询协议

**进度查询响应** (`GET /api/scan/progress/{task_id}`)

```html
<!-- 进行中 -->
<div>
  评估中: {{ completed }} / {{ total }}
  <script>
    document.getElementById('progress-bar').style.width = '{{ percent }}%';
    // 若已完成，自动触发结果加载
    {% if status == 'completed' %}
    htmx.ajax('GET', '/api/scan/result/{{ task_id }}', '#scan-result');
    {% endif %}
  </script>
</div>
```

**结果矩阵响应** (`GET /api/scan/result/{task_id}`)

复用 `build_ecosystem_scan_report()` 的配色逻辑，渲染为网页表格:

```html
<table class="w-full text-sm">
  <thead>
    <tr class="bg-gray-100">
      <th>代码</th><th>名称</th><th>角色</th><th>护城河</th>
      <th>估值分位</th><th>最终得分</th><th>评级</th><th>建议</th>
    </tr>
  </thead>
  <tbody>
    {% for r in reports %}
    <tr class="border-b hover:bg-gray-50">
      <td class="p-2 font-mono">{{ r.target.symbol }}</td>
      <td class="p-2">{{ r.target.name }}</td>
      <td class="p-2">{{ role_emoji }} {{ role_label }}</td>
      <td class="p-2">{{ r.factor_scores.moat.score }}</td>
      <td class="p-2">{{ zone_emoji }} {{ zone }}</td>
      <td class="p-2 font-bold">{{ r.final_score }}</td>
      <td class="p-2">{{ rating_badge }}</td>
      <td class="p-2 text-xs">{{ r.action }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
```

---

## 6. YAML 配置安全校验

### 6.1 校验规则

```python
class ConfigValidator:
    @staticmethod
    def validate_moat_yaml(content: str) -> tuple[bool, list[str]]:
        """Return (is_valid, error_messages)."""
        errors = []
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            return False, [f"YAML 语法错误: {e}"]

        # 规则 1: 版本号存在
        if not data.get("version"):
            errors.append("缺少 version 字段")

        # 规则 2: companies 存在且为 dict
        companies = data.get("companies", {})
        if not isinstance(companies, dict):
            errors.append("companies 必须是字典")
            return False, errors

        # 规则 3: 每个公司的 base_score 维度分数在 0-100
        for symbol, cfg in companies.items():
            base_score = cfg.get("base_score", {})
            for dim, item in base_score.items():
                score = item.get("score") if isinstance(item, dict) else None
                if score is not None and not (0 <= score <= 100):
                    errors.append(f"{symbol}.{dim}.score = {score} 超出 [0, 100] 范围")

        # 规则 4: scoring_weights 权重和检查
        weights = data.get("scoring_weights", {})
        total = sum(w.get("weight", 0) for w in weights.values())
        if total > 0 and abs(total - 1.0) > 0.01:
            errors.append(f"scoring_weights 总和 = {total:.2f}，建议归一化为 1.0")

        return len(errors) == 0, errors
```

### 6.2 热加载机制

```python
@app.post("/api/config/save")
async def save_config(request: ConfigSaveRequest):
    # 1. 校验
    is_valid, errors = ConfigValidator.validate(request.filename, request.content)
    if not is_valid:
        return HTMLResponse(f"<div class='text-red-600'>❌ 校验失败:<br>{'<br>'.join(errors)}</div>")

    # 2. 备份
    config_path = settings.resolved_config_dir / request.filename
    backup_name = f"{request.filename}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(config_path, config_path.parent / backup_name)

    # 3. 写入
    config_path.write_text(request.content, encoding="utf-8")

    # 4. 热加载 — 重建 orchestrator
    global _orchestrator
    config = load_mgfs_config(settings.resolved_config_dir / "mgfs_config.yaml")
    _orchestrator = build_orchestrator(config, config_dir=settings.resolved_config_dir)

    return HTMLResponse("<div class='text-green-600'>✅ 配置已保存并热加载，新请求自动生效</div>")
```

---

## 7. 与现有系统的集成点

| 现有组件 | Web Dashboard 中的使用方式 | 是否需要修改 |
|---------|------------------------|-----------|
| `MGFSOrchestrator` | `/api/eval/single` 直接调用 `evaluate()` | 否 |
| `EcosystemScanner` | `/api/scan/start` 后台任务调用 `scan_theme()` | 否 |
| `MGFSRepository` | `/api/pipeline/history` 查询历史记录 | 否 |
| `build_feishu_card()` | 卡片配色逻辑复用到网页卡片模板 | 否 (复用配色映射) |
| `build_ecosystem_scan_report()` | 结果矩阵复用角色 emoji / 标签映射 | 否 (复用映射) |
| `ConfigLoader` | `/api/config/save` 后调用 `build_orchestrator()` 热加载 | 否 |
| `main.py` CLI | **废弃** — 功能迁移至 Web | 保留但不维护 |
| `publishers/` 飞书 | **降级为可选功能** — Web 中提供"一键同步飞书群"按钮 | 否 |

---

## 8. 部署架构

```
开发环境:
    uvicorn sentinel.web.main:app --reload --port 8000

生产环境:
    gunicorn sentinel.web.main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
    
反向代理 (Nginx):
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
    }
```

---

## 9. 文件清单 (新增)

```
sentinel/
└── web/
    ├── __init__.py
    ├── main.py              # FastAPI app + 路由注册
    ├── dependencies.py      # 全局 orchestrator / scanner / repository 单例
    ├── routers/
    │   ├── __init__.py
    │   ├── research.py      # 投研视图 API (/api/eval/*, /api/scan/*)
    │   ├── ops.py           # 运维视图 API (/api/config/*, /api/pipeline/*)
    │   └── health.py        # 健康检查
    ├── services/
    │   ├── __init__.py
    │   ├── eval_service.py  # 单票评估服务封装
    │   ├── scan_service.py  # 扫描任务管理 + 状态机
    │   ├── config_service.py # YAML 读写 + 校验 + 热加载
    │   └── pipeline_service.py # 历史记录查询 + CSV 导出
    └── templates/
        ├── base.html          # 共享布局 (左侧导航 + CSS/JS CDN)
        ├── research.html      # 投研视图页面
        ├── ops.html           # 运维视图页面
        ├── partials/
        │   ├── decision_card.html    # 单票评估结果卡片
        │   ├── scan_progress.html    # 扫描进度条
        │   ├── scan_matrix.html      # 扫描结果矩阵
        │   ├── config_editor.html    # 配置编辑器
        │   ├── pipeline_history.html # 历史记录表格
        │   └── health_status.html    # 系统健康状态
        └── components/
            ├── nav_item.html  # 导航项
            └── alert_badge.html # 评级徽章
```

---

## 10. 安全与权限 (MVP 阶段简化)

- **认证:** MVP 阶段使用 HTTP Basic Auth (Nginx 层配置)，不内置用户系统。
- **授权:** 投研视图全员可访问；运维视图限制为技术团队 (通过 Nginx location 规则或简单 IP 白名单)。
- **输入校验:** 所有用户输入通过 Pydantic 模型校验；YAML 内容通过自定义校验器。
- **备份:** 每次保存配置自动备份，保留最近 20 个版本。

---

## 11. 后续可扩展方向

1. **实时行情接入:** 引入 WebSocket/SSE 推送实时股价，MA60 和 bias 自动刷新。
2. **图表增强:** ECharts 绘制个股估值历史分位图、护城河雷达图。
3. **报告导出:** PDF/Excel 格式的投研报告生成。
4. **用户系统:** 基于 JWT 的登录系统，支持评估记录个人化。
5. **移动端适配:** Tailwind 响应式断点，手机端可用。
