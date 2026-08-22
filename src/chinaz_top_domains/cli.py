from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from filelock import FileLock, Timeout

from . import __version__
from .crawler import BASE_URL, ChinazCrawler, CrawlError, FullCrawlResult, SiteEntry
from .integrity import IntegrityError, sha256_file, verify_output_directory

DEFAULT_SNAPSHOTS = (500, 10_000, 100_000)


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("必须大于或等于 1")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("不能小于 0")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("不能小于 0")
    return parsed


def snapshot_limits(value: str) -> tuple[int, ...]:
    try:
        values = {positive_int(item.strip()) for item in value.split(",") if item.strip()}
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是逗号分隔的正整数") from exc
    if not values:
        raise argparse.ArgumentTypeError("至少指定一个快照数量")
    return tuple(sorted(values))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chinaz-top-domains",
        description="抓取 ChinaZ 网站总排名，输出归一化并去重的注册域名。",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--limit", type=positive_int, help="输出指定数量的唯一注册域名（默认：500）")
    mode.add_argument(
        "--full",
        action="store_true",
        help="抓取完整榜单一次，并生成多个快照和完整结果",
    )
    mode.add_argument(
        "--verify-output",
        type=Path,
        metavar="DIR",
        help="验证完整结果目录的哈希、计数、顺序和前缀关系",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="输出目录（默认：output）",
    )
    parser.add_argument(
        "--workers",
        type=positive_int,
        help="并发请求数（指定数量模式默认：4；全量模式默认：1）",
    )
    parser.add_argument(
        "--interval",
        type=non_negative_float,
        help="相邻请求的最小间隔秒数（指定数量模式默认：0.5；全量模式默认：2）",
    )
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=20.0,
        help="单次请求超时秒数（默认：20）",
    )
    parser.add_argument(
        "--retries",
        type=non_negative_int,
        default=3,
        help="失败重试次数（默认：3）",
    )
    parser.add_argument(
        "--snapshots",
        type=snapshot_limits,
        help="全量模式的快照数量，使用逗号分隔（默认：500,10000,100000）",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="可选页面缓存根目录；全量模式自动按榜单更新日期分层",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="全量模式忽略现有同周期结果并重新生成",
    )
    return parser


def _atomic_write(path: Path, writer: Callable[[TextIO], None], *, newline: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig" if path.suffix == ".csv" else "utf-8",
            newline=newline,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            writer(handle)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def write_outputs(entries: list[SiteEntry], output_dir: Path) -> tuple[Path, Path]:
    domains_path = output_dir / "domains.txt"
    ranking_path = output_dir / "ranking.csv"

    def write_domains(handle: TextIO) -> None:
        for entry in entries:
            handle.write(f"{entry.domain}\n")

    def write_ranking(handle: TextIO) -> None:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["normalized_rank", "source_rank", "domain", "hostname", "name", "page"])
        for entry in entries:
            writer.writerow(
                [
                    entry.normalized_rank,
                    entry.source_rank,
                    entry.domain,
                    entry.hostname,
                    entry.name,
                    entry.page,
                ]
            )

    _atomic_write(domains_path, write_domains)
    _atomic_write(ranking_path, write_ranking, newline="")
    return domains_path, ranking_path


def _write_domain_list(path: Path, entries: list[SiteEntry]) -> None:
    def writer(handle: TextIO) -> None:
        for entry in entries:
            handle.write(f"{entry.domain}\n")

    _atomic_write(path, writer)


def write_full_outputs(
    result: FullCrawlResult,
    output_dir: Path,
    snapshots: tuple[int, ...] = DEFAULT_SNAPSHOTS,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_manifest: dict[str, dict[str, object]] = {}

    for requested in snapshots:
        path = output_dir / f"top{requested}.txt"
        selected = result.entries[:requested]
        _write_domain_list(path, selected)
        snapshot_manifest[path.name] = {
            "requested": requested,
            "actual": len(selected),
            "complete": len(selected) == requested,
            "sha256": sha256_file(path),
        }

    all_path = output_dir / "all.txt"
    _write_domain_list(all_path, result.entries)

    ranking_path = output_dir / "ranking.csv"

    def write_ranking(handle: TextIO) -> None:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["normalized_rank", "source_rank", "domain", "hostname", "name", "page"])
        for entry in result.entries:
            writer.writerow(
                [
                    entry.normalized_rank,
                    entry.source_rank,
                    entry.domain,
                    entry.hostname,
                    entry.name,
                    entry.page,
                ]
            )

    _atomic_write(ranking_path, write_ranking, newline="")

    manifest = {
        "schema_version": 1,
        "tool_version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": BASE_URL,
        "source_updated_at": result.source_updated_at,
        "source_update_dates": list(result.source_update_dates),
        "source_entries": result.source_entries,
        "unique_domains": len(result.entries),
        "fetched_pages": result.fetched_pages,
        "max_pages": result.max_pages,
        "snapshots": snapshot_manifest,
        "all": {
            "file": all_path.name,
            "actual": len(result.entries),
            "sha256": sha256_file(all_path),
        },
        "ranking": {
            "file": ranking_path.name,
            "rows": len(result.entries),
            "sha256": sha256_file(ranking_path),
        },
    }
    manifest_path = output_dir / "manifest.json"

    def write_manifest(handle: TextIO) -> None:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    _atomic_write(manifest_path, write_manifest)
    return manifest_path


def manifest_is_current_and_valid(
    path: Path,
    source_updated_at: str,
    max_pages: int | None = None,
) -> bool:
    try:
        manifest = verify_output_directory(path.parent)
        if manifest.get("source_updated_at") != source_updated_at:
            return False
        if manifest.get("tool_version") != __version__:
            return False
        if max_pages is not None and manifest.get("max_pages") != max_pages:
            return False

    except (IntegrityError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return True


def _run(args: argparse.Namespace, output_dir: Path) -> int:
    workers = args.workers if args.workers is not None else (1 if args.full else 4)
    interval = args.interval if args.interval is not None else (2.0 if args.full else 0.5)

    if args.verify_output is not None:
        manifest = verify_output_directory(args.verify_output.resolve())
        print(
            f"结果校验通过：{manifest['unique_domains']} 个唯一域名；"
            f"源榜单日期 {manifest['source_updated_at']}。"
        )
        return 0

    if args.full:
        with ChinazCrawler(
            workers=1,
            interval=interval,
            timeout=args.timeout,
            retries=args.retries,
        ) as inspector:
            source = inspector.inspect_source()

        manifest_path = output_dir / "manifest.json"
        if not args.force and manifest_is_current_and_valid(
            manifest_path,
            source.updated_at,
            source.max_pages,
        ):
            print(f"榜单更新日期仍为 {source.updated_at}；现有结果校验通过，无需重新抓取。")
            return 0

        cache_dir = None
        if args.cache_dir is not None:
            cache_dir = args.cache_dir.resolve() / source.updated_at

        def show_progress(pages: int, max_pages: int, source_entries: int) -> None:
            print(
                f"\r已抓取 {pages}/{max_pages} 页；读取 {source_entries} 条原始记录。",
                end="",
                file=sys.stderr,
                flush=True,
            )

        with ChinazCrawler(
            workers=workers,
            interval=interval,
            timeout=args.timeout,
            retries=args.retries,
            cache_dir=cache_dir,
        ) as crawler:
            result = crawler.crawl_all(show_progress)
        print(file=sys.stderr)

        with ChinazCrawler(
            workers=1,
            interval=interval,
            timeout=args.timeout,
            retries=args.retries,
        ) as final_inspector:
            final_source = final_inspector.inspect_source()
        if final_source != source:
            raise CrawlError(
                "the ranking metadata changed between inspection and the complete crawl"
            )

        snapshots = args.snapshots or DEFAULT_SNAPSHOTS
        manifest_path = write_full_outputs(result, output_dir, snapshots)
        print(
            f"已输出 {len(result.entries)} 个唯一注册域名；"
            f"抓取 {result.fetched_pages}/{result.max_pages} 页。"
        )
        print(f"结果清单：{manifest_path}")
        return 0

    cache_dir = args.cache_dir.resolve() if args.cache_dir is not None else None
    with ChinazCrawler(
        workers=workers,
        interval=interval,
        timeout=args.timeout,
        retries=args.retries,
        cache_dir=cache_dir,
    ) as crawler:
        limit = args.limit or 500
        entries, fetched_pages, max_pages = crawler.crawl(limit)
    domains_path, ranking_path = write_outputs(entries, output_dir)
    print(f"已输出 {len(entries)} 个唯一注册域名；抓取 {fetched_pages}/{max_pages} 页。")
    print(f"域名列表：{domains_path}")
    print(f"排名明细：{ranking_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = build_parser().parse_args(argv)
    if args.snapshots is not None and not args.full:
        print("错误：--snapshots 只能与 --full 一起使用。", file=sys.stderr)
        return 2
    if args.force and not args.full:
        print("错误：--force 只能与 --full 一起使用。", file=sys.stderr)
        return 2

    output_dir = (
        args.verify_output.resolve()
        if args.verify_output is not None
        else args.output_dir.resolve()
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir.with_name(f".{output_dir.name}.lock")
    try:
        with FileLock(lock_path, timeout=0):
            return _run(args, output_dir)
    except Timeout:
        print(f"抓取失败：已有任务持有锁 {lock_path}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("抓取已取消；已缓存页面可用于续跑。", file=sys.stderr)
        return 130
    except (CrawlError, IntegrityError, OSError, ValueError) as exc:
        print(f"抓取失败：{exc}", file=sys.stderr)
        return 1
