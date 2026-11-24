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

- **后端**：64 位 Python 3.10–3.14（推荐 3.12）、Flask 3.x（模块化蓝图结构）
- **数据库**：SQLite（默认 `medical_system.db`）
- **前端**：`static/index.html` + `static/app.js` + `static/theme.css`（无前端构建流程）
- **数据导出**：pandas + openpyxl
- **时区语义**：默认 `Asia/Shanghai`（可通过环境变量 `APP_TIMEZONE` 覆盖）

依赖版本见 `requirements.txt`；包含 Windows 所需的 `tzdata`。无需安装 Node.js、数据库服务器或 C++ 编译工具。

---

## 3. 快速开始（Windows）

1. 安装 [Python](https://www.python.org/downloads/windows/) **64 位 3.10–3.14**，推荐 **3.12**，安装时勾选 **Add Python to PATH**。
2. 将下载的 ZIP **完整解压**到可写目录，例如 `D:\health_agent`；不要直接在压缩包内运行。
3. 双击 **`启动医疗系统.bat`**。首次会自动建立 `.venv` 并下载依赖，请保持联网、等待安装完成。
4. 浏览器自动打开 `http://127.0.0.1:5000`，桌面窗口显示“健康管理系统已启动”。关闭窗口即停止服务。

也可先双击 `安装依赖.bat` 安装，再启动。两个入口都使用项目内同一个 `.venv`，不会把依赖安装到其他 Python 中。`.pyw` 入口同样显示安装/启动控制台，避免错误被隐藏。后续启动无需重复安装；更新依赖清单后会自动重新检查安装。

### 会话密钥

本地首次运行会自动生成随机 `.secret_key` 并保存在数据目录，重启继续使用。**不再需要手动设置 SECRET_KEY 才能打开首页**。该文件已加入 Git 忽略规则，不要分享或提交。已有 `SECRET_KEY` 环境变量时优先使用环境变量，服务器部署仍建议显式配置固定的高强度密钥。

### 手动启动 / macOS / Linux

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe launch.py
# macOS / Linux:
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python launch.py
```

不需要激活虚拟环境，因此不受 PowerShell 执行策略影响。已安装依赖的环境也支持 `python app.py` 或 `python -m flask --app app run`，这些入口都会初始化数据库。

无桌面环境使用：

```bash
python launch.py --no-gui --no-browser --port 5000
```

按 `Ctrl+C` 退出。Tkinter 不可用时启动器自动保持命令行服务运行；启动失败会返回非零退出码，并写入 `error_log.txt`。只有本系统的健康检查通过后才打开浏览器。

### 端口占用

先关闭已运行的系统。也可指定其他端口（PowerShell）：

```powershell
$env:APP_PORT='5050'
.venv\Scripts\python.exe launch.py
```

或者使用 `launch.py --port 5050`。启动器会显示并打开实际使用的端口，不会跳转到占用 5000 端口的其他应用。

### 数据位置与升级

默认沿用项目内的 `medical_system.db`，不会运行清空数据的样本脚本。升级前请备份数据库、附件目录和 `.secret_key`，不要用下载包中的同名数据库覆盖已有数据。

可通过 `HEALTH_AGENT_DATA_DIR` 指定独立的可写数据目录（数据库、附件、日志、密钥及默认备份均放在那里）。指定一个空目录会创建新库，不会自动搬迁旧库；需要继续使用旧数据时，请在停止服务后复制原数据库和附件。

---

## 4. 默认登录

系统启用登录态校验（绝大部分 `/api/*` 需登录）。

- 默认账号：`admin`
- 默认密码：`123456`

已有数据库沿用原账号及密码。系统默认仅监听本机地址。页面右上角支持退出登录；同一浏览器刷新后会恢复有效会话。

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
│  ├─ runtime.py                       # 数据路径与持久化本地密钥
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
├─ launch.py                           # 就绪检测、桌面窗口与服务生命周期
├─ bootstrap.py                        # 建立 .venv 并安装依赖
├─ start.bat                           # Windows 解释器检测入口
├─ tests/test_runtime.py               # 启动、登录、导出与备份回归测试
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
│  ├─ theme.css                        # 工作台、登录页与响应式主题
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

## 9. 常见问题与验证

| 现象 | 处理方法 |
| --- | --- |
| 双击提示找不到 Python | 安装官方 64 位 Python 3.12，勾选 PATH；不要只安装 Microsoft Store 的占位别名。 |
| 旧 Python 3.13/3.14 安装 pandas 失败 | 使用更新后的 requirements.txt 和启动脚本；pandas 已升级到提供对应预编译包的 2.3.3。 |
| 安装下载失败 | 查看窗口内 pip 报错，检查网络及 pip 镜像，再双击安装依赖；不需要盲目安装 C++ 编译器。 |
| `.venv` 来自另一台电脑或旧 Python | 停止服务，重命名或删除 `.venv` 后重试；数据库与附件不在 `.venv` 中。 |
| 首页报错或打不开 | 查看 `error_log.txt`、`logs/startup.log`、`logs/app.log`；确认使用可写目录和空闲端口。 |
| 时区错误 | 确认依赖完整，`APP_TIMEZONE` 使用有效的 IANA 名称，例如 `Asia/Shanghai`。 |
| 自定义备份路径失效 | 在“数据查询导出”中改为当前机器可写的路径。 |

开发回归检查（使用装好依赖的 Python）：

```bash
python -m unittest discover -s tests -v
```

测试在临时目录中覆盖：无环境变量启动、密钥持久化、Windows 时区回退、登录/退出、主要页面 API、客户读写、Excel 下载、备份完整性、已有数据库迁移、端口占用和无桌面启动。不会对工作数据库写入测试数据。

GitHub Actions 工作流 `Startup regression` 在 Windows Python 3.10 / 3.12 / 3.14 和 Linux Python 3.12 上运行，并在 Windows 检查 `start.bat` 安装链路。实际通过状态以 Actions 记录为准。

---

## 10. 开发建议

- 当前为单机 SQLite 架构，适合中小规模本地部署。
- 若需多用户并发或跨机器访问，建议演进：
  - 数据库切换至 MySQL/PostgreSQL
  - 服务端部署至 Linux + Gunicorn/uWSGI + Nginx
  - 增加更细粒度权限与审计策略
