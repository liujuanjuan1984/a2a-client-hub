#!/usr/bin/env python3
"""
Purpose: Detect and dedupe i18n keys whose leaf values are duplicated across zh and en.

Behavior overview:
1) Read zh and en locale JSON (defaults to frontend/src/locales/zh/common.json and en/common.json).
2) Collect leaf keys and their values. Only consider keys present in both zh and en, and exclude any
   keys whose top-level namespace is in EXCLUDED_TOP_LEVEL_NAMESPACES (default: {"modules"}).
3) Group keys by the pair (zh_value, en_value). Any group with size >= 2 is considered redundant.
4) Modes:
   - check: Print redundant groups (canonical key and its duplicates). Optionally JSON via --stdout-json.
   - work:  For each redundant group, keep the first key by zh document order as canonical, replace all
            other redundant keys in source calls t("old.key")/t('old.key') with the canonical key, then
            remove redundant keys from zh/en JSON and prune empty dicts.
5) Additionally, detect explicit empty-object entries (e.g., habitActions.status: {}) in zh/en and
   report/remove them (excluding top-level namespaces in EXCLUDED_TOP_LEVEL_NAMESPACES).

Notes:
- Only matches t("ns.key") and t('ns.key') patterns, optionally with arguments after the key.
- Arrays in JSON are treated as leaf values (kept as-is).
- No backups; rely on git.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from typing import Any, DefaultDict, Dict, Iterable, List, Tuple

DEFAULT_SRC_DIR = "./frontend/src"
DEFAULT_ZH_FILE = "./frontend/src/locales/zh/common.json"
DEFAULT_EN_FILE = "./frontend/src/locales/en/common.json"

# Excluded top-level namespaces (do not scan or delete)
EXCLUDED_TOP_LEVEL_NAMESPACES = {"modules"}

# Matches only t("common.save") / t('common.save') and with params: t("common.save", ...)
TRANSLATION_CALL_PATTERN = re.compile(
    r"""t\(\s*(['\"])\s*([A-Za-z0-9_.-]+)\s*\1\s*(?:,|\))""",
    re.VERBOSE,
)

SOURCE_FILE_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Detect duplicated i18n values (zh & en) and optionally dedupe by replacing redundant keys in source and removing them from locales."
        )
    )
    parser.add_argument(
        "--mode",
        choices=["check", "work"],
        default="check",
        help="check: print redundant groups; work: replace redundant keys in source and remove from locales",
    )
    parser.add_argument(
        "--src",
        default=DEFAULT_SRC_DIR,
        help="Source directory to scan (default: project frontend src)",
    )
    parser.add_argument(
        "--zh",
        default=DEFAULT_ZH_FILE,
        help="Path to zh/common.json (default: ./frontend/src/locales/zh/common.json)",
    )
    parser.add_argument(
        "--en",
        default=DEFAULT_EN_FILE,
        help="Path to en/common.json (default: ./frontend/src/locales/en/common.json)",
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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_leaf(value: Any) -> bool:
    return not isinstance(value, dict)


def flatten_key_values(obj: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """Return (dotted_key, leaf_value) pairs in the order encountered in the dict."""
    flat: List[Tuple[str, Any]] = []

    def dfs(node: Any, prefix: List[str]) -> None:
        if is_leaf(node):
            if prefix:
                flat.append((".".join(prefix), node))
            return
        for k, v in node.items():
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


def remove_key_from_dict(root: Dict[str, Any], dotted_key: str) -> bool:
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


def top_level_namespace_of(key: str) -> str:
    return key.split(".", 1)[0] if "." in key else key


def collect_empty_object_keys(obj: Dict[str, Any]) -> List[str]:
    """Collect keys (dot paths) whose value is an empty dict {} (excluding top-level excluded namespaces)."""
    res: List[str] = []

    def dfs(node: Any, prefix: List[str]) -> None:
        if isinstance(node, dict):
            if not node and prefix:
                key = ".".join(prefix)
                top = top_level_namespace_of(key)
                if top not in EXCLUDED_TOP_LEVEL_NAMESPACES:
                    res.append(key)
                return
            for k, v in node.items():
                dfs(v, prefix + [str(k)])

    dfs(obj, [])
    return res


def build_canonical_order_from_zh(zh_doc: Dict[str, Any]) -> List[str]:
    return [k for k, _ in flatten_key_values(zh_doc)]


def collect_pairs(zh_doc: Dict[str, Any], en_doc: Dict[str, Any]) -> Dict[str, Tuple[Any, Any]]:
    zh_items = flatten_key_values(zh_doc)
    en_items = dict(flatten_key_values(en_doc))

    key_to_pair: Dict[str, Tuple[Any, Any]] = {}
    for key, zh_val in zh_items:
        top = top_level_namespace_of(key)
        if top in EXCLUDED_TOP_LEVEL_NAMESPACES:
            continue
        if key not in en_items:
            continue
        key_to_pair[key] = (zh_val, en_items[key])
    return key_to_pair


def group_by_value_pair(key_to_pair: Dict[str, Tuple[Any, Any]]) -> List[Tuple[str, List[str], Any, Any]]:
    """
    Returns list of groups: [(canonical_key, duplicates[], zh_value, en_value), ...]
    canonical_key will be decided later based on zh order; for now we return placeholder.
    """
    pair_to_keys: DefaultDict[Tuple[Any, Any], List[str]] = defaultdict(list)
    for key, pair in key_to_pair.items():
        pair_to_keys[pair].append(key)

    groups: List[Tuple[str, List[str], Any, Any]] = []
    for (zh_val, en_val), keys in pair_to_keys.items():
        if len(keys) >= 2:
            groups.append(("", keys, zh_val, en_val))
    return groups


def decide_canonical_by_zh_order(groups: List[Tuple[str, List[str], Any, Any]], zh_order: List[str]) -> List[Tuple[str, List[str], Any, Any]]:
    index_in_zh: Dict[str, int] = {k: i for i, k in enumerate(zh_order)}
    decided: List[Tuple[str, List[str], Any, Any]] = []
    for _, keys, zh_val, en_val in groups:
        sorted_keys = sorted(keys, key=lambda k: index_in_zh.get(k, 1_000_000))
        canonical = sorted_keys[0]
        duplicates = [k for k in sorted_keys[1:]]
        decided.append((canonical, duplicates, zh_val, en_val))
    return decided


def replace_keys_in_source(src_dir: str, replacements: Dict[str, str]) -> Dict[str, int]:
    """
    replacements: map old_key -> canonical_key
    Returns per-file replacement counts; also returns total via key '__total__'.
    """
    per_file_counts: Dict[str, int] = {"__total__": 0}

    if not replacements:
        return per_file_counts

    # Precompile per-old-key patterns to avoid cross-matching
    key_to_patterns: Dict[str, re.Pattern[str]] = {}
    for old_key in replacements:
        # Match t('old_key') or t("old_key") with optional args; capture quote to preserve style
        pattern = re.compile(r"t\(\s*(['\"])\s*" + re.escape(old_key) + r"\s*\1\s*(,|\))")
        key_to_patterns[old_key] = pattern

    for file_path in iter_source_files(src_dir):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, OSError):
            continue

        original_content = content
        file_replacements = 0

        for old_key, canonical_key in replacements.items():
            pattern = key_to_patterns[old_key]

            def _sub(match: re.Match[str]) -> str:
                quote = match.group(1)
                tail = match.group(2)
                return f"t({quote}{canonical_key}{quote}{tail}"

            content, n = pattern.subn(_sub, content)
            if n:
                file_replacements += n

        if file_replacements and content != original_content:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except OSError:
                # Best-effort; skip write errors
                pass

        if file_replacements:
            per_file_counts[file_path] = file_replacements
            per_file_counts["__total__"] += file_replacements

    return per_file_counts


def remove_keys_from_locales(zh_doc: Dict[str, Any], en_doc: Dict[str, Any], keys_to_remove: List[str]) -> Dict[str, List[str]]:
    removed: Dict[str, List[str]] = {"zh": [], "en": []}
    for k in keys_to_remove:
        if remove_key_from_dict(zh_doc, k):
            removed["zh"].append(k)
        if remove_key_from_dict(en_doc, k):
            removed["en"].append(k)
    return removed


def main() -> None:
    args = parse_args()

    # Load locales
    try:
        zh_doc = load_json(args.zh)
    except Exception as e:
        print(f"[ERROR] Failed to load zh JSON {args.zh}: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        en_doc = load_json(args.en)
    except Exception as e:
        print(f"[ERROR] Failed to load en JSON {args.en}: {e}", file=sys.stderr)
        sys.exit(2)

    # Build mapping key -> (zh_value, en_value)
    key_to_pair = collect_pairs(zh_doc, en_doc)
    if not key_to_pair:
        if args.stdout_json:
            print(json.dumps({"message": "No keys in intersection or all excluded"}, ensure_ascii=False, indent=2))
        else:
            print("No keys to analyze (intersection empty or excluded).")
        return

    # Group by identical (zh, en) pairs
    raw_groups = group_by_value_pair(key_to_pair)
    # Also collect explicit empty-object keys in zh/en
    zh_empty_keys = collect_empty_object_keys(zh_doc)
    en_empty_keys = collect_empty_object_keys(en_doc)

    # Decide canonical key by zh order
    zh_order = build_canonical_order_from_zh(zh_doc)
    groups = decide_canonical_by_zh_order(raw_groups, zh_order)

    if args.mode == "check":
        if args.stdout_json:
            data = {
                "groups": [
                    {
                        "canonical": g[0],
                        "duplicates": g[1],
                        "zh_value": g[2],
                        "en_value": g[3],
                    }
                    for g in groups
                ],
                "total_groups": len(groups),
                "total_affected_keys": sum(len(g[1]) for g in groups),
                "empty_object_keys": {"zh": zh_empty_keys, "en": en_empty_keys},
            }
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            if groups:
                print("Redundant key groups (canonical -> duplicates):")
                for canonical, dups, zh_val, en_val in groups:
                    print(f"- {canonical} -> {', '.join(dups)}")
            else:
                print("No redundant keys.")
            if zh_empty_keys or en_empty_keys:
                print("Empty object keys to remove:")
                if zh_empty_keys:
                    print("- zh:")
                    for k in zh_empty_keys:
                        print(f"  {k}")
                if en_empty_keys:
                    print("- en:")
                    for k in en_empty_keys:
                        print(f"  {k}")
            else:
                print("No empty object keys.")
        return

    # work mode
    # Build replacements map old_key -> canonical_key
    replacements: Dict[str, str] = {}
    keys_to_remove: List[str] = []
    for canonical, dups, _, _ in groups:
        for old in dups:
            replacements[old] = canonical
            keys_to_remove.append(old)

    per_file = replace_keys_in_source(args.src, replacements)
    removed = remove_keys_from_locales(zh_doc, en_doc, keys_to_remove)

    # Remove explicit empty-object keys from zh/en as well
    empties_removed: Dict[str, List[str]] = {"zh": [], "en": []}
    # Recompute from current docs (post-dup-removal)
    zh_empty_keys = collect_empty_object_keys(zh_doc)
    en_empty_keys = collect_empty_object_keys(en_doc)
    for k in zh_empty_keys:
        if remove_key_from_dict(zh_doc, k):
            empties_removed["zh"].append(k)
    for k in en_empty_keys:
        if remove_key_from_dict(en_doc, k):
            empties_removed["en"].append(k)

    # Save locales
    try:
        save_json(args.zh, zh_doc)
    except Exception as e:
        print(f"[ERROR] Failed to save zh JSON {args.zh}: {e}", file=sys.stderr)
    try:
        save_json(args.en, en_doc)
    except Exception as e:
        print(f"[ERROR] Failed to save en JSON {args.en}: {e}", file=sys.stderr)

    if args.stdout_json:
        print(
            json.dumps(
                {
                    "replacements_total": per_file.get("__total__", 0),
                    "replacements_per_file": {k: v for k, v in per_file.items() if k != "__total__"},
                    "removed": removed,
                    "groups": [
                        {"canonical": c, "duplicates": d} for c, d, _, _ in groups
                    ],
                    "empties_removed": empties_removed,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("Applied replacements in source files:")
        for path, cnt in per_file.items():
            if path == "__total__":
                continue
            print(f"- {path}: {cnt}")
        print(f"Total replacements: {per_file.get('__total__', 0)}")
        print("Removed redundant keys from locales:")
        print(f"- zh: {len(removed.get('zh', []))} keys")
        print(f"- en: {len(removed.get('en', []))} keys")
        if empties_removed.get("zh") or empties_removed.get("en"):
            print("Also removed empty object keys:")
            if empties_removed.get("zh"):
                print(f"- zh: {len(empties_removed['zh'])} keys")
            if empties_removed.get("en"):
                print(f"- en: {len(empties_removed['en'])} keys")


if __name__ == "__main__":
    main()
