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

## 2. 技术栈

- **后端**：Python 3.8+、Flask
- **数据库**：SQLite（默认 `medical_system.db`）
- **前端**：`static/index.html` + `static/app.js`（无前端构建流程）
- **数据导出**：pandas + openpyxl

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

## 5. 核心功能模块

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

9. **数据查询导出（query-export）**
   - 多维数据查询
   - Excel 导出
   - 数据库备份路径设置、备份列表、恢复

---

## 6. 项目目录结构（当前仓库）

```text
health_agent/
├─ app.py                              # Flask 主程序（路由、数据库初始化、业务逻辑）
├─ launch.py                           # 桌面启动器（自动打开浏览器 + GUI 提示）
├─ requirements.txt                    # Python 依赖
├─ README.md                           # 项目说明（本文件）
├─ medical_system.db                   # SQLite 主库文件（运行后生成/更新）
├─ database_backups/                   # 数据库备份目录
├─ logs/                               # 运行日志目录（app.log / startup.log）
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
- 日志目录：`logs/`
  - `app.log`：应用日志
  - `startup.log`：启动流程日志

> 建议定期备份 `medical_system.db` 及 `database_backups/` 目录。

---

## 8. 常见问题

### 8.1 启动失败 / 页面打不开

请按顺序排查：

1. 是否已安装 Python（建议 3.8+）
2. 是否已安装依赖：`pip install -r requirements.txt`
3. 5000 端口是否被占用
4. 查看错误日志：
   - `error_log.txt`
   - `logs/startup.log`
   - `logs/app.log`

### 8.2 自动安装依赖失败

`launch.py` 会尝试自动安装依赖；若失败，请手动执行：

```bash
python -m pip install -r requirements.txt
```

---

## 9. 开发建议

- 当前为单机 SQLite 架构，适合中小规模本地部署。
- 若需多用户并发或跨机器访问，建议演进：
  - 数据库切换至 MySQL/PostgreSQL
  - 服务端部署至 Linux + Gunicorn/uWSGI + Nginx
  - 增加更细粒度权限与审计策略

