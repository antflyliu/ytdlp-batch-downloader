@echo off
REM ============================================================
REM  Qwen3-ASR 一键安装脚本 (B 机, Windows)
REM ============================================================
REM  用法(管理员 PowerShell 或 CMD):
REM      scripts\install.bat
REM  说明:
REM    1. 创建 .venv312 虚拟环境(Python 3.12)
REM    2. 升级 pip / 安装 wheel
REM    3. 安装 GPU 版 PyTorch(CUDA 12.9)
REM    4. 安装 qwen-asr[vllm] 后端
REM    5. 预下载 Qwen3-ASR-0.6B 模型到 models\
REM 预计耗时: 10-25 分钟(视网络)
REM ============================================================
setlocal EnableDelayedExpansion

REM ---- 路径配置 ----
set "ROOT=%~dp0.."
pushd "%ROOT%"
set "ROOT=%CD%"
popd

set "VENV=%ROOT%\.venv312"
set "VENV_PY=%VENV%\Scripts\python.exe"
set "MODELS=%ROOT%\models"
set "LOGDIR=%ROOT%\logs"
set "MODEL_NAME=Qwen/Qwen3-ASR-0.6B"

REM ---- 日志 ----
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "LOG=%LOGDIR%\install_%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%.log"
set "LOG=%LOG: =0%"

echo ============================================================> "%LOG%"
echo  Qwen3-ASR 安装日志  %date% %time%>> "%LOG%"
echo ============================================================>> "%LOG%"

echo [1/6] 自检环境...
echo.
call "%ROOT%\scripts\check_env.py"
set "ENV_RC=%ERRORLEVEL%"
echo.
if not "%ENV_RC%"=="0" (
    echo [ERROR] 自检未通过(返回码 %ENV_RC%),请按提示修复后重试。
    echo         日志: %LOG%
    exit /b 1
)
echo [1/6] 自检通过。
echo.

echo [2/6] 创建虚拟环境 %VENV% ...
if not exist "%VENV%\Scripts\python.exe" (
    "%SystemRoot%\py.exe" -3.12 -m venv "%VENV%" 2>>"%LOG%"
    if errorlevel 1 (
        echo [ERROR] 创建 venv 失败。请确认已安装 Python 3.12,且 py launcher 可用。
        echo         下载: https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe
        exit /b 1
    )
) else (
    echo        venv 已存在,跳过创建。
)
echo [2/6] 完成。
echo.

echo [3/6] 升级 pip + 安装 wheel ...
"%VENV_PY%" -m pip install --upgrade pip wheel 2>>"%LOG%"
if errorlevel 1 (
    echo [ERROR] pip 升级失败,查看日志: %LOG%
    exit /b 1
)
echo [3/6] 完成。
echo.

echo [4/6] 安装 GPU 版 PyTorch (CUDA 12.9) ...
echo        这一步约 1-3 GB,耐心等待。
"%VENV_PY%" -m pip install --upgrade ^
    torch torchvision torchaudio ^
    --index-url https://download.pytorch.org/whl/cu129 2>>"%LOG%"
if errorlevel 1 (
    echo [WARN] cu129 索引失败,尝试 cu124 回退 ...
    "%VENV_PY%" -m pip install --upgrade ^
        torch torchvision torchaudio ^
        --index-url https://download.pytorch.org/whl/cu124 2>>"%LOG%"
    if errorlevel 1 (
        echo [ERROR] PyTorch 安装失败,日志: %LOG%
        exit /b 1
    )
)
echo [4/6] 完成。
echo.

echo [5/6] 安装 qwen-asr[vllm] + 音频依赖 ...
"%VENV_PY%" -m pip install --upgrade "qwen-asr[vllm]" 2>>"%LOG%"
if errorlevel 1 (
    echo [WARN] vllm 后端安装失败,降级到 transformers 后端 ...
    "%VENV_PY%" -m pip install --upgrade "qwen-asr" 2>>"%LOG%"
    if errorlevel 1 (
        echo [ERROR] qwen-asr 安装失败,日志: %LOG%
        exit /b 1
    )
    set "BACKEND=transformers"
) else (
    set "BACKEND=vllm"
)
REM 音频处理常用包
"%VENV_PY%" -m pip install --upgrade ^
    soundfile librosa pydub modelscope "huggingface_hub[cli]" 2>>"%LOG%"
echo [5/6] 完成 (后端: !BACKEND!)。
echo.

echo [6/6] 预下载模型 %MODEL_NAME% ...
if not exist "%MODELS%" mkdir "%MODELS%"
cd /d "%MODELS%"
"%VENV_PY%" -c "from huggingface_hub import snapshot_download; p = snapshot_download(repo_id='%MODEL_NAME%', local_dir='%MODELS%\%MODEL_NAME:\=/%'); print('下载完成:', p)" 2>>"%LOG%"
if errorlevel 1 (
    echo [WARN] HF 下载失败,尝试 ModelScope ...
    "%VENV_PY%" -m modelscope download --model "%MODEL_NAME%" --local_dir "%MODELS%\%MODEL_NAME:\=/%" 2>>"%LOG%"
    if errorlevel 1 (
        echo [ERROR] 模型下载失败,日志: %LOG%
        exit /b 1
    )
)
echo [6/6] 完成。
echo.

echo ============================================================
echo  安装完成!后端: !BACKEND!
echo  下一步: scripts\start_server.bat
echo  安装日志: %LOG%
echo ============================================================
endlocal
