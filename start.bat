@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker 未安装。请安装 Docker Desktop: https://www.docker.com/products/docker-desktop/
  exit /b 1
)

if not exist .env (
  if exist .env.example (
    copy .env.example .env >nul
    echo [WARN] 已创建 .env，请编辑并填入 MINIMAX_API_KEY 后重新运行 start.bat
    notepad .env
    exit /b 0
  ) else (
    echo [ERROR] 缺少 .env.example
    exit /b 1
  )
)

if not exist data\workspace mkdir data\workspace

echo [INFO] 构建并启动 linCut...
docker compose up --build -d
if errorlevel 1 (
  docker-compose up --build -d
)

echo [INFO] linCut 启动中，请稍候...
timeout /t 5 /nobreak >nul

echo.
echo [OK] 打开浏览器访问: http://localhost:8000
echo [INFO] 查看日志: docker compose logs -f
echo [INFO] 停止服务: docker compose down
echo [INFO] 视频输出目录: %cd%\data\workspace\

endlocal
