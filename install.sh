#!/usr/bin/env bash
# =============================================================
# install.sh — Cài đặt lần đầu & cập nhật Telegram Bot Reminder
# Dùng:
#   ./install.sh          → tự động phát hiện lần đầu / cập nhật
#   ./install.sh --first  → ép chế độ cài đặt lần đầu
#   ./install.sh --update → ép chế độ cập nhật
# =============================================================
set -euo pipefail

# ── Màu sắc ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC}   $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
info() { echo -e "${BLUE}[INFO]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }
sep()  { echo -e "${BOLD}──────────────────────────────────────────${NC}"; }

# ── 1. Kiểm tra Docker ───────────────────────────────────────
sep
info "Kiểm tra môi trường..."

command -v docker >/dev/null 2>&1 \
  || err "Docker chưa cài. Xem: https://docs.docker.com/get-docker/"

docker info >/dev/null 2>&1 \
  || err "Docker daemon chưa chạy. Hãy khởi động Docker Desktop hoặc 'sudo systemctl start docker'."

docker compose version >/dev/null 2>&1 \
  || err "Docker Compose v2 chưa cài. Xem: https://docs.docker.com/compose/install/"

ok "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+')"
ok "Docker Compose $(docker compose version --short)"

# ── 2. File .env ─────────────────────────────────────────────
sep
info "Kiểm tra cấu hình .env..."

if [ ! -f .env ]; then
  warn ".env chưa có → tạo từ .env.example..."
  if [ -f .env.example ]; then
    cp .env.example .env
  else
    cat > .env << 'ENVEOF'
BOT_TOKEN=your_bot_token_here
DB_HOST=db
DB_USER=root
DB_PASSWORD=change_me_secret
DB_NAME=reminder_bot
OPENWEATHER_API_KEY=your_openweathermap_api_key
DEFAULT_CITY=Ho Chi Minh
TIME_INFORMATION=06:30
ENVEOF
  fi
  echo ""
  warn "File .env vừa được tạo. Hãy điền thông tin trước khi tiếp tục:"
  echo "  BOT_TOKEN        — lấy từ @BotFather trên Telegram"
  echo "  DB_PASSWORD      — mật khẩu MySQL (đặt tuỳ ý)"
  echo "  OPENWEATHER_API_KEY — đăng ký tại https://openweathermap.org/api"
  echo ""
  echo "  Chỉnh sửa:  nano .env"
  echo "  Rồi chạy lại:  ./install.sh"
  exit 0
fi

# Validate các key bắt buộc
_bot=$(grep -E '^BOT_TOKEN=' .env | cut -d= -f2- | tr -d '"' | tr -d "'" | xargs)
_pass=$(grep -E '^DB_PASSWORD=' .env | cut -d= -f2- | tr -d '"' | tr -d "'" | xargs)

[[ "$_bot" == "your_bot_token_here" || -z "$_bot" ]] \
  && err "BOT_TOKEN trong .env chưa được cấu hình."
[[ "$_pass" == "change_me_secret" ]] \
  && warn "DB_PASSWORD vẫn là giá trị mặc định 'change_me_secret'. Nên đổi lại."

ok ".env hợp lệ"

# ── 3. Xác định chế độ ───────────────────────────────────────
sep
FORCE_MODE="${1:-auto}"

if [ "$FORCE_MODE" = "--first" ]; then
  MODE="install"
elif [ "$FORCE_MODE" = "--update" ]; then
  MODE="update"
else
  # Tự động: kiểm tra container tồn tại chưa
  if docker ps -a --format "{{.Names}}" 2>/dev/null | grep -q "telegram-bot"; then
    MODE="update"
  else
    MODE="install"
  fi
fi

if [ "$MODE" = "install" ]; then
  echo -e "\n${BOLD}📦  Chế độ: CÀI ĐẶT LẦN ĐẦU${NC}\n"
else
  echo -e "\n${BOLD}🔄  Chế độ: CẬP NHẬT${NC}\n"
  # Pull code mới nếu đang trong git repo
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    info "Git pull..."
    git pull --ff-only && ok "Code đã được cập nhật" || warn "git pull thất bại, tiếp tục với code hiện tại."
  fi
fi

# ── 4. Build & Start ─────────────────────────────────────────
sep
info "Build image và khởi động services..."
docker compose up -d --build
ok "docker compose up hoàn tất"

# ── 5. Đợi DB sẵn sàng (lần đầu) ────────────────────────────
if [ "$MODE" = "install" ]; then
  sep
  info "Đợi MySQL sẵn sàng (tối đa 60s)..."
  for i in $(seq 1 30); do
    if docker compose exec -T db mysqladmin ping -hlocalhost --silent 2>/dev/null; then
      ok "MySQL sẵn sàng (${i}×2s)"
      break
    fi
    printf "."
    sleep 2
    if [ "$i" -eq 30 ]; then
      echo ""
      warn "MySQL chưa phản hồi. Kiểm tra: docker compose logs db"
    fi
  done
  echo ""
fi

# ── 6. Hiển thị trạng thái ───────────────────────────────────
sep
info "Trạng thái containers:"
docker compose ps

sep
info "Log bot (20 dòng gần nhất):"
docker compose logs --tail=20 bot

sep
if [ "$MODE" = "install" ]; then
  ok "Cài đặt hoàn tất!"
else
  ok "Cập nhật hoàn tất!"
fi
echo -e "   Theo dõi log: ${BOLD}docker compose logs -f bot${NC}"
echo -e "   Dừng bot:     ${BOLD}docker compose down${NC}"
echo -e "   Khởi động lại:${BOLD}docker compose restart bot${NC}"
