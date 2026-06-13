"""
B 机环境自检脚本
================
目标:在安装任何依赖之前,先确认 B 机是否真的能跑 Qwen3-ASR。

用法:
    python scripts/check_env.py
退出码:
    0 = 通过(可继续部署)
    1 = 任意一项硬性要求不满足
    2 = 仅警告(可继续,但建议处理)
"""
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def banner(text: str) -> None:
    print()
    print("=" * 60)
    print(f"  {text}")
    print("=" * 60)


def check_python() -> bool:
    banner("Python 版本")
    v = sys.version_info
    print(f"  Python {v.major}.{v.minor}.{v.micro} ({platform.architecture()[0]})")
    ok = (v.major, v.minor) >= (3, 10)
    print(f"  {'[OK]' if ok else '[FAIL]'} 需要 Python >= 3.10 (官方推荐 3.12)")
    return ok


def check_pip() -> bool:
    banner("pip")
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True, text=True, check=True,
        )
        print(f"  {out.stdout.strip()}")
        return True
    except Exception as e:
        print(f"  [FAIL] pip 不可用: {e}")
        return False


def check_ffmpeg() -> bool:
    banner("ffmpeg")
    path = shutil.which("ffmpeg")
    if not path:
        print("  [FAIL] 未检测到 ffmpeg,Qwen3-ASR 前处理必需")
        print("         安装: choco install ffmpeg   (需要管理员 PowerShell)")
        print("         或:   winget install Gyan.FFmpeg")
        return False
    try:
        out = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True, check=True,
        )
        first_line = out.stdout.splitlines()[0]
        print(f"  {first_line}")
        return True
    except Exception as e:
        print(f"  [WARN] ffmpeg 路径异常: {e}")
        return False


def check_cuda() -> dict:
    banner("NVIDIA 驱动 / CUDA")
    info = {"driver": None, "cuda_runtime": None, "gpus": []}

    # nvidia-smi
    nvsmi = shutil.which("nvidia-smi")
    if not nvsmi:
        print("  [FAIL] 未找到 nvidia-smi,可能未装 NVIDIA 驱动或不在 PATH")
        return info
    try:
        out = subprocess.run(
            [nvsmi, "--query-gpu=name,memory.total,driver_version"],
            capture_output=True, text=True, check=True,
        )
        print("  nvidia-smi 输出:")
        for line in out.stdout.strip().splitlines():
            print(f"    {line}")
            if "MiB" in line and "GeForce" in line or "NVIDIA" in line:
                info["gpus"].append(line.strip())
        # 提取 driver
        for line in out.stdout.splitlines():
            if "Driver Version" in line:
                info["driver"] = line.strip()
    except subprocess.CalledProcessError as e:
        print(f"  [FAIL] nvidia-smi 执行失败: {e.stderr.strip()}")
        return info

    # nvcc
    nvcc = shutil.which("nvcc")
    if nvcc:
        try:
            out = subprocess.run(
                [nvcc, "--version"], capture_output=True, text=True, check=True,
            )
            for line in out.stdout.splitlines():
                if "release" in line.lower():
                    print(f"  {line.strip()}")
                    info["cuda_runtime"] = line.strip()
        except Exception:
            pass
    else:
        print("  [INFO] 未检测到 nvcc(可只装 GPU 版 PyTorch,无需 nvcc)")

    return info


def check_pytorch_cuda() -> bool:
    banner("PyTorch + CUDA 可用性")
    try:
        import torch  # type: ignore
    except ImportError:
        print("  [WARN] 尚未安装 torch,稍后由 install.bat 一并安装")
        return True  # 不是 fail,只是 skip
    print(f"  torch  {torch.__version__}")
    print(f"  cuda available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"  device count:    {torch.cuda.device_count()}")
        for i in range(torch.cuda.device_count()):
            name = torch.cuda.get_device_name(i)
            cap = torch.cuda.get_device_capability(i)
            mem = torch.cuda.get_device_properties(i).total_memory / (1024 ** 3)
            print(f"  [{i}] {name}  CC {cap[0]}.{cap[1]}  VRAM {mem:.1f} GB")
    else:
        print("  [FAIL] torch 装的是 CPU 版,需要重装 GPU 版")
    return torch.cuda.is_available()


def check_disk(models_dir: Path) -> bool:
    banner("磁盘空间")
    try:
        import ctypes
        free_bytes = ctypes.c_ulonglong(0)
        total_bytes = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            str(models_dir), None, None, ctypes.pointer(free_bytes)
        )
        free_gb = free_bytes.value / (1024 ** 3)
        print(f"  {models_dir} 所在盘剩余: {free_gb:.1f} GB")
        if free_gb < 15:
            print("  [FAIL] 至少需要 15GB 空闲(模型 3-7GB + 缓存 + 运行环境)")
            return False
        return True
    except Exception as e:
        print(f"  [WARN] 无法获取磁盘空间: {e}")
        return True


def check_memory() -> bool:
    banner("物理内存")
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        total = stat.ullTotalPhys / (1024 ** 3)
        avail = stat.ullAvailPhys / (1024 ** 3)
        print(f"  总计 {total:.1f} GB,可用 {avail:.1f} GB")
        return total >= 8
    except Exception as e:
        print(f"  [WARN] 无法获取内存信息: {e}")
        return True


def main() -> int:
    print("Qwen3-ASR 部署环境自检 (B 机)")
    print(f"  平台: {platform.system()} {platform.release()} {platform.machine()}")
    print(f"  当前 Python: {sys.executable}")

    models_dir = Path(__file__).resolve().parent.parent / "models"

    py_ok = check_python()
    pip_ok = check_pip()
    ffmpeg_ok = check_ffmpeg()
    cuda_info = check_cuda()
    torch_ok = check_pytorch_cuda()
    mem_ok = check_memory()
    disk_ok = check_disk(models_dir)

    banner("总结")
    checks = [
        ("Python >= 3.10", py_ok),
        ("pip 可用",       pip_ok),
        ("ffmpeg 可用",    ffmpeg_ok),
        ("GPU + 驱动可用", bool(cuda_info["gpus"])),
        ("PyTorch CUDA",   torch_ok),
        ("内存 >= 8GB",    mem_ok),
        ("磁盘 >= 15GB",   disk_ok),
    ]
    for name, ok in checks:
        print(f"  [{'OK' if ok else 'FAIL'}] {name}")

    hard_fails = [n for n, ok in checks if not ok and n in {
        "Python >= 3.10", "pip 可用", "ffmpeg 可用",
        "GPU + 驱动可用", "PyTorch CUDA", "磁盘 >= 15GB",
    }]
    if hard_fails:
        print("\n[FAIL] 硬性要求不满足,请先处理以下项:")
        for n in hard_fails:
            print(f"   - {n}")
        return 1

    if not mem_ok:
        print("\n[WARN] 内存偏小,运行时可能 swap 频繁,建议升级到 16GB+")

    print("\n[OK] 环境自检通过,可以运行 install.bat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
