@echo off
REM ============================================================
REM  防火墙放行端口 8000(可选,首次部署时执行一次)
REM ============================================================
REM  用途:让 A 机能通过局域网访问 B 机的 Qwen3-ASR 服务。
REM  注意:此脚本需要管理员权限,右键"以管理员身份运行"。
REM  仅对当前 Windows 防火墙生效,不会修改路由器 ACL。
REM ============================================================
setlocal
set "PORT=8000"
set "RULE_NAME=Qwen3-ASR Server (TCP %PORT%)"

echo 正在放行 TCP %PORT% ...
netsh advfirewall firewall delete rule name="%RULE_NAME%" >nul 2>&1
netsh advfirewall firewall add rule ^
    name="%RULE_NAME%" ^
    dir=in action=allow protocol=TCP localport=%PORT% ^
    profile=private,domain
if errorlevel 1 (
    echo [ERROR] 添加防火墙规则失败,请确认已用"管理员身份"运行此脚本。
    exit /b 1
)
echo [OK] 已放行端口 %PORT%(仅 private + domain profile)。
echo.
echo 测试访问(本机): http://127.0.0.1:%PORT%/health
echo 局域网访问(从 A 机): http://B机的IP:%PORT%/health
echo.
echo 如需查看本机 IP:
ipconfig | findstr /i "IPv4"
endlocal
