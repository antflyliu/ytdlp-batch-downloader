#!/usr/bin/env python3
"""
WhisperX 子进程包装器
在独立进程中运行 WhisperX，避免 pyannote.audio 在 Windows 上的崩溃影响主进程
"""
import sys
import os


def generate_subtitle(video_path, output_dir, model_name, device, compute_type):
    try:
        import whisperx
    except Exception as e:
        print(f"ERROR:WhisperX 无法导入，请先安装: pip install whisperx", file=sys.stderr)
        print(f"ERROR:详情: {e}", file=sys.stderr)
        return 1

    try:
        # 加载模型
        model = whisperx.load_model(model_name, device=device, compute_type=compute_type)

        # 加载音频
        audio = whisperx.load_audio(video_path)

        # 转写
        result = model.transcribe(audio)

        # 对齐时间轴（跳过，pyannote 不稳定）
        # 导出 SRT
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        srt_path = os.path.join(output_dir, f"{base_name}.srt")

        def format_timestamp(seconds):
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            millis = int((seconds % 1) * 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

        segments = result.get("segments", [])
        if not segments:
            print("WARNING:No speech detected, skipping SRT", file=sys.stderr)
            del model
            return 1

        with open(srt_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                start = seg.get("start", 0)
                end = seg.get("end", 0)
                text = seg.get("text", "").strip()
                f.write(f"{i}\n")
                f.write(f"{format_timestamp(start)} --> {format_timestamp(end)}\n")
                f.write(f"{text}\n\n")

        del model
        # 只有实际写了内容才算成功
        if os.path.getsize(srt_path) > 0:
            print(f"SUCCESS:{srt_path}")
            return 0
        else:
            print("ERROR:SRT file is empty", file=sys.stderr)
            return 1
    except Exception as e:
        print(f"ERROR:{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 6:
        print("Usage: whisperx_worker.py <video_path> <output_dir> <model_name> <device> <compute_type>")
        sys.exit(1)

    video_path = sys.argv[1]
    output_dir = sys.argv[2]
    model_name = sys.argv[3]
    device = sys.argv[4]
    compute_type = sys.argv[5]

    sys.exit(generate_subtitle(video_path, output_dir, model_name, device, compute_type))
