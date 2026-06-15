"""微信视频号 SPH 链接解析（移植自 wx-sph-parser/app/）。

导出：
- core：核心解析业务（fetch_video_profile, clean_video_url, generate_rid）
- config：模块级 SPH_COOKIE 变量 + update_cookie
- routes：FastAPI 路由
- schemas：Pydantic 模型
"""
# 当前为骨架版本（Task 2.1）。core / config / routes / schemas 待 Task 2.2-2.5 落地。
# 落地后追加：
#   from server.sp_modules.sph_parser import core
#   from server.sp_modules.sph_parser.config import (SPH_COOKIE, get_cookie, update_cookie)
#   from server.sp_modules.sph_parser.routes import router
#   __all__ = ["core", "router", "SPH_COOKIE", "get_cookie", "update_cookie"]
__all__: list[str] = []
