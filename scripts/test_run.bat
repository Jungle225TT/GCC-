@echo off
chcp 65001 >nul
echo.
echo 正在运行GCC智库抓取系统（测试模式）...
echo 预计耗时3-8分钟，请耐心等待
echo.
python main.py
echo.
echo 运行完成！
echo 结果文件在 output\ 目录下
echo 日志文件在 logs\ 目录下
echo.
pause
