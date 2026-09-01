@echo off
chcp 65001
title DataForge - 启动所有服务
echo ==========================================
echo DataForge 服务启动脚本
echo ==========================================
echo.

cd /d d:\working_file\DataFactory\backend

echo [1/4] 检查 Redis 连接...
.venv\Scripts\python -c "import redis; r = redis.from_url('redis://:baiwang@172.28.31.239:6379/3'); r.ping(); print('  Redis 连接成功')" || (
    echo   Redis 连接失败，请检查配置！
    pause
    exit /b 1
)

echo [2/4] 检查 MySQL 连接...
.venv\Scripts\python -c "
import pymysql
try:
    conn = pymysql.connect(host='172.28.30.59', port=3306, user='popsicle', password='QY20Lsf%!PLfM25Ts!', database='data_factory')
    print('  MySQL 连接成功')
    conn.close()
except Exception as e:
    print(f'  MySQL 连接失败: {e}')
" || (
    echo   MySQL 连接失败，请检查配置！
    pause
    exit /b 1
)

echo [3/4] 启动 Celery Worker（新窗口）...
start "Celery Worker" cmd /k "cd /d d:\working_file\DataFactory\backend && .venv\Scripts\python -m celery -A app.celery_app worker -l info -Q high,normal,low"

timeout /t 2 /nobreak >nul

echo [4/4] 启动 Celery Beat（新窗口）...
start "Celery Beat" cmd /k "cd /d d:\working_file\DataFactory\backend && .venv\Scripts\python -m celery -A app.celery_app beat -l info"

echo.
echo ==========================================
echo 启动完成！
echo ==========================================
echo.
echo 新开的窗口：
echo   - Celery Worker: 执行任务队列
echo   - Celery Beat:   定时任务调度（每30秒心跳）
echo.
echo 请保持这些窗口开启状态。
echo.
pause
