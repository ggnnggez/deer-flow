#!/usr/bin/env python3
"""Analyze a captured raw SSE response.

This parser is intentionally wire-oriented: it groups frames by the SSE
``event:`` field while preserving each frame's raw UTF-8 byte length.  It is
meant for evidence collection, not for consuming SSE as application data.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Frame:
    event: str
    frame_bytes: int
    data_bytes: int
    id_value: str | None
    data: bytes


@dataclass
class EventStats:
    count: int = 0
    total_frame_bytes: int = 0
    total_data_bytes: int = 0
    max_frame_bytes: int = 0
    max_data_bytes: int = 0
    frame_samples: list[int] = field(default_factory=list)
    data_samples: list[int] = field(default_factory=list)

    def record(self, frame: Frame) -> None:
        self.count += 1
        self.total_frame_bytes += frame.frame_bytes
        self.total_data_bytes += frame.data_bytes
        self.max_frame_bytes = max(self.max_frame_bytes, frame.frame_bytes)
        self.max_data_bytes = max(self.max_data_bytes, frame.data_bytes)
        self.frame_samples.append(frame.frame_bytes)
        self.data_samples.append(frame.data_bytes)

    def as_dict(self, total_frame_bytes: int) -> dict[str, int | float]:
        share = (self.total_frame_bytes / total_frame_bytes * 100) if total_frame_bytes else 0.0
        return {
            "count": self.count,
            "total_frame_bytes": self.total_frame_bytes,
            "frame_bytes_share_pct": round(share, 2),
            "avg_frame_bytes": round(self.total_frame_bytes / self.count, 2) if self.count else 0,
            "max_frame_bytes": self.max_frame_bytes,
            "p95_frame_bytes": percentile(self.frame_samples, 95),
            "total_data_bytes": self.total_data_bytes,
            "avg_data_bytes": round(self.total_data_bytes / self.count, 2) if self.count else 0,
            "max_data_bytes": self.max_data_bytes,
            "p95_data_bytes": percentile(self.data_samples, 95),
        }


def percentile(values: list[int], percentile_value: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, (percentile_value * len(ordered) + 99) // 100 - 1))
    return ordered[index]


def split_frames(raw: bytes) -> list[bytes]:
    """Split raw SSE bytes into frame byte chunks including trailing delimiters."""
    frames: list[bytes] = []
    start = 0
    cursor = 0
    while True:
        lf_index = raw.find(b"\n\n", cursor)
        crlf_index = raw.find(b"\r\n\r\n", cursor)
        candidates = [(idx, delim) for idx, delim in ((lf_index, b"\n\n"), (crlf_index, b"\r\n\r\n")) if idx != -1]
        if not candidates:
            break
        index, delimiter = min(candidates, key=lambda item: item[0])
        frame = raw[start : index + len(delimiter)]
        if frame.strip():
            frames.append(frame)
        start = index + len(delimiter)
        cursor = start

    trailing = raw[start:]
    if trailing.strip():
        frames.append(trailing)
    return frames


def parse_field_line(line: bytes) -> tuple[str, bytes] | None:
    if not line or line.startswith(b":"):
        return None
    field, sep, value = line.partition(b":")
    if not sep:
        return field.decode("utf-8", errors="replace"), b""
    if value.startswith(b" "):
        value = value[1:]
    return field.decode("utf-8", errors="replace"), value


def parse_frame(frame: bytes) -> Frame:
    event = "message"
    id_value: str | None = None
    data_lines: list[bytes] = []
    saw_field = False
    saw_comment = False

    for line in frame.splitlines():
        if line.startswith(b":"):
            saw_comment = True
            continue
        parsed = parse_field_line(line)
        if parsed is None:
            continue
        saw_field = True
        field_name, value = parsed
        if field_name == "event":
            event = value.decode("utf-8", errors="replace")
        elif field_name == "data":
            data_lines.append(value)
        elif field_name == "id":
            id_value = value.decode("utf-8", errors="replace")

    if not saw_field and saw_comment:
        event = "heartbeat"

    data = b"\n".join(data_lines)
    return Frame(event=event or "message", frame_bytes=len(frame), data_bytes=len(data), id_value=id_value, data=data)


def json_wire_size(value: Any) -> int:
    return len(json.dumps(value, default=str, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def analyze_values_payload(frames: list[Frame]) -> dict[str, Any]:
    values_frames = [frame for frame in frames if frame.event == "values"]
    field_totals: dict[str, int] = {}
    field_counts: dict[str, int] = {}
    field_max: dict[str, int] = {}
    message_counts: list[int] = []
    parse_errors = 0
    decoded_count = 0

    for frame in values_frames:
        try:
            payload = json.loads(frame.data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parse_errors += 1
            continue
        if not isinstance(payload, dict):
            continue

        decoded_count += 1
        messages = payload.get("messages")
        if isinstance(messages, list):
            message_counts.append(len(messages))

        for key, value in payload.items():
            size = json_wire_size(value)
            field_totals[key] = field_totals.get(key, 0) + size
            field_counts[key] = field_counts.get(key, 0) + 1
            field_max[key] = max(field_max.get(key, 0), size)

    total_field_bytes = sum(field_totals.values())
    return {
        "values_event_count": len(values_frames),
        "decoded_values_event_count": decoded_count,
        "parse_errors": parse_errors,
        "total_top_level_field_bytes": total_field_bytes,
        "message_count_min": min(message_counts) if message_counts else 0,
        "message_count_max": max(message_counts) if message_counts else 0,
        "message_count_last": message_counts[-1] if message_counts else 0,
        "fields": {
            key: {
                "count": field_counts[key],
                "total_bytes": total,
                "share_pct": round(total / total_field_bytes * 100, 2) if total_field_bytes else 0.0,
                "avg_bytes": round(total / field_counts[key], 2) if field_counts[key] else 0,
                "max_bytes": field_max[key],
            }
            for key, total in sorted(field_totals.items(), key=lambda item: (-item[1], item[0]))
        },
    }


def analyze(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    frames = [parse_frame(frame) for frame in split_frames(raw)]
    stats: dict[str, EventStats] = {}
    for frame in frames:
        stats.setdefault(frame.event, EventStats()).record(frame)

    total_frame_bytes = sum(frame.frame_bytes for frame in frames)
    return {
        "source": str(path),
        "file_bytes": len(raw),
        "parsed_frame_bytes": total_frame_bytes,
        "unparsed_bytes": len(raw) - total_frame_bytes,
        "total_events": len(frames),
        "events": {
            event: event_stats.as_dict(total_frame_bytes)
            for event, event_stats in sorted(
                stats.items(),
                key=lambda item: (-item[1].total_frame_bytes, item[0]),
            )
        },
        "values_payload": analyze_values_payload(frames),
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# SSE Capture Summary",
        "",
        f"- Source: `{summary['source']}`",
        f"- File bytes: {summary['file_bytes']:,}",
        f"- Parsed frame bytes: {summary['parsed_frame_bytes']:,}",
        f"- Unparsed bytes: {summary['unparsed_bytes']:,}",
        f"- Total events: {summary['total_events']:,}",
        "",
        "| Event | Count | Total Frame Bytes | Share | Avg Frame | P95 Frame | Max Frame | Total Data Bytes |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for event, stats in summary["events"].items():
        lines.append(
            "| {event} | {count:,} | {total_frame_bytes:,} | {share:.2f}% | "
            "{avg_frame_bytes:,.2f} | {p95_frame_bytes:,} | {max_frame_bytes:,} | {total_data_bytes:,} |".format(
                event=event,
                count=stats["count"],
                total_frame_bytes=stats["total_frame_bytes"],
                share=stats["frame_bytes_share_pct"],
                avg_frame_bytes=stats["avg_frame_bytes"],
                p95_frame_bytes=stats["p95_frame_bytes"],
                max_frame_bytes=stats["max_frame_bytes"],
                total_data_bytes=stats["total_data_bytes"],
            )
        )
    lines.append("")

    values_payload = summary.get("values_payload", {})
    if values_payload:
        lines.extend(
            [
                "## Values Payload Top-Level Fields",
                "",
                f"- Values events: {values_payload['values_event_count']:,}",
                f"- Decoded values events: {values_payload['decoded_values_event_count']:,}",
                f"- Parse errors: {values_payload['parse_errors']:,}",
                f"- Message count range in values: {values_payload['message_count_min']:,} -> {values_payload['message_count_max']:,}",
                f"- Last values message count: {values_payload['message_count_last']:,}",
                "",
                "| Field | Count | Total Bytes | Share | Avg Bytes | Max Bytes |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for field_name, stats in values_payload["fields"].items():
            lines.append(
                "| {field} | {count:,} | {total_bytes:,} | {share:.2f}% | {avg_bytes:,.2f} | {max_bytes:,} |".format(
                    field=field_name,
                    count=stats["count"],
                    total_bytes=stats["total_bytes"],
                    share=stats["share_pct"],
                    avg_bytes=stats["avg_bytes"],
                    max_bytes=stats["max_bytes"],
                )
            )
        lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze raw SSE wire capture bytes by event type.")
    parser.add_argument("raw_sse", type=Path, help="Path to raw SSE response body captured from curl or a proxy.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Directory for raw-summary.json and raw-summary.md. Defaults to the input file's directory.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_path = args.raw_sse
    out_dir = args.out_dir or raw_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = analyze(raw_path)
    json_path = out_dir / "raw-summary.json"
    markdown_path = out_dir / "raw-summary.md"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(summary), encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
