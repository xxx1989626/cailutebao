@echo off
title 蔡路特保队管理系统-控制台
chcp 936 >nul

:start
cls
echo ======================================================
echo   蔡路特保队队务管理系统 - 正在启动
echo   启动时间: %date% %time%
echo ======================================================

:: 1. 强制清理旧进程，防止端口占用
echo [1/3] 正在清理旧进程...
taskkill /f /t /im nginx.exe >nul 2>&1
taskkill /f /t /im python.exe >nul 2>&1

:: 2. 启动 Nginx (使用 start /d 切换目录启动，保证其能找到配置文件)
echo [2/3] 正在启动 Nginx 代理服务器...
start /d "D:\cailu\nginx-1.28.2" nginx.exe

:: 3. 启动 Flask 后端 (使用 start 让它在独立窗口运行，或者直接运行)
echo [3/3] 正在启动 Python 后端服务...
echo ------------------------------------------------------
echo 提示：请勿直接关闭此窗口，如需停止请按 Ctrl+C
echo ------------------------------------------------------

cd /d "D:\cailu\cailutebao"
python app.py

echo.
echo !!!!!!! 警告：程序意外退出 !!!!!!!
echo 正在尝试重新启动...
timeout /t 5
goto start