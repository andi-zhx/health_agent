@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 直接在本窗口运行 python，方便看到报错；启动成功后会有弹窗，可最小化本窗口
python "%~dp0launch.py"

REM 若启动失败或用户关闭弹窗后，停留以便查看错误信息
if errorlevel 1 (
    echo.
    echo 若上方有报错，请根据提示处理。也可查看同目录下 error_log.txt
    if exist "%~dp0error_log.txt" type "%~dp0error_log.txt"
    echo.
    pause
)
