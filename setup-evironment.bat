@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: =============================================================
:: setup-environment.bat
:: Cài đặt lần đầu & cập nhật Telegram Bot Reminder (Windows)
:: Dùng:  setup-environment.bat
::        setup-environment.bat --first   (ép cài đặt lần đầu)
::        setup-environment.bat --update  (ép cập nhật)
:: =============================================================

set "FORCE_MODE=%~1"

echo.
echo ══════════════════════════════════════════════════
echo   Telegram Bot Reminder — Setup / Update
echo ══════════════════════════════════════════════════

:: ── 1. Kiểm tra Docker ──────────────────────────────────────
echo.
echo [INFO] Kiem tra Docker...
docker --version >nul 2>&1
if errorlevel 1 (
    echo [ERR]  Docker chua duoc cai dat.
    echo        Tai tai: https://docs.docker.com/desktop/windows/
    pause & exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERR]  Docker daemon chua chay. Hay mo Docker Desktop truoc.
    pause & exit /b 1
)
docker compose version >nul 2>&1
if errorlevel 1 (
    echo [ERR]  Docker Compose v2 chua co. Cap nhat Docker Desktop.
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('docker --version') do echo [OK]   %%v
echo [OK]   Docker Compose OK

:: ── 2. File .env ────────────────────────────────────────────
echo.
echo [INFO] Kiem tra .env...
if not exist ".env" (
    echo [WARN] .env chua co. Tao moi tu .env.example...
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
    ) else (
        (
            echo BOT_TOKEN=your_bot_token_here
            echo DB_HOST=db
            echo DB_USER=root
            echo DB_PASSWORD=change_me_secret
            echo DB_NAME=reminder_bot
            echo OPENWEATHER_API_KEY=your_openweathermap_api_key
            echo DEFAULT_CITY=Ho Chi Minh
            echo TIME_INFORMATION=06:30
        ) > .env
    )
    echo.
    echo [WARN] File .env vua duoc tao. Hay dien thong tin vao truoc:
    echo        BOT_TOKEN        - lay tu @BotFather tren Telegram
    echo        DB_PASSWORD      - mat khau MySQL tu dat
    echo        OPENWEATHER_API_KEY - dang ky tai openweathermap.org
    echo.
    echo        Mo file: notepad .env
    echo        Roi chay lai script nay.
    notepad .env
    pause & exit /b 0
)

:: Validate BOT_TOKEN
findstr /R "^BOT_TOKEN=your_bot_token_here" .env >nul 2>&1
if not errorlevel 1 (
    echo [ERR]  BOT_TOKEN trong .env chua duoc cau hinh.
    echo        Mo file .env va dien BOT_TOKEN.
    notepad .env
    pause & exit /b 1
)
findstr /R "^BOT_TOKEN=\s*$" .env >nul 2>&1
if not errorlevel 1 (
    echo [ERR]  BOT_TOKEN trong .env dang de trong.
    notepad .env
    pause & exit /b 1
)
echo [OK]   .env hop le

:: ── 3. Xac dinh che do ──────────────────────────────────────
echo.
set "MODE=auto"
if "%FORCE_MODE%"=="--first"  set "MODE=install"
if "%FORCE_MODE%"=="--update" set "MODE=update"

if "%MODE%"=="auto" (
    docker ps -a --format "{{.Names}}" 2>nul | findstr /C:"telegram-bot" >nul 2>&1
    if errorlevel 1 (
        set "MODE=install"
    ) else (
        set "MODE=update"
    )
)

if "%MODE%"=="install" (
    echo ══ CHE DO: CAI DAT LAN DAU ══
) else (
    echo ══ CHE DO: CAP NHAT ══
    :: Git pull neu co
    git rev-parse --is-inside-work-tree >nul 2>&1
    if not errorlevel 1 (
        echo [INFO] Git pull...
        git pull --ff-only && echo [OK]   Code da cap nhat || echo [WARN] git pull that bai, tiep tuc voi code hien tai.
    )
)

:: ── 4. Build & Start ────────────────────────────────────────
echo.
echo [INFO] Build image va khoi dong services...
docker compose up -d --build
if errorlevel 1 (
    echo [ERR]  docker compose up that bai.
    pause & exit /b 1
)
echo [OK]   docker compose up hoan tat

:: ── 5. Doi DB san sang (lan dau) ────────────────────────────
if "%MODE%"=="install" (
    echo.
    echo [INFO] Doi MySQL san sang (toi da 60s^)...
    set /a TRIES=0
    :WAIT_DB
    set /a TRIES+=1
    docker compose exec -T db mysqladmin ping -hlocalhost --silent >nul 2>&1
    if not errorlevel 1 (
        echo [OK]   MySQL san sang
        goto DB_READY
    )
    if !TRIES! geq 30 (
        echo [WARN] MySQL chua phan hoi. Kiem tra: docker compose logs db
        goto DB_READY
    )
    timeout /t 2 /nobreak >nul
    goto WAIT_DB
    :DB_READY
)

:: ── 6. Trang thai ───────────────────────────────────────────
echo.
echo [INFO] Trang thai containers:
docker compose ps

echo.
echo [INFO] Log bot (20 dong gan nhat):
docker compose logs --tail=20 bot

echo.
echo ══════════════════════════════════════════════════
if "%MODE%"=="install" (
    echo [OK]   Cai dat hoan tat!
) else (
    echo [OK]   Cap nhat hoan tat!
)
echo        Theo doi log : docker compose logs -f bot
echo        Dung bot     : docker compose down
echo        Khoi dong lai: docker compose restart bot
echo ══════════════════════════════════════════════════
echo.
pause
