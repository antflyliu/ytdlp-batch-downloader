@echo off
REM ============================================================
REM  Qwen3-ASR 服务启动脚本 (B 机, Windows)
REM ============================================================
REM  用法:
REM      scripts\start_server.bat
REM  可调参数(通过环境变量):
REM      PORT          监听端口,默认 8000
REM      HOST          监听地址,默认 0.0.0.0(允许远程连接)
REM      MODEL         模型名称或本地路径,默认 Qwen/Qwen3-ASR-0.6B
REM      GPU_MEM_UTIL  显存利用率(0-1),默认 0.85
REM      API_KEY       鉴权 token,留空则不启用鉴权
REM      BACKEND       vllm 或 transformers,默认自动选择
REM ============================================================
setlocal EnableDelayedExpansion

set "ROOT=%~dp0.."
pushd "%ROOT%"
set "ROOT=%CD%"
popd

if not defined PORT          set "PORT=8000"
if not defined HOST          set "HOST=0.0.0.0"
if not defined MODEL         set "MODEL=Qwen/Qwen3-ASR-0.6B"
if not defined GPU_MEM_UTIL  set "GPU_MEM_UTIL=0.85"
if not defined BACKEND       set "BACKEND=vllm"

set "VENV_PY=%ROOT%\.venv312\Scripts\python.exe"
set "LOGDIR=%ROOT%\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "LOG=%LOGDIR%\server_%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%.log"
set "LOG=%LOG: =0%"

echo ============================================================> "%LOG%"
echo  Qwen3-ASR 启动日志  %date% %time%>> "%LOG%"
echo  PORT=%PORT% HOST=%HOST% MODEL=%MODEL% GPU_MEM_UTIL=%GPU_MEM_UTIL%>> "%LOG%"
echo  API_KEY=%API_KEY% BACKEND=%BACKEND%>> "%LOG%"
echo ============================================================>> "%LOG%"

if not exist "%VENV_PY%" (
    echo [ERROR] 虚拟环境不存在,请先运行 scripts\install.bat
    exit /b 1
)

REM ---- 自动选后端(可被环境变量覆盖) ----
"%VENV_PY%" -c "import vllm" 2>nul
if errorlevel 1 (
    if /i "%BACKEND%"=="vllm" (
        echo [WARN] 未检测到 vllm,降级到 transformers 后端
        set "BACKEND=transformers"
    )
)

REM ---- 拼装 token 参数 ----
set "TOKEN_ARGS="
if defined API_KEY (
    if not "%API_KEY%"=="" set "TOKEN_ARGS=--api-key %API_KEY%"
)

if /i "%BACKEND%"=="vllm" (
    echo [INFO] 启动 vLLM 后端 ...
    echo        端口 %PORT%   模型 %MODEL%   显存利用率 %GPU_MEM_UTIL%
    echo        日志: %LOG%
    echo.
    "%VENV_PY%" -m vllm.entrypoints.openai.api_server ^
        --model "%MODEL%" ^
        --host "%HOST%" ^
        --port %PORT% ^
        --gpu-memory-utilization %GPU_MEM_UTIL% ^
        --served-model-name qwen3-asr ^
        --trust-remote-code ^
        %TOKEN_ARGS% >> "%LOG%" 2>&1
) else (
    echo [INFO] 启动 transformers 后端 ...
    echo        端口 %PORT%   模型 %MODEL%
    echo        日志: %LOG%
    echo.
    pushd "%ROOT%"
    "%VENV_PY%" "%ROOT%\scripts\serve_transformers.py" ^
        --model "%MODEL%" ^
        --host "%HOST%" ^
        --port %PORT% ^
        --api-key "%API_KEY%" >> "%LOG%" 2>&1
    popd
)

echo.
echo [INFO] 服务已退出,日志: %LOG%
endlocal
