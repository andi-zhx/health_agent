# health-agent 项目云服务器自动化部署脚本使用说明

本说明文档旨在指导您如何在 Ubuntu 云服务器上使用 `deploy.sh` 脚本自动化部署 `health-agent` 项目。该脚本将帮助您完成环境初始化、项目代码克隆、Python 虚拟环境配置、Gunicorn 进程守护以及 Nginx 反向代理的设置，从而实现项目的稳定运行和外部访问。

## 1. 部署架构

本部署方案采用行业标准的 **Ubuntu + Gunicorn + Nginx** 架构：

*   **Ubuntu Server**：作为操作系统，提供稳定可靠的运行环境。
*   **Gunicorn**：一个 Python WSGI HTTP 服务器，用于运行 Flask 应用，处理并发请求。
*   **Nginx**：一个高性能的 Web 服务器和反向代理服务器，负责接收外部请求，转发给 Gunicorn，并提供静态文件服务和 SSL 终止。
*   **Systemd**：Linux 系统和服务管理器，用于管理 Gunicorn 进程，确保其自动启动和恢复。

## 2. 前提条件

在运行部署脚本之前，请确保满足以下条件：

*   **云服务器**：一台已购买并运行 **Ubuntu Server 22.04 LTS 或更高版本** 的云服务器（如阿里云 ECS、腾讯云 CVM、华为云 ECS 等）。
*   **SSH 访问**：您可以通过 SSH 客户端（如 PuTTY、Xshell、终端等）登录到您的云服务器。
*   **域名（可选）**：如果您希望通过域名访问您的应用并配置 HTTPS，请确保您已拥有一个域名，并将其 DNS 解析指向您的云服务器的公网 IP 地址。
*   **Git 仓库**：`health-agent` 项目的代码已托管在 GitHub 仓库：`https://github.com/andi-zhx/health-agent.git`。

## 3. 脚本配置

在运行 `deploy.sh` 脚本之前，您可能需要根据您的实际情况修改脚本中的一些配置变量。请使用文本编辑器（如 `nano` 或 `vim`）打开 `deploy.sh` 文件进行修改。

```bash
# --- 配置变量 --- START ---
PROJECT_NAME="health-agent"
PROJECT_DIR="/var/www/${PROJECT_NAME}"
GIT_REPO="https://github.com/andi-zhx/health-agent.git"
PYTHON_VERSION="python3.10" # 根据您的Ubuntu版本调整，通常是python3.10或python3.11

# Gunicorn 配置
GUNICORN_WORKERS=3 # 建议根据服务器CPU核心数调整，通常为 2 * CPU_CORES + 1
GUNICORN_BIND="127.0.0.1:5000"

# Nginx 配置
SERVER_NAME="_" # 您的服务器IP或域名，例如：your_domain.com 或 192.168.1.1。'_' 表示匹配所有请求。
# --- 配置变量 --- END ---
```

*   **`PROJECT_NAME`**：项目名称，默认为 `health-agent`。这将作为项目目录名和 Systemd 服务名。
*   **`PROJECT_DIR`**：项目在服务器上的部署路径，默认为 `/var/www/health-agent`。
*   **`GIT_REPO`**：项目的 Git 仓库地址。如果您将项目迁移到自己的私有仓库，请务必更新此项。
*   **`PYTHON_VERSION`**：服务器上安装的 Python 版本。通常 Ubuntu 22.04 默认是 `python3.10`，Ubuntu 24.04 可能是 `python3.12`。请根据您的系统版本进行确认。
*   **`GUNICORN_WORKERS`**：Gunicorn 工作进程数。建议设置为 `2 * CPU核心数 + 1`，以充分利用服务器资源并提高并发处理能力。
*   **`GUNICORN_BIND`**：Gunicorn 监听的地址和端口。默认为 `127.0.0.1:5000`，表示只监听本地回环地址，由 Nginx 进行反向代理。
*   **`SERVER_NAME`**：Nginx `server_name` 配置项。如果您使用域名访问，请将其替换为您的域名（例如 `your_domain.com`）。如果您只使用服务器 IP 访问，可以保持 `_`，或者替换为您的服务器公网 IP。

## 4. 运行部署脚本

1.  **上传脚本**：将 `deploy.sh` 文件上传到您的 Ubuntu 云服务器的任意目录，例如您的用户主目录 (`/home/ubuntu/`)。

2.  **添加执行权限**：通过 SSH 登录服务器后，为脚本添加执行权限：
    ```bash
    chmod +x deploy.sh
    ```

3.  **运行脚本**：使用 `sudo` 权限运行脚本。脚本执行过程中会输出详细的日志信息。
    ```bash
    sudo ./deploy.sh
    ```

    *   脚本将自动执行以下操作：
        *   更新系统软件包并安装必要的依赖（Python 虚拟环境、pip、Nginx、Git、curl）。
        *   克隆 `health-agent` 项目代码到指定目录 (`/var/www/health-agent`)。
        *   创建 Python 虚拟环境，并安装项目 `requirements.txt` 中列出的所有依赖，以及 `gunicorn`。
        *   配置并启动 `health-agent` 的 Gunicorn Systemd 服务，并设置开机自启。
        *   配置 Nginx 反向代理，将外部 80 端口请求转发到 Gunicorn，并配置静态文件服务。
        *   如果服务器上安装了 UFW 防火墙，将自动允许 Nginx HTTP 流量。

4.  **验证部署**：脚本运行完成后，您可以通过浏览器访问您的服务器公网 IP 地址或您配置的域名，应该能看到 `health-agent` 应用的界面。

## 5. 后续操作与维护

### 5.1 检查服务状态

*   **Gunicorn 服务**：
    ```bash
    sudo systemctl status health-agent
    ```
*   **Nginx 服务**：
    ```bash
    sudo systemctl status nginx
    ```

### 5.2 查看日志

*   **Gunicorn 应用日志**：
    ```bash
    sudo journalctl -u health-agent -f
    ```
*   **Nginx 访问日志**：
    ```bash
    sudo tail -f /var/log/nginx/access.log
    ```
*   **Nginx 错误日志**：
    ```bash
    sudo tail -f /var/log/nginx/error.log
    ```

### 5.3 配置 HTTPS (强烈推荐)

为了数据传输安全，强烈建议为您的网站配置 HTTPS。这通常通过 Let's Encrypt 和 Certbot 工具实现。在成功部署并能通过域名访问您的应用后，执行以下步骤：

1.  **安装 Certbot**：
    ```bash
    sudo snap install core
    sudo snap refresh core
    sudo snap install --classic certbot
    sudo ln -s /snap/bin/certbot /usr/bin/certbot
    ```
2.  **获取并安装 SSL 证书**：
    ```bash
    sudo certbot --nginx -d 您的域名
    ```
    Certbot 会自动修改 Nginx 配置，为您获取并安装 SSL 证书，并设置自动续期。请将 `您的域名` 替换为您的实际域名。

### 5.4 更新项目代码

如果 `health-agent` 项目代码有更新，您可以通过以下步骤进行更新和重启：

1.  **进入项目目录**：
    ```bash
    cd /var/www/health-agent
    ```
2.  **拉取最新代码**：
    ```bash
    git pull
    ```
3.  **重新安装依赖（如果 `requirements.txt` 有变化）**：
    ```bash
    source venv/bin/activate
    pip install -r requirements.txt
    deactivate
    ```
4.  **重启 Gunicorn 服务**：
    ```bash
    sudo systemctl restart health-agent
    ```

## 6. 故障排除

*   **服务无法启动**：
    *   检查 Systemd 服务日志：`sudo journalctl -u health-agent`。
    *   检查 Nginx 错误日志：`sudo tail -f /var/log/nginx/error.log`。
    *   确保 Gunicorn 监听的端口没有被其他进程占用。
*   **无法通过浏览器访问**：
    *   检查服务器安全组/防火墙设置，确保 80 端口（和 443 端口，如果配置了 HTTPS）已对外开放。
    *   检查 Nginx 配置语法：`sudo nginx -t`。
    *   确保 `SERVER_NAME` 配置正确，并且域名解析已生效。

## 7. 注意事项

*   本脚本默认使用 `$(logname)` 作为 Gunicorn 服务的运行用户。请确保该用户具有对项目目录的读写权限。
*   `medical_system.db` 数据库文件将存储在项目目录下 (`/var/www/health-agent/medical_system.db`)。请确保定期备份此文件以防止数据丢失。
*   对于生产环境，建议进一步加强安全措施，例如限制 SSH 登录、使用密钥认证、配置更严格的防火墙规则等。

---
