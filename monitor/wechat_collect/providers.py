from __future__ import annotations

from typing import Protocol

from monitor.wechat_collect.errors import WechatUpstreamError, safe_error_message
from monitor.wechat_collect.html_export import (
    author_match_key,
    download_article,
    is_author_name_match,
    normalize_author_name,
)
from monitor.wechat_collect.native_client import NativeMpClient
from monitor.wechat_collect.session_store import NativeSessionStore


class CollectionProvider(Protocol):
    def check_session(self) -> dict:
        raise NotImplementedError

    def logout(self) -> dict:
        raise NotImplementedError

    def search_accounts(self, keyword: str, *, begin: int = 0, size: int = 5) -> list[dict]:
        raise NotImplementedError

    def account_by_article_url(self, article_url: str) -> dict:
        raise NotImplementedError

    def list_articles(
        self,
        fakeid: str,
        *,
        keyword: str = "",
        max_articles: int = 50,
        page_size: int = 20,
        begin: int = 0,
        progress=None,
        cancel_check=None,
    ) -> list[dict]:
        raise NotImplementedError

    def download_article(self, article_url: str, export_format: str):
        raise NotImplementedError


class NativeMpProvider:
    def __init__(self, *, session_id: str, store: NativeSessionStore | None = None, http_session=None, proxy_plan=None):
        self.session_id = session_id
        self.store = store or NativeSessionStore()
        self.session = self.store.get_session(session_id)
        self.proxy_plan = proxy_plan
        self.client = NativeMpClient(self.session, http_session=http_session, proxy_plan=proxy_plan)
        self.http_session = self.client.http

    def _mark_if_session_expired(self, exc: Exception) -> None:
        if isinstance(exc, WechatUpstreamError) and exc.session_expired:
            self.store.mark_expired(self.session_id, safe_error_message(exc))

    def check_session(self) -> dict:
        try:
            return self.client.check_session()
        except Exception as exc:
            self._mark_if_session_expired(exc)
            raise

    def logout(self) -> dict:
        result: dict = {"ok": True, "upstream_ok": True}
        try:
            result.update(self.client.logout())
        except Exception as exc:
            result = {"ok": True, "upstream_ok": False, "warning": safe_error_message(exc)}
        finally:
            self.store.mark_logged_out(self.session_id)
        return result

    def search_accounts(self, keyword: str, *, begin: int = 0, size: int = 5) -> list[dict]:
        try:
            return self.client.search_accounts(keyword, begin=begin, size=size)
        except Exception as exc:
            self._mark_if_session_expired(exc)
            raise

    def account_by_article_url(self, article_url: str) -> dict:
        downloaded = download_article(
            article_url,
            "html",
            http_session=self.http_session,
            proxies=self.proxy_plan.requests_proxies if self.proxy_plan else None,
        )
        name = normalize_author_name(downloaded.metadata.get("author") or "")
        biz = downloaded.metadata.get("biz") or ""
        if not name:
            detail = "文章链接中的 __biz 不是微信公众号后台 fakeid，无法直接用于文章列表" if biz else "无法从文章链接识别公众号作者"
            raise ValueError(f"{detail}，请手动搜索公众号或输入 fakeid")
        matches = self.search_accounts(name, size=20)
        target_key = author_match_key(name)
        exact = [item for item in matches if author_match_key(item.get("nickname") or "") == target_key]
        lookup_mode = "author_exact"
        candidates = exact
        if not candidates:
            candidates = [item for item in matches if is_author_name_match(item.get("nickname") or "", name)]
            lookup_mode = "author_unique_normalized"
        if not candidates:
            detail = "文章链接中的 __biz 不是微信公众号后台 fakeid，无法直接用于文章列表；" if biz else ""
            raise ValueError(f"{detail}无法精确匹配文章作者对应的公众号，请手动搜索公众号或输入 fakeid")
        if len(candidates) > 1:
            raise ValueError("文章作者对应多个同名公众号，请手动搜索公众号或输入 fakeid")
        return {
            **candidates[0],
            "article_biz": biz,
            "article_author": name,
            "matched_name": normalize_author_name(candidates[0].get("nickname") or name),
            "lookup_mode": lookup_mode,
        }

    def list_articles(
        self,
        fakeid: str,
        *,
        keyword: str = "",
        max_articles: int = 50,
        page_size: int = 20,
        begin: int = 0,
        progress=None,
        cancel_check=None,
    ) -> list[dict]:
        try:
            return self.client.list_articles(
                fakeid,
                keyword=keyword,
                max_articles=max_articles,
                page_size=page_size,
                begin=begin,
                progress=progress,
                cancel_check=cancel_check,
            )
        except Exception as exc:
            self._mark_if_session_expired(exc)
            raise

    def list_article_page(self, fakeid: str, *, keyword: str = "", begin: int = 0, page_size: int = 20) -> dict:
        try:
            return self.client.list_article_page(fakeid, keyword=keyword, begin=begin, page_size=page_size)
        except Exception as exc:
            self._mark_if_session_expired(exc)
            raise

    def download_article(self, article_url: str, export_format: str):
        return download_article(
            article_url,
            export_format,
            http_session=self.http_session,
            proxies=self.proxy_plan.requests_proxies if self.proxy_plan else None,
        )


class ExporterApiProvider:
    def __init__(self, client):
        self.client = client

    def check_session(self) -> dict:
        return self.client.verify_auth_key()

    def logout(self) -> dict:
        return {"ok": True}

    def search_accounts(self, keyword: str, *, begin: int = 0, size: int = 5) -> list[dict]:
        raise NotImplementedError("现有 exporter API P0 不提供本地搜索入口")

    def account_by_article_url(self, article_url: str) -> dict:
        return self.client.account_by_article_url(article_url)

    def list_articles(
        self,
        fakeid: str,
        *,
        keyword: str = "",
        max_articles: int = 50,
        page_size: int = 5,
        begin: int = 0,
        progress=None,
        cancel_check=None,
    ) -> list[dict]:
        if cancel_check and cancel_check():
            return []
        return self.client.list_articles(
            fakeid,
            keyword=keyword,
            max_articles=max_articles,
            page_size=page_size,
            progress=progress,
        )

    def download_article(self, article_url: str, export_format: str):
        body, content_type = self.client.download_article(article_url, export_format)
        from monitor.wechat_collect.models import ArticleDownload

        return ArticleDownload(body=body, content_type=content_type)
