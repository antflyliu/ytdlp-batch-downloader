import yt_dlp
from tqdm import tqdm
import os
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import time


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


def batch_download(urls, output_path, resolution, proxy=None, progress_callback=None):
    """批量下载视频的函数"""
    results = []
    total = len(urls)
    completed = 0

    ydl_opts = {
        'format': get_format_option(resolution),
        'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'ignoreerrors': True,
        'quiet': True,
        'no_warnings': True,
        'format_sort': ['vcodec:h264'],
        # 使用aria2c作为外部下载器
        'external_downloader': 'aria2c',
        'external_downloader_args': [
            '--min-split-size=1M',  # 最小分片大小
            '--max-connection-per-server=16',  # 单个服务器最大连接数
            '--split=16',  # 单个文件分成16片下载
            '--max-concurrent-downloads=3',  # 同时下载数
            '--continue=true',  # 支持断点续传
            '--optimize-concurrent-downloads=true'  # 优化并发下载
        ]
    }

    if proxy:
        ydl_opts['proxy'] = proxy
        # 为aria2c也添加代理设置
        ydl_opts['external_downloader_args'].extend([
            f'--all-proxy={proxy}'
        ])



    # 添加下载进度回调
    def download_progress_hook(d):
        if d['status'] == 'downloading':
            try:
                downloaded = d.get('downloaded_bytes', 0)
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                if total_bytes:
                    video_progress = downloaded / total_bytes
                    total_progress = (completed + video_progress) / total
                    if progress_callback:
                        progress_callback(total_progress, f"正在下载第 {completed + 1}/{total} 个视频")
            except Exception:
                pass

    ydl_opts['progress_hooks'] = [download_progress_hook]

    for i, url in enumerate(urls):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                results.append({
                    'URL': url,
                    '状态': '成功',
                    '信息': '下载成功'
                })
        except Exception as e:
            results.append({
                'URL': url,
                '状态': '失败',
                '信息': str(e)
            })

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
    print("YouTube视频批量下载器")
    print(f"已选择下载分辨率: {resolution}")

    # 获取下载数量
    while True:
        try:
            max_videos = input(f"请输入要下载的视频数量（最大{len(urls)}个，直接回车下载全部）: ").strip()
            if not max_videos:
                max_videos = None
                break
            max_videos = int(max_videos)
            if 1 <= max_videos <= len(urls):
                break
            print(f"请输入1到{len(urls)}之间的数字！")
        except ValueError:
            print("请输入有效的数字！")

    # 执行批量下载
    results = batch_download(urls, save_path, resolution, max_videos)

    # 保存下载结果
    save_results_to_excel(results, save_path)

    # 显示统计信息
    success_count = sum(1 for r in results if r['状态'] == '成功')
    print(f"\n下载完成！成功: {success_count}/{len(results)}")

if __name__ == "__main__":
    main()
