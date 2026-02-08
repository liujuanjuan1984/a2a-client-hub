#!/usr/bin/env python3
"""
用途：扫描 i18n 文案 key 的使用情况，并在“工作模式”下移除未使用的 key。

功能概述：
1) 从多个 locale JSON（默认同时处理中文 zh 与英文 en 的 common.json）中，递归获取所有“叶子” key，
   并生成以点分隔的路径（示例：common.save、status.active）。
2) 在指定源码目录（默认：./frontend/src）中，仅匹配
   t("ns.key") 或 t('ns.key') 两种调用形式，并统计每个 key 的使用次数；支持含参数的调用（例如 t("ns.key", {...})）。
3) 支持两种模式：
   - 检查模式（--mode check）：仅打印每个 key 及其被使用次数。
   - 工作模式（--mode work）：对使用次数为 0 的 key，从所有提供的 locale JSON 中移除对应项（会级联清理空对象）。

注意事项：
- 本脚本不进行备份，建议依赖 git 做版本管理。
- 不排序输出，按 key 收集顺序打印（按 locale 文件顺序合并去重）。
- 仅匹配 t("ns.key")/t('ns.key') 两种写法；不处理其它调用样式（如 i18n.t、<Trans> 等）。
- JSON 中的数组会被视为叶子节点整体，不深入展开。
- 默认排除顶层命名空间为 "modules" 的所有 key（该命名空间通过动态参数实现）。

示例用法：
  1) 检查模式：
     python3 scripts/i18n_usage_checker.py --mode check

  2) 工作模式（移除未使用 key）：
     python3 scripts/i18n_usage_checker.py --mode work

  3) 指定源码目录或自定义 locale 文件（可多文件）：
     python3 scripts/i18n_usage_checker.py \
       --mode check \
       --src ./frontend/src \
       --locales /path/to/zh/common.json /path/to/en/common.json

  4) 以 JSON 报表输出：
     python3 scripts/i18n_usage_checker.py --mode check --stdout-json
"""

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Tuple

DEFAULT_SRC_DIR = \
    "./frontend/src"
DEFAULT_LOCALE_FILES = [
    "./frontend/src/locales/zh/common.json",
    "./frontend/src/locales/en/common.json",
]

# Excluded top-level namespaces (do not scan or delete)
EXCLUDED_TOP_LEVEL_NAMESPACES = {"modules"}

# Matches only:
#   t("common.save")
#   t('common.save')
#   t("common.save", ...)
#   t('common.save', ...)
TRANSLATION_CALL_PATTERN = re.compile(
    r"""t\(\s*(['\"])\s*([A-Za-z0-9_.-]+)\s*\1\s*(?:,|\))""",
    re.VERBOSE,
)

SOURCE_FILE_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan i18n key usages (t('ns.key') only) and optionally remove unused keys from locale files."
        )
    )
    parser.add_argument(
        "--mode",
        choices=["check", "work"],
        default="check",
        help="check: print usage report; work: remove unused keys from locale files",
    )
    parser.add_argument(
        "--src",
        default=DEFAULT_SRC_DIR,
        help="Source directory to scan (default: project frontend src)",
    )
    parser.add_argument(
        "--locales",
        nargs="+",
        default=DEFAULT_LOCALE_FILES,
        help="List of locale JSON files to process (default: zh/en common.json)",
    )
    parser.add_argument(
        "--stdout-json",
        action="store_true",
        help="Output a JSON report to stdout instead of plain lines",
    )
    return parser.parse_args()


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Dict[str, Any]) -> None:
    # No backup by request; rely on git
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_leaf(value: Any) -> bool:
    # Treat non-dict as leaf. Arrays are leaves (kept whole).
    return not isinstance(value, dict)


def flatten_keys(obj: Dict[str, Any]) -> List[str]:
    """Return dot-joined leaf paths in the order encountered in the dict."""
    flat: List[str] = []

    def dfs(node: Any, prefix: List[str]) -> None:
        if is_leaf(node):
            if prefix:
                flat.append(".".join(prefix))
            return
        for k, v in node.items():  # dict preserves insertion order in Py3.7+
            dfs(v, prefix + [str(k)])

    dfs(obj, [])
    return flat


def iter_source_files(root: str) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        if "node_modules" in dirnames:
            dirnames.remove("node_modules")
        for name in filenames:
            _, ext = os.path.splitext(name)
            if ext in SOURCE_FILE_EXTENSIONS:
                yield os.path.join(dirpath, name)


def count_usages_for_keys(keys: List[str], src_dir: str) -> Dict[str, int]:
    # Aggregate per-file matches; only count exact matched key strings.
    counts = {k: 0 for k in keys}

    for file_path in iter_source_files(src_dir):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, OSError):
            continue

        matches = TRANSLATION_CALL_PATTERN.findall(content)
        if not matches:
            continue
        for _, matched_key in matches:
            if matched_key in counts:
                counts[matched_key] += 1

    return counts


def remove_key_from_dict(root: Dict[str, Any], dotted_key: str) -> bool:
    """
    Remove a dotted key path from dict. Returns True if something was removed.
    Also prunes empty dicts on the way back up to the root.
    """
    parts = dotted_key.split(".")
    stack: List[Tuple[Dict[str, Any], str]] = []
    node: Any = root

    for idx, part in enumerate(parts):
        if not isinstance(node, dict) or part not in node:
            return False
        if idx == len(parts) - 1:
            del node[part]
            prune_upwards(stack, node)
            return True
        stack.append((node, part))
        node = node[part]
    return False


def prune_upwards(stack: List[Tuple[Dict[str, Any], str]], current: Dict[str, Any]) -> None:
    # After deleting a leaf, remove empty dict containers up to the root.
    while True:
        if isinstance(current, dict) and not current:
            if not stack:
                return
            parent, parent_key = stack.pop()
            if isinstance(parent.get(parent_key), dict) and not parent[parent_key]:
                del parent[parent_key]
                current = parent
                continue
            return
        return


def union_keys_in_order(locale_docs: List[Tuple[str, Dict[str, Any]]]) -> List[str]:
    """Union keys preserving first-seen order across provided locale docs."""
    seen = set()
    ordered: List[str] = []
    for _, doc in locale_docs:
        for k in flatten_keys(doc):
            # exclude keys under certain top-level namespaces
            top = k.split(".", 1)[0] if "." in k else k
            if top in EXCLUDED_TOP_LEVEL_NAMESPACES:
                continue
            if k not in seen:
                seen.add(k)
                ordered.append(k)
    return ordered


def main() -> None:
    args = parse_args()

    # Load locale docs
    locale_docs: List[Tuple[str, Dict[str, Any]]] = []
    for path in args.locales:
        if not os.path.isfile(path):
            print(f"[WARN] Locale file not found: {path}", file=sys.stderr)
            continue
        try:
            doc = load_json(path)
        except Exception as e:
            print(f"[ERROR] Failed to load JSON {path}: {e}", file=sys.stderr)
            continue
        locale_docs.append((path, doc))

    if not locale_docs:
        print("[ERROR] No valid locale files loaded.", file=sys.stderr)
        sys.exit(2)

    # Union keys preserving order
    all_keys = union_keys_in_order(locale_docs)

    # Count usages in source
    usage_counts = count_usages_for_keys(all_keys, args.src)

    if args.mode == "check":
        if args.stdout_json:
            print(json.dumps(usage_counts, ensure_ascii=False, indent=2))
        else:
            for key in all_keys:
                print(f"{key}\t{usage_counts.get(key, 0)}")
        return

    # work mode: remove keys with zero usage from each locale doc
    zero_keys = [k for k, c in usage_counts.items() if c == 0]
    removed_report: Dict[str, List[str]] = {path: [] for path, _ in locale_docs}

    if not zero_keys:
        if args.stdout_json:
            print(json.dumps({"message": "No unused keys", "removed": {}}, ensure_ascii=False, indent=2))
        else:
            print("No unused keys.")
        return

    for path, doc in locale_docs:
        removed_for_file: List[str] = []
        for k in zero_keys:
            if remove_key_from_dict(doc, k):
                removed_for_file.append(k)
        if removed_for_file:
            save_json(path, doc)
            removed_report[path] = removed_for_file

    if args.stdout_json:
        print(json.dumps({"removed": removed_report, "total_candidate_unused_keys": len(zero_keys)}, ensure_ascii=False, indent=2))
    else:
        print("Removed unused keys from locale files:")
        for path, keys in removed_report.items():
            if keys:
                print(f"- {path}:")
                for k in keys:
                    print(f"  {k}")
        print(f"Total candidate unused keys: {len(zero_keys)}")


if __name__ == "__main__":
    main()
