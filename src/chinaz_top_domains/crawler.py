from __future__ import annotations

import math
import os
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import tldextract
from selectolax.parser import HTMLParser

BASE_URL = "https://top.chinaz.com/all/"
PAGE_URL_TEMPLATE = "https://top.chinaz.com/all/index_{page}.html"
USER_AGENT = "chinaz-top-domains/0.1 (unofficial ranking collector)"

_PAGE_RE = re.compile(r"/all/index_(\d+)\.html(?:[?#]|$)", re.IGNORECASE)
_UPDATE_RE = re.compile(r"网站排行榜\s*\(\s*更新[：:]\s*(\d{4}-\d{2}-\d{2})\s*\)")


class CrawlError(RuntimeError):
    """Raised when the ranking cannot be fetched or parsed safely."""


@dataclass(frozen=True, slots=True)
class SiteEntry:
    normalized_rank: int
    source_rank: int
    name: str
    hostname: str
    domain: str
    page: int


@dataclass(frozen=True, slots=True)
class ParsedSite:
    source_rank: int
    name: str
    hostname: str
    domain: str
    page: int


@dataclass(frozen=True, slots=True)
class FullCrawlResult:
    entries: list[SiteEntry]
    fetched_pages: int
    max_pages: int
    source_entries: int
    source_updated_at: str


@dataclass(frozen=True, slots=True)
class SourceInfo:
    max_pages: int
    updated_at: str


def normalize_hostname(value: str) -> str | None:
    candidate = value.strip().strip(".")
    if not candidate:
        return None

    if "://" not in candidate:
        candidate = f"//{candidate}"
    hostname = urlsplit(candidate).hostname
    if not hostname:
        return None

    hostname = hostname.rstrip(".").lower()
    try:
        ip_address(hostname)
    except ValueError:
        pass
    else:
        return None

    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return None


def registrable_domain(hostname: str, extractor: tldextract.TLDExtract) -> str | None:
    extracted = extractor(hostname)
    if not extracted.domain or not extracted.suffix:
        return None
    return extracted.top_domain_under_public_suffix.lower()


def parse_max_pages(html: str) -> int:
    tree = HTMLParser(html)
    pages = [1]
    for link in tree.css(".ListPageWrap a"):
        href = link.attributes.get("href", "")
        match = _PAGE_RE.search(href)
        if match:
            pages.append(int(match.group(1)))
    return max(pages)


def parse_update_date(html: str) -> str | None:
    match = _UPDATE_RE.search(HTMLParser(html).text(separator=" ", strip=True))
    return match.group(1) if match is not None else None


def parse_page(
    html: str,
    page: int,
    extractor: tldextract.TLDExtract | None = None,
) -> list[ParsedSite]:
    extractor = extractor or tldextract.TLDExtract(suffix_list_urls=())
    tree = HTMLParser(html)
    parsed: list[ParsedSite] = []

    for item in tree.css(".TopListCent-listWrap .listCentent li"):
        hostname_node = item.css_first(".rightTxtHead .col-gray")
        rank_node = item.css_first(".RtCRateCent strong")
        name_node = item.css_first(".rightTxtHead a")
        if hostname_node is None or rank_node is None:
            continue

        hostname = normalize_hostname(hostname_node.text(strip=True))
        if hostname is None:
            continue
        domain = registrable_domain(hostname, extractor)
        if domain is None:
            continue

        rank_text = rank_node.text(strip=True).replace(",", "")
        if not rank_text.isdigit():
            continue

        parsed.append(
            ParsedSite(
                source_rank=int(rank_text),
                name=name_node.text(strip=True) if name_node is not None else "",
                hostname=hostname,
                domain=domain,
                page=page,
            )
        )

    return parsed


def deduplicate(entries: list[ParsedSite], limit: int | None = None) -> list[SiteEntry]:
    unique: list[SiteEntry] = []
    seen: set[str] = set()
    for entry in sorted(entries, key=lambda row: (row.source_rank, row.page)):
        if entry.domain in seen:
            continue
        seen.add(entry.domain)
        unique.append(
            SiteEntry(
                normalized_rank=len(unique) + 1,
                source_rank=entry.source_rank,
                name=entry.name,
                hostname=entry.hostname,
                domain=entry.domain,
                page=entry.page,
            )
        )
        if limit is not None and len(unique) >= limit:
            break
    return unique


def validate_source_ranks(entries: list[ParsedSite]) -> None:
    ranks = sorted(entry.source_rank for entry in entries)
    if not ranks or ranks[0] != 1:
        raise CrawlError("the complete ranking did not start at source rank 1")
    for expected, actual in enumerate(ranks, start=1):
        if actual != expected:
            raise CrawlError(
                f"the complete ranking was not contiguous at source rank {expected}; got {actual}"
            )


class ChinazCrawler:
    def __init__(
        self,
        *,
        workers: int = 4,
        interval: float = 0.5,
        timeout: float = 20.0,
        retries: int = 3,
        cache_dir: Path | None = None,
    ) -> None:
        if workers < 1:
            raise ValueError("workers must be at least 1")
        if interval < 0:
            raise ValueError("interval cannot be negative")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if retries < 0:
            raise ValueError("retries cannot be negative")

        self.workers = workers
        self.interval = interval
        self.retries = retries
        self.cache_dir = cache_dir
        self._request_lock = threading.Lock()
        self._last_request = 0.0
        self._extractor = tldextract.TLDExtract(suffix_list_urls=())
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
            },
        )
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def __enter__(self) -> ChinazCrawler:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _wait_for_rate_limit(self) -> None:
        with self._request_lock:
            now = time.monotonic()
            delay = self.interval - (now - self._last_request)
            if delay > 0:
                time.sleep(delay)
            self._last_request = time.monotonic()

    def _fetch(self, page: int) -> str:
        cached = self._read_cache(page)
        if cached is not None:
            return cached

        url = BASE_URL if page == 1 else PAGE_URL_TEMPLATE.format(page=page)
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            self._wait_for_rate_limit()
            try:
                response = self._client.get(url)
            except httpx.TransportError as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 8))
                continue

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "not provided")
                raise CrawlError(
                    f"page {page} was rate limited with HTTP 429; Retry-After={retry_after!r}"
                )
            if response.status_code == 403:
                raise CrawlError(f"page {page} was blocked with HTTP 403")
            if 500 <= response.status_code <= 599:
                last_error = httpx.HTTPStatusError(
                    f"server returned HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 8))
                    continue
                break
            if response.status_code >= 400:
                raise CrawlError(f"page {page} returned HTTP {response.status_code}")

            if "TopListCent-listWrap" not in response.text:
                challenge_markers = ("captcha", "访问过于频繁", "安全验证", "请输入验证码")
                if any(marker in response.text.lower() for marker in challenge_markers):
                    raise CrawlError(f"page {page} returned a verification or challenge page")
                raise CrawlError(f"page {page} did not contain the ranking list")

            self._write_cache(page, response.text)
            return response.text

        raise CrawlError(f"failed to fetch page {page}: {last_error}")

    def inspect_source(self) -> SourceInfo:
        html = self._fetch(1)
        updated_at = parse_update_date(html)
        if updated_at is None:
            raise CrawlError("page 1 did not contain the ranking update date")
        return SourceInfo(max_pages=parse_max_pages(html), updated_at=updated_at)

    def _cache_path(self, page: int) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"page-{page:04d}.html"

    def _read_cache(self, page: int) -> str | None:
        path = self._cache_path(page)
        if path is None or not path.is_file():
            return None
        try:
            html = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CrawlError(f"failed to read cached page {page}: {exc}") from exc
        if "TopListCent-listWrap" not in html:
            raise CrawlError(f"cached page {page} did not contain the ranking list")
        return html

    def _write_cache(self, page: int, html: str) -> None:
        path = self._cache_path(page)
        if path is None:
            return
        temp_path = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
        try:
            temp_path.write_text(html, encoding="utf-8")
            os.replace(temp_path, path)
        except OSError as exc:
            raise CrawlError(f"failed to cache page {page}: {exc}") from exc
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _fetch_pages(self, pages: list[int]) -> dict[int, str]:
        if not pages:
            return {}
        results: dict[int, str] = {}
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {executor.submit(self._fetch, page): page for page in pages}
            for future in as_completed(futures):
                page = futures[future]
                results[page] = future.result()
        return results

    def crawl(self, limit: int) -> tuple[list[SiteEntry], int, int]:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        first_html = self._fetch(1)
        max_pages = parse_max_pages(first_html)
        parsed_by_page = {1: parse_page(first_html, 1, self._extractor)}
        if not parsed_by_page[1]:
            raise CrawlError("page 1 contained no parseable ranking entries")

        rows_per_page = len(parsed_by_page[1])
        next_page = 2
        initial_pages = min(max_pages, max(1, math.ceil(limit / rows_per_page)))

        while True:
            all_entries = [
                entry for page in sorted(parsed_by_page) for entry in parsed_by_page[page]
            ]
            unique = deduplicate(all_entries, limit)
            if len(unique) >= limit or next_page > max_pages:
                return unique, len(parsed_by_page), max_pages

            missing = limit - len(unique)
            estimated_pages = max(1, math.ceil(missing / rows_per_page))
            target_page = max(initial_pages, next_page + max(self.workers, estimated_pages) - 1)
            target_page = min(max_pages, target_page)
            pages = list(range(next_page, target_page + 1))

            for page, html in self._fetch_pages(pages).items():
                page_entries = parse_page(html, page, self._extractor)
                if not page_entries:
                    raise CrawlError(f"page {page} contained no parseable ranking entries")
                parsed_by_page[page] = page_entries
            next_page = target_page + 1

    def crawl_all(
        self,
        progress: Callable[[int, int, int], None] | None = None,
    ) -> FullCrawlResult:
        first_html = self._fetch(1)
        max_pages = parse_max_pages(first_html)
        source_updated_at = parse_update_date(first_html)
        if source_updated_at is None:
            raise CrawlError("page 1 did not contain the ranking update date")
        first_entries = parse_page(first_html, 1, self._extractor)
        if not first_entries:
            raise CrawlError("page 1 contained no parseable ranking entries")

        parsed: list[ParsedSite] = list(first_entries)
        fetched_pages = 1
        if progress is not None:
            progress(fetched_pages, max_pages, len(parsed))

        batch_size = max(20, self.workers * 5)
        for batch_start in range(2, max_pages + 1, batch_size):
            batch_end = min(max_pages, batch_start + batch_size - 1)
            pages = list(range(batch_start, batch_end + 1))
            fetched = self._fetch_pages(pages)
            for page in pages:
                page_updated_at = parse_update_date(fetched[page])
                if page_updated_at != source_updated_at:
                    raise CrawlError(
                        f"page {page} belonged to ranking update {page_updated_at!r}; "
                        f"expected {source_updated_at!r}"
                    )
                page_entries = parse_page(fetched[page], page, self._extractor)
                if not page_entries:
                    raise CrawlError(f"page {page} contained no parseable ranking entries")
                parsed.extend(page_entries)
            fetched_pages += len(pages)
            if progress is not None:
                progress(fetched_pages, max_pages, len(parsed))

        validate_source_ranks(parsed)
        return FullCrawlResult(
            entries=deduplicate(parsed),
            fetched_pages=fetched_pages,
            max_pages=max_pages,
            source_entries=len(parsed),
            source_updated_at=source_updated_at,
        )
