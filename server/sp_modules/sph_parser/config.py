"""sph_parser 模块级 cookie 管理。

- SPH_COOKIE：模块级变量，启动时从 config.settings.get_sph_cookie() 读取
- update_cookie(plain)：热更新内存变量 + 同步写回 config.json（加密）
- get_cookie()：仅读内存变量（不读盘）
"""
import logging

logger = logging.getLogger("sph.config")

SPH_COOKIE: str = ""


def _init_from_settings() -> str:
    """从 config.settings 读取当前 cookie，写入模块级变量。启动时调用一次。"""
    global SPH_COOKIE
    try:
        from config.settings import get_sph_cookie
        SPH_COOKIE = get_sph_cookie() or ""
    except Exception as e:
        logger.warning("[init] get_sph_cookie failed: %s, default empty", e)
        SPH_COOKIE = ""
    return SPH_COOKIE


def get_cookie() -> str:
    """返回当前内存中的 cookie（不读盘）。"""
    return SPH_COOKIE


def update_cookie(new_cookie: str) -> str:
    """热更新 cookie：写回 config.json（加密）+ 更新内存变量。"""
    new_value = new_cookie or ""
    from config.settings import set_sph_cookie
    set_sph_cookie(new_value, source="manual")  # raises on failure → memory unchanged
    global SPH_COOKIE
    SPH_COOKIE = new_value
    logger.info("[update_cookie] updated, length=%d", len(SPH_COOKIE))
    return SPH_COOKIE
