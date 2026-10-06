#!/usr/bin/env python3
"""Local vocabulary and chunk library for the Verve English coach."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
KINDS = ("word", "phrase", "sentence", "chunk")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_data_dir() -> Path:
    override = os.environ.get("VERVE_DATA_DIR")
    return Path(override).expanduser() if override else Path.home() / ".verve"


def library_path(args: argparse.Namespace) -> Path:
    return Path(args.data_dir).expanduser() / "library.json"


def empty_library() -> dict[str, Any]:
    stamp = now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": stamp,
        "updated_at": stamp,
        "profile": {},
        "items": [],
    }


def save_library(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now_iso()
    fd, temp_name = tempfile.mkstemp(prefix=".library-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_library(path: Path, create: bool = False) -> dict[str, Any]:
    if not path.exists():
        if not create:
            raise SystemExit(f"No Verve library found at {path}. Run `init` first.")
        data = empty_library()
        save_library(path, data)
        return data
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read Verve library at {path}: {exc}") from exc
    if data.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(
            f"Unsupported schema version {data.get('schema_version')!r}; expected {SCHEMA_VERSION}."
        )
    return data


def emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return sorted({part.strip().lower() for part in raw.split(",") if part.strip()})


def mastery(item: dict[str, Any]) -> str:
    review = item["review"]
    reps = int(review.get("repetitions", 0))
    streak = int(review.get("streak", 0))
    if reps == 0:
        return "new"
    if reps < 3 or streak < 2:
        return "learning"
    if reps >= 6 and streak >= 3:
        return "owned"
    return "active"


def public_item(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    result["mastery"] = mastery(item)
    return result


def find_item(data: dict[str, Any], item_id: str) -> dict[str, Any]:
    exact = [item for item in data["items"] if item["id"] == item_id]
    if len(exact) == 1:
        return exact[0]
    prefix = [item for item in data["items"] if item["id"].startswith(item_id)]
    if len(prefix) == 1:
        return prefix[0]
    if not prefix:
        raise SystemExit(f"No item matches id {item_id!r}.")
    raise SystemExit(f"Id prefix {item_id!r} is ambiguous.")


def summary(data: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, Any] = {"total": len(data["items"]), "due": 0}
    today = date.today().isoformat()
    for label in ("new", "learning", "active", "owned"):
        counts[label] = 0
    for item in data["items"]:
        counts[mastery(item)] += 1
        if item["review"]["due"] <= today:
            counts["due"] += 1
    counts["by_kind"] = {
        kind: sum(1 for item in data["items"] if item["kind"] == kind) for kind in KINDS
    }
    return counts


def command_init(args: argparse.Namespace) -> None:
    path = library_path(args)
    created = not path.exists()
    data = load_library(path, create=True)
    emit({"created": created, "path": str(path), "summary": summary(data)})


def command_profile(args: argparse.Namespace) -> None:
    path = library_path(args)
    data = load_library(path, create=args.action == "set")
    if args.action == "show":
        emit(data["profile"])
        return
    value: Any = args.value
    if args.json:
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSON value: {exc}") from exc
    data["profile"][args.key] = value
    save_library(path, data)
    emit(data["profile"])


def command_add(args: argparse.Namespace) -> None:
    path = library_path(args)
    data = load_library(path, create=True)
    normalized = " ".join(args.text.split()).casefold()
    duplicate = next(
        (
            item
            for item in data["items"]
            if item["kind"] == args.kind
            and " ".join(item["text"].split()).casefold() == normalized
        ),
        None,
    )
    fields = {
        "meaning": args.meaning,
        "context": args.context,
        "tone": args.tone,
        "source": args.source,
        "example": args.example,
        "note": args.note,
    }
    if duplicate:
        for key, value in fields.items():
            if value and not duplicate.get(key):
                duplicate[key] = value
        duplicate["tags"] = sorted(set(duplicate.get("tags", [])) | set(parse_tags(args.tags)))
        duplicate["updated_at"] = now_iso()
        save_library(path, data)
        emit({"created": False, "item": public_item(duplicate)})
        return

    stamp = now_iso()
    item = {
        "id": uuid.uuid4().hex[:12],
        "kind": args.kind,
        "text": " ".join(args.text.split()),
        **fields,
        "tags": parse_tags(args.tags),
        "created_at": stamp,
        "updated_at": stamp,
        "review": {
            "due": date.today().isoformat(),
            "ease": 2.3,
            "interval_days": 0,
            "repetitions": 0,
            "streak": 0,
            "last_score": None,
            "last_reviewed_at": None,
        },
    }
    data["items"].append(item)
    save_library(path, data)
    emit({"created": True, "item": public_item(item)})


def command_list(args: argparse.Namespace) -> None:
    data = load_library(library_path(args))
    items = data["items"]
    if args.kind:
        items = [item for item in items if item["kind"] == args.kind]
    if args.tag:
        tag = args.tag.casefold()
        items = [item for item in items if tag in item.get("tags", [])]
    emit([public_item(item) for item in items])


def command_search(args: argparse.Namespace) -> None:
    data = load_library(library_path(args))
    query = args.query.casefold()
    keys = ("text", "meaning", "context", "tone", "source", "example", "note")
    found = []
    for item in data["items"]:
        haystack = " ".join(str(item.get(key, "")) for key in keys)
        haystack += " " + " ".join(item.get("tags", []))
        if query in haystack.casefold():
            found.append(public_item(item))
    emit(found)


def command_due(args: argparse.Namespace) -> None:
    data = load_library(library_path(args))
    today = date.today().isoformat()
    items = [item for item in data["items"] if item["review"]["due"] <= today]
    items.sort(key=lambda item: (item["review"]["due"], item["created_at"]))
    emit([public_item(item) for item in items[: args.limit]])


def next_interval(review: dict[str, Any], score: int) -> int:
    previous = int(review.get("interval_days", 0))
    if score == 0:
        return 1
    if score == 1:
        return 2
    if score == 2:
        return max(3, previous * 2)
    return max(7, round(previous * 2.5))


def command_review(args: argparse.Namespace) -> None:
    path = library_path(args)
    data = load_library(path)
    item = find_item(data, args.id)
    review = item["review"]
    review["repetitions"] = int(review.get("repetitions", 0)) + 1
    review["streak"] = int(review.get("streak", 0)) + 1 if args.score >= 2 else 0
    review["ease"] = round(
        min(3.0, max(1.3, float(review.get("ease", 2.3)) + (args.score - 2) * 0.12)),
        2,
    )
    interval = next_interval(review, args.score)
    review["interval_days"] = interval
    review["due"] = (date.today() + timedelta(days=interval)).isoformat()
    review["last_score"] = args.score
    review["last_reviewed_at"] = now_iso()
    item["updated_at"] = now_iso()
    save_library(path, data)
    emit(public_item(item))


def command_stats(args: argparse.Namespace) -> None:
    emit(summary(load_library(library_path(args))))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        default=str(default_data_dir()),
        help="Directory containing library.json (default: %(default)s)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init", help="Create an empty library if needed")
    init_parser.set_defaults(func=command_init)

    profile = sub.add_parser("profile", help="Show or update the coaching profile")
    profile_sub = profile.add_subparsers(dest="action", required=True)
    profile_show = profile_sub.add_parser("show")
    profile_show.set_defaults(func=command_profile)
    profile_set = profile_sub.add_parser("set")
    profile_set.add_argument("--key", required=True)
    profile_set.add_argument("--value", required=True)
    profile_set.add_argument("--json", action="store_true", help="Parse value as JSON")
    profile_set.set_defaults(func=command_profile)

    add = sub.add_parser("add", help="Add or enrich a library item")
    add.add_argument("--kind", required=True, choices=KINDS)
    add.add_argument("--text", required=True)
    add.add_argument("--meaning", default="")
    add.add_argument("--context", default="")
    add.add_argument("--tone", default="")
    add.add_argument("--source", default="")
    add.add_argument("--example", default="")
    add.add_argument("--note", default="")
    add.add_argument("--tags", default="", help="Comma-separated tags")
    add.set_defaults(func=command_add)

    list_parser = sub.add_parser("list", help="List library items")
    list_parser.add_argument("--kind", choices=KINDS)
    list_parser.add_argument("--tag")
    list_parser.set_defaults(func=command_list)

    search = sub.add_parser("search", help="Search all item fields")
    search.add_argument("query")
    search.set_defaults(func=command_search)

    due = sub.add_parser("due", help="List items due for active recall")
    due.add_argument("--limit", type=int, default=10)
    due.set_defaults(func=command_due)

    review = sub.add_parser("review", help="Record a recall score")
    review.add_argument("--id", required=True)
    review.add_argument("--score", required=True, type=int, choices=range(4))
    review.set_defaults(func=command_review)

    stats = sub.add_parser("stats", help="Show library and mastery counts")
    stats.set_defaults(func=command_stats)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
