#!/usr/bin/env bash
# One-command launcher for linCut (Docker)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}▸${NC} $*"; }
warn()  { echo -e "${YELLOW}▸${NC} $*"; }
error() { echo -e "${RED}✗${NC} $*" >&2; }

if ! command -v docker >/dev/null 2>&1; then
  error "Docker 未安装。请先安装 Docker Desktop: https://www.docker.com/products/docker-desktop/"
  exit 1
fi

COMPOSE="docker compose"
if ! docker compose version >/dev/null 2>&1; then
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
  else
    error "未找到 docker compose，请安装 Docker Compose v2。"
    exit 1
  fi
fi

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    warn "已创建 .env，请编辑并填入 MINIMAX_API_KEY："
    echo "  open .env   # macOS"
    echo "  nano .env"
    exit 0
  else
    error "缺少 .env 和 .env.example"
    exit 1
  fi
fi

# shellcheck disable=SC1091
set +u
source .env 2>/dev/null || true
set -u

if [ -z "${MINIMAX_API_KEY:-}" ] || [ "${MINIMAX_API_KEY}" = "your-minimax-api-key-here" ]; then
  error "请在 .env 中设置有效的 MINIMAX_API_KEY 后再运行。"
  exit 1
fi

mkdir -p data/workspace

info "构建并启动 linCut（首次可能需要几分钟）..."
$COMPOSE up --build -d

info "等待服务就绪..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
    echo ""
    info "linCut 已启动 → http://localhost:8000"
    info "查看日志: $COMPOSE logs -f"
    info "停止服务: $COMPOSE down"
    info "生成视频保存在: $ROOT/data/workspace/"
    exit 0
  fi
  sleep 2
done

error "服务启动超时，请查看日志: $COMPOSE logs"
exit 1
