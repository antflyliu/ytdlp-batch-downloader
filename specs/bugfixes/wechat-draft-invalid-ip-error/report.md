# 微信草稿箱 invalid IP 失败提示不完整

## 现象

在 AI 创作页面选择文章任务 `article_75ba49540e84` 后，点击「保存到草稿箱」会创建 `wechat_*` 异步任务。微信接口实际返回：

`invalid ip 1.119.141.218 ipv6 ::ffff:1.119.141.218, not in whitelist`

后台日志能看到「获取 access_token 失败」，但页面发布面板只显示「草稿箱状态: error」，没有持久展示可操作的失败原因。

IP 白名单配置后，同一篇文章又进入下一阶段并返回：

`创建草稿失败: invalid media_id hint: [yTgqiA0254c6-2]`

## 根因

1. 后端直接透传微信 access token 接口的原始 `errmsg`，没有把 `40164 / invalid ip not in whitelist` 归一化成用户可执行的配置提示。
2. 前端发布面板只持久展示发布任务状态，没有单独保存和渲染 `task.error`。错误 toast 可能很快消失，刷新后用户只能看到 `error`。
3. 微信新增草稿接口要求图文消息有封面 `thumb_media_id`，且该值必须是当前公众号下的永久图片素材。`article_75ba49540e84` 的 `draft.md` 没有正文图片，任务目录也没有封面图，后端把空封面传给微信，导致 `invalid media_id`。

## 修复

- `monitor/wechat_publisher.py`：新增微信 API 错误归一化逻辑，识别 `40164` 或 `invalid ip ... not in whitelist`，提示将当前服务器出口 IP 加入微信公众号后台 IP 白名单，并保留微信原始错误。
- `monitor/wechat_publisher.py`：无封面且正文无图片时，自动在文章目录生成 `_wechat_default_cover.png`，上传为永久图片素材，再用返回的 `media_id` 创建草稿。
- `monitor/wechat_publisher.py`：识别 `invalid media_id`，提示它是图文封面 `thumb_media_id` / 永久图片素材问题。
- `frontend-vue/src/views/AiCreation.vue`：新增 `wechatPublishError` 状态，轮询发布任务时同步保存 `task.error`，并在「发布到公众号」面板内持续展示错误详情。
- `tests/test_wechat_publish_invalid_ip_guidance.py`：增加 access token invalid IP 回归测试。
- `tests/test_wechat_publish_invalid_ip_guidance.py`：增加无图文章默认封面和 `invalid media_id` 文案回归测试。
- `tests/test_ai_content_frontend_contract.py`：增加前端面板必须持久展示微信发布错误详情的契约测试。

## 验证

- `python -m pytest tests/test_wechat_publish_invalid_ip_guidance.py -q`
- `python -m pytest tests/test_wechat_publish_invalid_ip_guidance.py tests/test_ai_content_frontend_contract.py tests/test_ai_content_api_contract.py tests/test_ai_content_config_masking_contract.py -q`
- `cd frontend-vue && npx vue-tsc --noEmit`
- `cd frontend-vue && npm run build`

## 剩余风险

- 这次修复不能绕过微信官方 IP 白名单限制；仍需在微信公众号后台把实际出口 IP 加入白名单后重试。
- 当前机器如果更换网络、代理或部署环境，出口 IP 可能变化，需要以微信返回的最新 IP 为准。
- 默认封面是兜底图，只保证草稿能创建；正式发布前建议在公众号后台替换成更贴合文章内容的封面。
