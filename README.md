# 健康管理系统（本地部署版）

一个基于 **Flask + SQLite + 原生 HTML/JS** 的单机健康管理系统，适用于诊所、康复中心、理疗门店等场景。  
项目无需 Node.js/NPM，安装 Python 依赖后即可运行。

---

## 1. 项目定位

本系统围绕“客户建档 → 健康评估 → 预约服务 → 仪器使用 → 满意度回访 → 查询导出/备份恢复”形成闭环，支持：

- 客户档案与健康评估档案沉淀
- 门店预约与上门预约管理
- 仪器使用记录与统计分析
- 首页经营看板（趋势、Top10、满意度、活跃度）
- 数据导出（Excel）与数据库备份/恢复
- 登录鉴权、操作日志、系统设置

---

## 2. 技术栈与运行环境

- **后端**：Python 3.8+、Flask 3.x（模块化蓝图结构）
- **数据库**：SQLite（默认 `medical_system.db`）
- **前端**：`static/index.html` + `static/app.js`（无前端构建流程）
- **数据导出**：pandas + openpyxl
- **时区语义**：默认 `Asia/Shanghai`（可通过环境变量 `APP_TIMEZONE` 覆盖）

依赖见 `requirements.txt`：

```txt
Flask==3.0.0
pandas==2.1.4
openpyxl==3.1.2
Werkzeug==3.0.1
```

---

## 3. 快速开始

### 3.1 安装依赖

在项目根目录执行：

```bash
pip install -r requirements.txt
```

> Windows 用户也可双击 `安装依赖.bat`。

### 3.2 启动方式

> ⚠️ 安全要求：启动前必须设置环境变量 `SECRET_KEY`。  
> 若未设置，`app.py` 会在启动时直接报错并退出（不提供默认值）。

#### 先设置 SECRET_KEY（必做）

`SECRET_KEY` 用于 Flask 会话签名，建议使用足够随机的长字符串（至少 32 字符）。

- Linux/macOS（临时生效）：

```bash
export SECRET_KEY='请替换为高强度随机字符串'
python app.py
```

- Windows PowerShell（当前会话生效）：

```powershell
$env:SECRET_KEY='请替换为高强度随机字符串'
python app.py
```

- Windows CMD（当前窗口生效）：

```cmd
set SECRET_KEY=请替换为高强度随机字符串
python app.py
```

#### 方式 A（推荐，桌面体验）

- 双击 `启动医疗系统.bat`
- 或双击 `启动医疗系统.pyw`

启动后会调用 `launch.py`：

- 自动初始化数据库
- 自动尝试打开浏览器 `http://127.0.0.1:5000`
- 弹出桌面提示窗口（关闭窗口即停止服务）

#### 方式 B（命令行）

```bash
python app.py
```

然后浏览器访问：

- `http://127.0.0.1:5000`
- 或 `http://localhost:5000`

---

## 4. 默认登录

系统启用登录态校验（绝大部分 `/api/*` 需登录）。

- 默认账号：`admin`
- 默认密码：`123456`

请在首次登录后尽快修改默认密码（可通过系统设置相关功能维护）。

---

## 5. 核心功能模块（按现有代码）

根据当前代码与前端页面结构，主要模块如下：

1. **首页看板（home）**
   - 客户总数、今日预约
   - 最近 7 天预约趋势
   - 设备使用统计 Top10（支持按日期区间）
   - 满意度与活跃度摘要

2. **客户档案（customers）**
   - 客户新增、编辑、列表查询

3. **健康档案（health）**
   - 健康评估信息录入与管理
   - 覆盖基础信息、生活方式、慢病/风险相关字段

4. **健康画像（portrait）**
   - 按健康记录聚合展示画像与统计

5. **预约服务（appointments）**
   - 门店预约
   - 时段冲突与资源校验

6. **上门预约（home-appointments）**
   - 上门服务预约管理
   - 支持项目、人员等关联选择

7. **仪器使用（usage）**
   - 设备使用记录
   - 支持统计分析

8. **满意度（surveys）**
   - 服务/设备/环境/人员/综合维度评分与反馈

9. **服务改进追踪（service-improvement）**
   - 服务前状态、服务内容、服务后评价
   - 改善状态与回访计划
   - 关联附件上传记录

10. **数据查询导出（query-export）**
   - 多维数据查询
   - Excel 导出
   - 数据库备份路径设置、备份列表、恢复

---

## 6. 项目目录结构（当前仓库）

```text
health_agent/
├─ app.py                              # Flask 入口（创建应用、注册蓝图）
├─ backend/
│  ├─ core.py                          # 数据库初始化、通用钩子、中间逻辑
│  └─ api/
│     ├─ auth.py                       # 登录与密码更新
│     ├─ customers.py                  # 客户档案接口
│     ├─ health_assessments.py         # 健康评估接口
│     ├─ appointments.py               # 门店预约接口
│     ├─ home_appointments.py          # 上门预约接口
│     ├─ improvement_records.py        # 服务改进记录接口
│     ├─ dashboard.py                  # 首页看板接口
│     ├─ system.py                     # 设备/项目/人员与系统配置接口
│     ├─ system_misc.py                # 其他系统接口（备份等）
│     ├─ export.py                     # 导出接口
│     └─ audit_logs.py                 # 审计日志接口
├─ launch.py                           # 桌面启动器（自动打开浏览器 + GUI 提示）
├─ seed_sample_data.py                 # 清理旧业务数据并生成 50 位客户全链路样本
├─ requirements.txt                    # Python 依赖
├─ README.md                           # 项目说明（本文件）
├─ medical_system.db                   # SQLite 主库文件（运行后生成/更新）
├─ database_backups/                   # 数据库备份目录
├─ exports/                            # Excel 导出目录（运行时自动创建）
├─ logs/                               # 运行日志目录（app.log / startup.log）
├─ uploads/                            # 服务改进记录附件目录（运行时自动创建）
├─ error_log.txt                       # 启动异常日志
├─ static/
│  ├─ index.html                       # 单页应用页面结构
│  ├─ app.js                           # 前端交互逻辑（API 调用、页面渲染）
│  └─ images/
│     ├─ login-bg.svg
│     └─ login-bg-house.svg
├─ 安装依赖.bat                        # Windows 一键安装依赖
├─ 启动医疗系统.bat                    # Windows 一键启动（有控制台）
└─ 启动医疗系统.pyw                    # Windows 一键启动（无控制台）
```

---

## 7. 运行与数据说明

- 默认数据库文件：`medical_system.db`
- 导出目录：`exports/`（程序启动时自动创建）
- 备份目录：默认 `database_backups/`，可在系统中修改备份路径
- 上传目录：`uploads/`（按客户与记录自动分目录保存）
- 日志目录：`logs/`
  - `app.log`：应用日志
  - `startup.log`：启动流程日志

> 建议定期备份 `medical_system.db` 及 `database_backups/` 目录。

---

## 8. 生成测试样本数据（50位客户，全链路覆盖）

为便于联调和功能测试，项目内置脚本 `seed_sample_data.py`，会基于 `backend/core.py` 的最新数据结构执行：

1. 清理历史业务数据（客户、健康评估、健康记录、到访签到、门店预约、上门预约、服务改进、改进附件等）；
2. 重新生成 **50 位客户** 的完整测试样本；
3. 确保每位客户均具备以下业务数据：
   - 预约服务记录（`appointments`）
   - 上门服务记录（`home_appointments`）
   - 理疗/服务改进记录（`service_improvement_records`）
   - 健康评估、健康记录、签到及附件记录等。

脚本执行前会自动调用 `init_db()`，确保基础主数据（`therapy_projects`、`equipment`、`staff`）已初始化；若基础数据缺失会直接报错提醒。

执行命令：

```bash
python seed_sample_data.py
```

脚本会输出各业务表最终记录数，便于快速校验。

> 字段说明：`customers` 表已移除 `email` 字段，样本脚本仅写入手机号等联系方式。

> 提示：脚本会清空业务数据表，请勿在生产环境直接执行。

> 说明：为避免代码评审平台对二进制文件的限制，建议仅提交脚本与文档，不提交 `medical_system.db` 的二进制差异；开发/测试环境请本地执行上述命令生成样本数据。

---

## 9. 常见问题

### 9.1 启动失败 / 页面打不开

请按顺序排查：

1. 是否已安装 Python（建议 3.8+）
2. 是否已安装依赖：`pip install -r requirements.txt`
3. 5000 端口是否被占用
4. 查看错误日志：
   - `error_log.txt`
   - `logs/startup.log`
   - `logs/app.log`

### 9.2 自动安装依赖失败

`launch.py` 会尝试自动安装依赖；若失败，请手动执行：

```bash
python -m pip install -r requirements.txt
```

---

## 10. 开发建议

- 当前为单机 SQLite 架构，适合中小规模本地部署。
- 若需多用户并发或跨机器访问，建议演进：
  - 数据库切换至 MySQL/PostgreSQL
  - 服务端部署至 Linux + Gunicorn/uWSGI + Nginx
  - 增加更细粒度权限与审计策略

---

## 附录：为 `trade_agent`（贸促经贸企业信息管理平台）创建独立环境

如果你需要在本机为另一个项目 `https://github.com/andi-zhx/trade_agent` 准备隔离环境，可直接执行：

```bash
bash scripts/setup_trade_agent_env.sh
```

默认会尝试把项目放到 `/workspace/projects/trade_agent` 并创建 `.venv`。你也可以传入自定义目录：

```bash
bash scripts/setup_trade_agent_env.sh /your/custom/path/trade_agent
```

> 若当前网络无法访问 GitHub，脚本会先创建目录和虚拟环境，后续网络恢复后再手动 `git clone` 即可。
