"""Small shared helpers: atomic writes, jsonl, csv, domain normalisation, timestamps."""
from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlparse


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today():
    return datetime.now().strftime("%Y-%m-%d")


def atomic_write(path, text):
    """Write text to path atomically (temp file in same dir, fsync, rename)."""
    path = str(path)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path, obj):
    atomic_write(path, json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n")


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def append_jsonl(path, obj):
    os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()


def read_jsonl(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # torn last line after a crash; the row is simply redone
    except FileNotFoundError:
        pass
    return out


def write_csv(path, rows, columns):
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in columns})
    atomic_write(path, buf.getvalue())


def read_csv(path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def norm_domain(value):
    """'https://www.Example.com/path' -> 'example.com'. Empty string if unusable."""
    v = (value or "").strip().lower()
    if not v:
        return ""
    if "//" not in v:
        v = "http://" + v
    host = urlparse(v).netloc.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", host) else ""
