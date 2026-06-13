# config.template.json — 全局配置模板

> 这是 `config.json` 的脱敏模板。新部署或拉取本仓库时，请拷贝本文件为 `config.json` 并按需填入真实值。
> **不要把含真实凭据的 `config.json` 提交到仓库**。

## 字段分类速查

| 分组 | 字段数 | 主要字段 | 是否加密 |
|---|---|---|---|
| 通知 Webhook | 4 | `global_feishu_url` / `global_dingtalk_url` / `global_dingtalk_sign_secret` / `global_wecom_url` / `global_telegram_token` / `global_telegram_chat_id` | 是（webhook URL） |
| 监控运维 | 11 | `default_fetch_mode` / `default_scan_interval` / `quota_budget_per_day` / `channel_meta_max_age_days` / `scan_jitter_seconds` / `quota_alert_thresholds` 等 | 否 |
| 下载 | 3 | `download_cookies_file` / `download_output_path` / `default_sub_langs` | 否 |
| 系统动态代理 | 16 | `system_dynamic_proxy_enabled` / `apply_dynamic_proxy_to_*` / `manual_*_route_policy` / `default_proxy_*` / `candidate_*` 等 | 否 |
| LLM | 6 | `llm_provider` / `llm_api_key` / `llm_model` / `llm_base_url` / `llm_min_score` / `llm_category` | **是**（api_key） |
| 视频切片增强 | 4 | `clip_embed_thumbnail` / `clip_embed_subtitle` / `clip_adapt_aspect_ratio` / `clip_thumbnail_quality` | 否 |
| 自动切片 | 2 | `auto_clip_enabled` / `auto_clip_notify_enabled` | 否 |
| Whisper | 8 | `whisper_provider` / `whisper_base_url` / `whisper_api_key` / `whisper_model` 等 | 否（暂不加密） |
| AI 文章生成 | 12 | `article_output_dir` / `article_subtitle_*` / `gmail_oauth_*` / `article_*_prompt_*` | 部分加密（gmail secret） |
| 视频生成 | 6 | `tts_provider` / `local_tts_url` / `video_gen_output_dir` / `video_gen_default_*` | 否 |
| 语音 Provider | 35 | `voice_provider` / `voice_fallback_order` / `voice_*` / `openai_speech_*` / `azure_speech_*` / `minimax_speech_*` / `voxcpm_*` / `vibevoice_*` | 部分加密（各 provider api_key） |
| 配图 | 11 | `image_generation_provider` / `image_generation_fallback_order` / `minimax_*` / `openai_image_*` / `gemini_*` | 部分加密（api_key） |
| 微信公众号发布 | 17 | `wechat_app_id` / `wechat_app_secret` / `wechat_default_*` / `wechat_baoyu_*` / `wechat_publish_*` / `wechat_need_open_comment` | **是**（app_secret） |
| 微信公众号采集 | 6 | `wechat_exporter_*` / `wechat_collection_*` | 部分加密（auth_key） |
| 资源嗅探 | 2 | `proxy_sniffer_enabled` / `proxy_sniffer_port` | 否 |
| 加速 | 1 | `enable_aria2` | 否 |

> 「加密」字段：保存时由 `config/settings.py::_encrypt_config_*` 自动包成 `enc:gAAAAA...` Fernet token；模板里留空字符串即可，运行时由用户在前端填入。

## 输出目录（必看）

`article_output_dir` / `video_gen_output_dir` / `voice_output_dir` / `wechat_collection_output_dir` 四个字段若留空字符串，运行时由 `config/settings.py::_config_default()` 自动落到 `get_data_dir()/ai-articles`、`get_data_dir()/video-gen`、`get_data_dir()/voice`、`get_data_dir()/wechat-articles`。

若想覆盖默认目录，请填绝对路径，例如：

- Linux/macOS：`/var/lib/ytdlp-batch-downloader/ai-articles`
- Windows：`D:/data/ai-articles`（推荐正斜杠，反斜杠需在 JSON 里转义成 `\\`）

**模板刻意不写入任何绝对路径**，避免误把开发机路径随仓库流转。

## 最低可运行配置

如果你只想先跑起来再慢慢调，下面 4 个字段最低限度必填：

1. `llm_provider` — 例如 `"qwen"` / `"openai"` / `"gemini"` 之一
2. `llm_api_key` — 对应 provider 的 API key（首次保存后会被自动加密）
3. `llm_model` — 例如 `"qwen-plus"` / `"gpt-4o"`
4. `llm_base_url` — provider 的 API endpoint，留空走官方

其它字段都有合理默认值（`config/settings.py::_config_default()`），留空即可。

## 从模板生成 config.json

```bash
# 1) 拷贝模板为本地 config.json
cp config.template.json config.json   # Linux/macOS
copy config.template.json config.json  # Windows cmd
# 2) 启动程序，登录后端「配置中心」页填入真实 API key 等
# 3) 保存时 _encrypt_config_* 会把 *_api_key、webhook URL 等加密写入 config.json
```

## 注意事项

- **不要**把生成的 `config.json` 加入 `git add` / `git commit`。
- 若 `config.json` 误提交，可考虑 `git rm --cached config.json` + 加入 `.gitignore`；并立即到对应 provider 控制台**轮换所有泄露的 key**。
- 历史提交中可能已存在含真实 `enc:` 字段的 `config.json`；合并或回滚时需人工核对，避免把本机私钥推到远端。
