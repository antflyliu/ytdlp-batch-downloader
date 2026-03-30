import yt_dlp
from tqdm import tqdm
import os
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import time
import argparse
import sys
import re
from pathlib import Path
import torch


def load_proxy_pool(file_path):
    """
    从文件加载代理池，每行一个代理地址
    支持空行和 # 注释
    """
    proxies = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    proxies.append(line)
    except Exception:
        pass
    return proxies


def is_rate_limited(error_msg):
    """判断是否是被限流或代理网络错误的信号，应切换代理"""
    msg = str(error_msg).lower()
    # YouTube 限流信号
    if any(k in msg for k in ["429", "too many request", "rate limit", "quota exceeded"]):
        return True
    # 代理网络问题：超时 / 连接拒绝 / SOCKS 错误
    if any(k in msg for k in [
        "timed out", "timeout", "connection refused",
        "connection reset", "proxy error",
        "socks", "tunnel connection failed",
    ]):
        return True
    return False


def get_format_option(resolution):
    """根据选择的分辨率返回格式选项"""
    resolution_map = {
        '720p': 720,
        '1080p': 1080,
        '1440p': 1440
    }
    height = resolution_map[resolution]
    # 添加编码格式限制，优先选择 H.264 编码
    return f'bestvideo[height<={height}][vcodec^=avc]+bestaudio[ext=m4a]/best[height<={height}]/best'


def get_device(prefer_device="auto"):
    """自动或手动选择运行设备"""
    if prefer_device == "cuda":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if prefer_device == "cpu":
        return "cpu"
    # auto: 有GPU用GPU，否则CPU
    return "cuda" if torch.cuda.is_available() else "cpu"


def get_subtitle_langs(sub_lang_str):
    """解析字幕语言字符串，返回 yt-dlp 和 WhisperX 格式"""
    langs = [l.strip() for l in sub_lang_str.split(",") if l.strip()]
    # yt-dlp 格式
    ydl_format = ",".join(langs)
    return langs, ydl_format


def generate_subtitle_with_whisper(video_path, output_dir, model_name="medium",
                                   device="cpu", compute_type="int8"):
    """
    使用 WhisperX 子进程从视频文件生成字幕
    返回生成的字幕文件路径，失败返回 None
    """
    import subprocess
    import sys

    script_dir = os.path.dirname(os.path.abspath(__file__))
    worker_script = os.path.join(script_dir, "scripts", "whisperx_worker.py")

    try:
        result = subprocess.run(
            [
                sys.executable, worker_script,
                video_path, output_dir, model_name, device, compute_type
            ],
            capture_output=True,
            text=True,
            timeout=3600,
        )

        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("SUCCESS:"):
                    return line.split("SUCCESS:", 1)[1].strip()
            return None
        else:
            print(f"      WhisperX 子进程失败: {result.stderr.strip()}")
            return None
    except subprocess.TimeoutExpired:
        print(f"      WhisperX 处理超时（>1小时）")
        return None
    except Exception as e:
        print(f"      WhisperX 生成字幕失败: {e}")
        return None


def check_subtitle_exists(video_path, sub_langs):
    """
    检查字幕文件是否存在
    sub_langs: 语言代码列表，如 ['zh-Hans', 'en']
    返回第一个找到的字幕文件路径，否则返回 None
    """
    video_dir = Path(video_path).parent
    base_name = Path(video_path).stem  # 不含扩展名的文件名
    for lang in sub_langs:
        for ext in ("srt", "vtt"):
            # 精确匹配: title.lang.ext
            candidate = video_dir / f"{base_name}.{lang}.{ext}"
            if candidate.exists():
                return str(candidate)
            # 模糊匹配: title.*.lang.ext（yt-dlp 某些版本）
            for other in video_dir.glob(f"{base_name}.*.{lang}.{ext}"):
                return str(other)
    return None


def format_timestamp(seconds):
    """将秒数转换为 SRT 时间戳格式 HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(segments, srt_path):
    """将 whisperx segments 写入 SRT 文件"""
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            text = seg.get("text", "").strip()
            f.write(f"{i}\n")
            f.write(f"{format_timestamp(start)} --> {format_timestamp(end)}\n")
            f.write(f"{text}\n\n")


def convert_vtt_to_srt(vtt_path):
    """
    将 VTT 字幕文件转换为 SRT 格式
    返回转换后的 SRT 路径，失败返回 None
    """
    srt_path = vtt_path.rsplit(".", 1)[0] + ".srt"
    try:
        with open(vtt_path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.splitlines()
        result = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if "-->" in line:
                # 转换 VTT 时间格式为 SRT（只转换时间部分，不影响 cue text 中的 VTT tags）
                def convert_vtt_time(srt_match):
                    full = srt_match.group(0)
                    return full.replace(".", ",")
                line = re.sub(r"\d{2}:\d{2}:\d{2}\.\d{3}", convert_vtt_time, line)
                # 去掉 align/position 等 VTT 扩展属性
                line = re.sub(r"\s+align:\S+", "", line)
                line = re.sub(r"\s+position:\S+", "", line)
                line = re.sub(r"\s+line:\S+", "", line)
                result.append(line)
            elif line and not line.startswith("WEBVTT") and not line.startswith("NOTE"):
                result.append(line)
            i += 1
        # 写 SRT：重新编号，合并多行文本
        with open(srt_path, "w", encoding="utf-8") as f:
            subtitle_index = 0
            i = 0
            while i < len(result):
                if "-->" in result[i]:
                    subtitle_index += 1
                    f.write(f"{subtitle_index}\n")
                    f.write(result[i] + "\n")
                    i += 1
                    text_lines = []
                    while i < len(result) and result[i].strip() and "-->" not in result[i]:
                        # 清理 VTT tags（包括 timestamp tags <00:00:00.000> 和样式 tags <c>)
                        text = re.sub(r"<[^>]+>", "", result[i]).strip()
                        text_lines.append(text)
                        i += 1
                    f.write(" ".join(text_lines) + "\n\n")
                else:
                    i += 1
        return srt_path
    except Exception as e:
        print(f"      VTT→SRT 转换失败: {e}")
        return None


def sanitize_filename(name):
    """清理文件名，移除非法字符"""
    return re.sub(r'[<>:"/\\|?*]', '_', name)


def batch_download(urls, output_path, resolution, proxy=None, progress_callback=None,
                  sub_langs=None, no_subs=False, proxy_pool=None,
                  cookies_from_browser=None, cookies_file=None):
    """
    批量下载视频的函数
    sub_langs: yt-dlp 字幕语言格式，如 "zh-Hans,en"
    no_subs: True 则不下载字幕
    proxy_pool: 代理池列表（每行一个地址），自动轮换；单个 proxy 优先于代理池
    """
    results = []
    total = len(urls)
    completed = 0

    # 优先用单个 proxy；没有则从代理池取
    pool_index = 0
    if proxy_pool:
        current_proxy = proxy_pool[0] if proxy_pool else None
    else:
        current_proxy = proxy

    ydl_opts_base = {
        'format': get_format_option(resolution),
        'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'format_sort': ['vcodec:h264'],
        'external_downloader': 'aria2c',
        'external_downloader_args': [
            '--min-split-size=1M',
            '--max-connection-per-server=16',
            '--split=16',
            '--max-concurrent-downloads=3',
            '--continue=true',
        ],
        # Cookie 配置（绕过 YouTube 机器人检测）
        'cookies_from_browser': cookies_from_browser,
        'cookiefile': cookies_file,
    }

    def _apply_proxy(opts, p):
        opts = {**opts}
        if p:
            opts['proxy'] = p
            opts['external_downloader_args'] = [
                '--min-split-size=1M',
                '--max-connection-per-server=16',
                '--split=16',
                '--max-concurrent-downloads=3',
                '--continue=true',
                f'--all-proxy={p}',
            ]
        else:
            opts['proxy'] = ''
            opts['external_downloader_args'] = [
                '--min-split-size=1M',
                '--max-connection-per-server=16',
                '--split=16',
                '--max-concurrent-downloads=3',
                '--continue=true',
            ]
        return opts

    # 字幕选项
    if not no_subs and sub_langs:
        ydl_opts_base.update({
            'writesubtitles': True,
            'writeautomaticsub': True,
            'sub_langs': sub_langs,
            'convert_subs': 'srt',
        })

    device = get_device("auto")
    whisper_compute = "float16" if device == "cuda" else "int8"
    whisper_model = "medium"

    for i, url in enumerate(urls):
        sub_status = "未下载"
        max_retries = len(proxy_pool) if proxy_pool else 1
        retry_count = 0

        while retry_count < max_retries:
            # 切换代理
            if proxy_pool:
                current_proxy = proxy_pool[pool_index % len(proxy_pool)]

            ydl_opts = _apply_proxy(ydl_opts_base, current_proxy)

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    video_title = info.get('title', 'unknown') if info else 'unknown'
                    video_path = os.path.join(output_path, f"{sanitize_filename(video_title)}.mp4")

                # yt-dlp ignoreerrors 会吞掉部分错误，必须验证文件是否真实存在
                if not video_path or not os.path.exists(video_path):
                    raise Exception("视频文件未生成，下载失败")

                # 处理字幕
                if not no_subs and video_path and os.path.exists(video_path):
                    lang_list = [l.strip() for l in sub_langs.split(",")] if sub_langs else []
                    existing_sub = check_subtitle_exists(video_path, lang_list) if lang_list else None
                    if existing_sub:
                        if existing_sub.endswith(".vtt"):
                            srt_path = convert_vtt_to_srt(existing_sub)
                            sub_status = f"yt-dlp: {os.path.basename(srt_path)}" if srt_path else f"yt-dlp: {os.path.basename(existing_sub)} (VTT未转换)"
                        else:
                            sub_status = f"yt-dlp: {os.path.basename(existing_sub)}"
                    else:
                        srt_path = generate_subtitle_with_whisper(
                            video_path, output_path,
                            model_name=whisper_model,
                            device=device,
                            compute_type=whisper_compute
                        )
                        sub_status = f"WhisperX: {os.path.basename(srt_path)}" if srt_path else "WhisperX失败"

                results.append({
                    'URL': url,
                    '状态': '成功',
                    '信息': f"下载成功 | 代理: {current_proxy or '直连'} | 字幕: {sub_status}" if not no_subs else f"下载成功 | 代理: {current_proxy or '直连'}"
                })
                break  # 成功则跳出重试循环

            except (yt_dlp.utils.DownloadError, Exception) as e:
                error_msg = str(e)
                if is_rate_limited(error_msg) and proxy_pool and retry_count < max_retries - 1:
                    print(f" [{i+1}/{total}] 代理 {current_proxy} 被限流，切换下一个...")
                    pool_index += 1
                    retry_count += 1
                    continue
                else:
                    results.append({
                        'URL': url,
                        '状态': '失败',
                        '信息': f"{error_msg} | 代理: {current_proxy or '直连'}"
                    })
                    break

        completed += 1
        if progress_callback:
            progress_callback(completed / total, f"完成第 {completed}/{total} 个视频")

    return results

def read_urls_from_file(file_path):
    """根据文件类型读取URL列表，支持 Excel(.xlsx/.xls) 和纯文本(.txt)"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".xlsx", ".xls"):
        return read_urls_from_excel(file_path)
    elif ext == ".txt":
        return read_urls_from_txt(file_path)
    else:
        print(f"不支持的文件格式: {ext}，仅支持 .xlsx/.xls/.txt")
        return None


def read_urls_from_excel(file_path):
    """从Excel文件读取URL列表"""
    try:
        df = pd.read_excel(file_path)
        url_column = None
        for col in df.columns:
            if col.lower() == "url":
                url_column = col
                print(f"找到URL列：{col}（第 {list(df.columns).index(col) + 1} 列）")
                break

        if url_column is None:
            print("错误：Excel文件中没有找到'URL'或'url'列")
            return None

        urls = df[url_column].dropna().tolist()
        print(f"从Excel读取到 {len(urls)} 个URL")
        return urls
    except Exception as e:
        print(f"读取Excel文件时出错: {str(e)}")
        return None


def read_urls_from_txt(file_path):
    """从纯文本文件读取URL列表，每行一条"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        print(f"从TXT读取到 {len(lines)} 个URL")
        return lines
    except Exception as e:
        print(f"读取TXT文件时出错: {str(e)}")
        return None

def save_results_to_excel(results, output_path):
    """保存下载结果到Excel文件"""
    try:
        df = pd.DataFrame(results)
        result_file = os.path.join(output_path, f'下载结果_{time.strftime("%Y%m%d_%H%M%S")}.xlsx')
        df.to_excel(result_file, index=False)
        print(f"\n下载结果已保存到: {result_file}")
    except Exception as e:
        print(f"保存结果文件时出错: {str(e)}")


def get_valid_path():
    """获取有效的保存路径"""
    while True:
        path = input("请输入保存视频的完整路径: ").strip()
        if not path:
            print("错误：请输入有效的保存路径！")
            continue

        path = os.path.abspath(path)

        try:
            if not os.path.exists(path):
                os.makedirs(path)
            if os.access(path, os.W_OK):
                return path
            else:
                print("错误：没有写入权限，请选择其他路径")
        except Exception as e:
            print(f"错误：无效的路径 ({str(e)})")


def get_resolution_choice():
    """获取用户选择的分辨率"""
    while True:
        print("\n请选择下载视频的分辨率：")
        print("1. 720p")
        print("2. 1080p")
        print("3. 1440p")
        choice = input("请输入选择（1-3）: ").strip()

        resolution_map = {
            '1': '720p',
            '2': '1080p',
            '3': '1440p'
        }

        if choice in resolution_map:
            return resolution_map[choice]
        print("无效的选择，请重新输入！")


def main():
    parser = argparse.ArgumentParser(description='YouTube 批量视频下载器')
    parser.add_argument('-i', '--input', required=True, help='URL列表文件 (.xlsx/.xls/.txt) 或逗号分隔的URL')
    parser.add_argument('-o', '--output', default='videos', help='下载目录 (默认: videos)')
    parser.add_argument('-r', '--resolution', default='1080p', choices=['720p', '1080p', '1440p'], help='视频分辨率 (默认: 1080p)')
    parser.add_argument('-p', '--proxy', help='代理地址 (如: http://127.0.0.1:7890)')
    parser.add_argument('-n', '--max', type=int, help='最多下载视频数量')
    parser.add_argument('--no-aria2', action='store_true', help='不使用 aria2c 加速')
    # 字幕相关参数
    parser.add_argument('--sub-lang', default='zh-Hans,en', help='字幕语言，逗号分隔 (默认: zh-Hans,en)')
    parser.add_argument('--whisper-model', default='medium',
                        choices=['tiny', 'base', 'small', 'medium', 'large-v3'],
                        help='WhisperX 模型 (默认: medium, 可选: large-v3)')
    parser.add_argument('--whisper-device', default='auto',
                        choices=['auto', 'cpu', 'cuda'],
                        help='WhisperX 运行设备 (默认: auto)')
    parser.add_argument('--no-subs', action='store_true', help='不下载字幕')
    parser.add_argument('--proxy-file', default=None,
                        help='代理池文件（每行一个代理地址），支持 # 注释，自动轮换')
    BROWSERS = ['chrome', 'edge', 'firefox', 'brave', 'opera']

    def _browser_type(value):
        # 支持 yt-dlp 原生语法: chrome:Profile 1、chrome+keyring:Profile:container
        base = value.split(':')[0].split('+')[0]
        if base not in BROWSERS:
            raise argparse.ArgumentTypeError(
                f"无效的浏览器: '{base}'，可用值: {', '.join(BROWSERS)}")
        return value

    parser.add_argument('--cookies-from-browser', default=None, type=_browser_type,
                        help='从浏览器读取已登录 cookie（绕过机器人检测），支持 browser:Profile 语法')
    parser.add_argument('--cookies', default=None,
                        help='cookie 文件路径（Netscape 格式），由浏览器插件导出')

    args = parser.parse_args()

    # 解析输入源
    if os.path.isfile(args.input):
        urls = read_urls_from_file(args.input)
        if not urls:
            sys.exit(1)
    else:
        # 逗号分隔的URL
        urls = [u.strip() for u in args.input.split(',') if u.strip()]
        print(f"从命令行读取到 {len(urls)} 个URL")

    if not urls:
        print("错误：没有找到有效的URL")
        sys.exit(1)

    # 限制下载数量
    if args.max and args.max > 0:
        urls = urls[:args.max]
        print(f"限制下载数量: {len(urls)}")

    # 确保输出目录存在
    output_path = os.path.abspath(args.output)
    os.makedirs(output_path, exist_ok=True)

    # 构建下载选项
    ydl_opts_base = {}
    if not args.no_aria2:
        ydl_opts_base['external_downloader'] = 'aria2c'
        ydl_opts_base['external_downloader_args'] = [
            '--min-split-size=1M',
            '--max-connection-per-server=16',
            '--split=16',
            '--max-concurrent-downloads=3',
            '--continue=true',
        ]

    if args.proxy:
        ydl_opts_base['proxy'] = args.proxy
        if not args.no_aria2:
            ydl_opts_base['external_downloader_args'].append(f'--all-proxy={args.proxy}')

    # 代理池加载
    proxy_pool = None
    if args.proxy_file:
        proxy_pool = load_proxy_pool(args.proxy_file)
        if proxy_pool:
            print(f"已加载 {len(proxy_pool)} 个代理，启用自动轮换")
        else:
            print(f"警告：代理池文件为空或无法读取: {args.proxy_file}")

    # 字幕配置
    sub_langs, ydl_sub_format = get_subtitle_langs(args.sub_lang)
    device = get_device(args.whisper_device)
    print(f"\nWhisperX 设备: {device} | 模型: {args.whisper_model}")

    # 开始下载
    print(f"\n开始下载 {len(urls)} 个视频到: {output_path}")
    print(f"分辨率: {args.resolution}")
    if not args.no_subs:
        print(f"字幕语言: {args.sub_lang}")
    if args.cookies_from_browser:
        print(f"Cookie: 从 {args.cookies_from_browser} 浏览器读取")
    elif args.cookies:
        print(f"Cookie: {args.cookies}")

    # tqdm 进度回调适配器
    pbar_wrapper = [None]  # 用列表包裹以便内部修改

    def tqdm_callback(progress, status):
        if pbar_wrapper[0]:
            pct = int(progress * 100)
            pbar_wrapper[0].set_postfix_str(f"{pct}% {status}")

    with tqdm(total=len(urls), desc="下载进度", unit="个") as pbar:
        pbar_wrapper[0] = pbar

        results = batch_download(
            urls,
            output_path,
            args.resolution,
            proxy=args.proxy if not args.proxy_file else None,
            progress_callback=tqdm_callback,
            sub_langs=ydl_sub_format if not args.no_subs else None,
            no_subs=args.no_subs,
            proxy_pool=proxy_pool,
            cookies_from_browser=args.cookies_from_browser,
            cookies_file=args.cookies,
        )

        # 更新进度条到完成
        for _ in results:
            pbar.update(1)

    # 保存结果
    save_results_to_excel(results, output_path)

    # 统计
    success = sum(1 for r in results if r['状态'] == '成功')
    print(f"\n✅ 下载完成！成功: {success}/{len(results)}")

if __name__ == "__main__":
    main()
