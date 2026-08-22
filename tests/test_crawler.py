import json

import httpx
import pytest

from chinaz_top_domains import __version__
from chinaz_top_domains.cli import manifest_is_current_and_valid, write_full_outputs
from chinaz_top_domains.crawler import (
    ChinazCrawler,
    CrawlError,
    FullCrawlResult,
    ParsedSite,
    RejectedSite,
    SiteEntry,
    deduplicate,
    normalize_hostname,
    parse_max_pages,
    parse_page,
    parse_ranked_hostnames,
)

HTML = """
<p>网站排行榜(更新：2026-08-16)</p>
<div class="TopListCent-listWrap">
  <ul class="listCentent">
    <li>
      <h3 class="rightTxtHead"><a>示例一</a><span class="col-gray">www.example.com</span></h3>
      <div class="RtCRateCent"><strong>1</strong></div>
    </li>
    <li>
      <h3 class="rightTxtHead"><a>示例二</a><span class="col-gray">blog.example.com</span></h3>
      <div class="RtCRateCent"><strong>2</strong></div>
    </li>
    <li>
      <h3 class="rightTxtHead"><a>新浪</a><span class="col-gray">sina.com.cn</span></h3>
      <div class="RtCRateCent"><strong>3</strong></div>
    </li>
  </ul>
</div>
<div class="ListPageWrap">
  <a href="/all/index_2.html">2</a>
  <a href="https://top.chinaz.com/all/index_3457.html">3457</a>
</div>
"""


def test_parse_page_and_public_suffix_normalization() -> None:
    rows = parse_page(HTML, page=1)

    assert [(row.source_rank, row.hostname, row.domain) for row in rows] == [
        (1, "www.example.com", "example.com"),
        (2, "blog.example.com", "example.com"),
        (3, "sina.com.cn", "sina.com.cn"),
    ]


def test_parse_max_pages() -> None:
    assert parse_max_pages(HTML) == 3457


def test_parse_ranked_hostnames_preserves_source_entries() -> None:
    assert parse_ranked_hostnames(HTML) == [
        (1, "www.example.com"),
        (2, "blog.example.com"),
        (3, "sina.com.cn"),
    ]


def test_deduplicate_keeps_best_source_rank() -> None:
    rows = [
        ParsedSite(2, "second", "blog.example.com", "example.com", 1),
        ParsedSite(1, "first", "www.example.com", "example.com", 1),
        ParsedSite(3, "other", "other.cn", "other.cn", 1),
    ]

    result = deduplicate(rows, limit=2)

    assert [(row.normalized_rank, row.source_rank, row.domain) for row in result] == [
        (1, 1, "example.com"),
        (2, 3, "other.cn"),
    ]


def test_normalize_hostname_rejects_ip_addresses() -> None:
    assert normalize_hostname("https://WWW.Example.COM/path") == "www.example.com"
    assert normalize_hostname("127.0.0.1") is None


def test_crawl_all_fetches_each_page_once(monkeypatch) -> None:
    second_page = HTML.replace("www.example.com", "second.example.net").replace(
        "<strong>1</strong>", "<strong>4</strong>"
    )
    second_page = second_page.replace("<strong>2</strong>", "<strong>5</strong>").replace(
        "<strong>3</strong>", "<strong>6</strong>"
    )
    first_page = HTML.replace("index_3457.html", "index_2.html").replace(">3457<", ">2<")
    pages = {1: first_page, 2: second_page}
    requested: list[int] = []
    progress: list[tuple[int, int, int]] = []

    with ChinazCrawler(workers=1, interval=0) as crawler:

        def fake_fetch(page: int) -> str:
            requested.append(page)
            return pages[page]

        monkeypatch.setattr(crawler, "_fetch", fake_fetch)
        result = crawler.crawl_all(lambda *values: progress.append(values))

    assert requested == [1, 2]
    assert result.fetched_pages == 2
    assert result.max_pages == 2
    assert result.source_entries == 6
    assert result.parsed_source_entries == 6
    assert result.rejected_entries == ()
    assert [entry.domain for entry in result.entries] == [
        "example.com",
        "sina.com.cn",
        "example.net",
    ]
    assert progress[-1] == (2, 2, 6)


def test_write_full_outputs_marks_short_snapshot(tmp_path) -> None:
    entries = [
        SiteEntry(1, 1, "one", "www.one.com", "one.com", 1),
        SiteEntry(2, 2, "two", "two.cn", "two.cn", 1),
        SiteEntry(3, 3, "three", "blog.three.net", "three.net", 1),
    ]
    result = FullCrawlResult(
        entries,
        fetched_pages=1,
        max_pages=1,
        source_entries=4,
        parsed_source_entries=3,
        rejected_entries=(RejectedSite(4, "127.0.0.1", "ip_address"),),
        source_updated_at="2026-08-16",
        source_update_dates=("2026-08-16",),
    )

    manifest_path = write_full_outputs(result, tmp_path, snapshots=(2, 5))

    assert (tmp_path / "top2.txt").read_text(encoding="utf-8").splitlines() == [
        "one.com",
        "two.cn",
    ]
    assert (tmp_path / "top5.txt").read_text(encoding="utf-8").splitlines() == [
        "one.com",
        "two.cn",
        "three.net",
    ]
    assert (tmp_path / "all.txt").read_text(encoding="utf-8").splitlines() == [
        "one.com",
        "two.cn",
        "three.net",
    ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["tool_version"] == __version__
    assert manifest["snapshots"]["top5.txt"]["actual"] == 3
    assert manifest["snapshots"]["top5.txt"]["complete"] is False
    assert manifest["source_updated_at"] == "2026-08-16"
    assert manifest_is_current_and_valid(manifest_path, "2026-08-16", 1) is True
    assert manifest_is_current_and_valid(manifest_path, "2026-08-16", 2) is False

    (tmp_path / "all.txt").write_text("tampered.example\n", encoding="utf-8")
    assert manifest_is_current_and_valid(manifest_path, "2026-08-16") is False


def test_crawl_all_records_mixed_update_dates(monkeypatch) -> None:
    first_page = HTML.replace("index_3457.html", "index_2.html").replace(">3457<", ">2<")
    second_page = first_page.replace("2026-08-16", "2026-08-23")
    second_page = second_page.replace("<strong>1</strong>", "<strong>4</strong>")
    second_page = second_page.replace("<strong>2</strong>", "<strong>5</strong>")
    second_page = second_page.replace("<strong>3</strong>", "<strong>6</strong>")
    pages = {1: first_page, 2: second_page}

    with ChinazCrawler(workers=1, interval=0) as crawler:
        monkeypatch.setattr(crawler, "_fetch", lambda page: pages[page])
        result = crawler.crawl_all()

    assert result.source_update_dates == ("2026-08-16", "2026-08-23")


@pytest.mark.parametrize("status", [403, 404, 429])
def test_fetch_stops_immediately_on_non_retryable_status(status) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, request=request, headers={"Retry-After": "60"})

    with ChinazCrawler(workers=1, interval=0, retries=3) as crawler:
        crawler._client.close()
        crawler._client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(CrawlError, match=f"HTTP {status}"):
            crawler._fetch(1)

    assert calls == 1


def test_fetch_retries_server_error_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, request=request, text=HTML)

    with ChinazCrawler(workers=1, interval=0, retries=1) as crawler:
        crawler._client.close()
        crawler._client = httpx.Client(transport=httpx.MockTransport(handler))
        assert crawler._fetch(1) == HTML

    assert calls == 2
