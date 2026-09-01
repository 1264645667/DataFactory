@echo off
chcp 65001
echo 启动 Celery Worker 和 Beat...
echo.

cd /d d:\working_file\DataFactory\backend

echo [1/2] 启动 Celery Worker (窗口1)...
start "Celery Worker" cmd /k ".venv\Scripts\python -m celery -A app.celery_app worker -l info -Q high,normal,low"

timeout /t 3 /nobreak >nul

echo [2/2] 启动 Celery Beat (窗口2)...
start "Celery Beat" cmd /k ".venv\Scripts\python -m celery -A app.celery_app beat -l info"

echo.
echo 启动完成！请查看两个新窗口确认状态。
echo 心跳检测: 每30秒执行一次
echo 定时同步: 每天凌晨 02:00
echo.
pause
