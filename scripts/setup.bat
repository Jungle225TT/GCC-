@echo off
chcp 65001 >nul
:: ============================================================
:: GCC智库爬虫 — Windows一键部署脚本
:: 右键 → 以管理员身份运行
:: ============================================================

echo.
echo ========================================
echo  GCC智库研究抓取系统 v2.2 — 一键部署
echo ========================================
echo.

:: 检查Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    echo 安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)
echo [OK] Python已安装

:: 创建工作目录结构
set SCRIPT_DIR=%~dp0
mkdir "%SCRIPT_DIR%output" 2>nul
mkdir "%SCRIPT_DIR%logs" 2>nul
echo [OK] 目录结构创建完成

:: 安装依赖
echo.
echo 正在安装依赖包（约需1-2分钟）...
pip install requests beautifulsoup4 feedparser anthropic playwright -q
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败，请检查网络连接
    pause
    exit /b 1
)
echo [OK] Python依赖安装完成

:: 安装Playwright浏览器（用于JS渲染抓取）
echo.
echo 正在安装Playwright浏览器内核（约需3-5分钟，仅首次需要）...
playwright install chromium
if %errorlevel% neq 0 (
    echo [警告] Playwright浏览器安装失败，JS渲染功能将不可用
    echo         静态HTML抓取仍然正常运行
)
echo [OK] Playwright安装完成

:: 创建Windows定时任务（每周一09:00）
echo.
echo 正在配置定时任务（每周一 09:00 自动运行）...

schtasks /create ^
  /tn "GCC智库研究抓取" ^
  /tr "python \"%SCRIPT_DIR%main.py\"" ^
  /sc weekly /d MON /st 09:00 ^
  /f /rl highest ^
  /sd %date%

if %errorlevel% equ 0 (
    echo [OK] 定时任务配置成功
    echo      任务名称: GCC智库研究抓取
    echo      运行时间: 每周一 09:00
    echo      查看路径: 任务计划程序 → GCC智库研究抓取
) else (
    echo [警告] 定时任务创建失败
    echo         请右键此脚本 → 以管理员身份运行
)

echo.
echo ========================================
echo  部署完成！下一步：
echo.
echo  1. 用记事本打开 config.py
echo  2. 填入 ANTHROPIC_API_KEY
echo  3. 填入 FEISHU_WEBHOOK_URL
echo  4. 填入飞书Bitable相关配置（可选）
echo  5. 双击 test_run.bat 测试运行
echo ========================================
echo.
pause
