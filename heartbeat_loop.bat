@echo off
chcp 65001
title DataForge - 心跳检测循环 (30秒间隔)
echo 每30秒触发一次心跳检测任务...
echo 按 Ctrl+C 停止
echo.

:loop
cd /d d:\working_file\DataFactory\backend
.venv\Scripts\python -c "from app.celery_app import celery_app; celery_app.send_task('tasks.heartbeat_check'); print('心跳任务已发送 %time%')"

timeout /t 30 /nobreak >nul
goto loop
