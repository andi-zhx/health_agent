@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 正在安装医疗系统所需依赖...
echo.

python -m pip install -r requirements.txt
if errorlevel 1 (
    echo 使用 python -m pip 失败，尝试 py -m pip ...
    py -m pip install -r requirements.txt
)

echo.
if errorlevel 1 (
    echo 安装失败，请检查：
    echo 1) 是否已安装 Python（建议 3.8+）
    echo 2) 安装 Python 时是否勾选 Add Python to PATH
    echo 3) 网络是否可访问 pip 源
    pause
    exit /b 1
)

echo 依赖安装完成。现在可双击「启动医疗系统.bat」或「启动医疗系统.pyw」启动程序。
echo.
pause
