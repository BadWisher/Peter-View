"""Структура страницы для сравнения: теги, порядок, атрибуты."""

from __future__ import annotations

import difflib
import hashlib
import re

from bs4 import BeautifulSoup, Tag

from ..extractors import normalize_spaces

_VOLATILE = [
    re.compile(r"\b\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2}(?::\d{2})?)?"),
    re.compile(r"\b\d{2}:\d{2}(?::\d{2})?\b"),
    re.compile(r"\b[0-9a-f]{16,}\b", re.I),
    re.compile(r"\b\d[\d\s]*просмотр\w*", re.I),
    re.compile(r"обновлено.*", re.I),
]

_HASHY_CLASS = re.compile(r"[0-9a-f]{6,}|\d{4,}", re.I)

SKIP_TAGS = frozenset({
    "script", "style", "noscript", "template", "head",
    "meta", "link", "base", "title",
})

KEPT_ATTRS = frozenset({
    "id", "name", "type", "href", "src", "alt", "title",
    "placeholder", "value", "role", "for", "action", "method",
    "selected", "checked", "disabled", "readonly", "required", "open",
})

_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)

MAX_NODES = 2000
MAX_TEXT = 120
MAX_EVENTS = 200
COPY_LIMIT = 60000


def mask_volatile(value: str) -> str:
    value = normalize_spaces(value)
    for pat in _VOLATILE:
        value = pat.sub("", value)
    return re.sub(r"\s+", " ", value).strip(" -–—•·")


def _clean_style(raw: str) -> str:
    bits = []
    for chunk in str(raw or "").split(";"):
        chunk = chunk.strip().lower()
        if not chunk or ":" not in chunk:
            continue
        name, _, value = chunk.partition(":")
        name = re.sub(r"\s+", " ", name.strip())
        value = re.sub(r"\s+", " ", value.strip())
        if name and value:
            bits.append(f"{name}:{value}")
    return mask_volatile(";".join(sorted(bits)))


def _clean_attrs(tag: Tag) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in KEPT_ATTRS:
        if tag.has_attr(name):
            raw = tag.get(name)
            if raw is True or raw == "":
                out[name] = ""
            elif isinstance(raw, list):
                out[name] = mask_volatile(" ".join(str(v) for v in raw))
            else:
                out[name] = mask_volatile(str(raw))
    classes = tag.get("class") or []
    if isinstance(classes, str):
        classes = classes.split()
    kept = sorted({c for c in classes if c and not _HASHY_CLASS.search(c)})
    if kept:
        out["class"] = " ".join(kept)
    style = _clean_style(tag.get("style") or "")
    if style:
        out["style"] = style
    return out


def _visible(tag: Tag) -> bool:
    if tag.name in ("input",):
        itype = (tag.get("type") or "text").lower()
        if itype == "hidden":
            return False
    if tag.has_attr("hidden") or tag.get("aria-hidden") == "true":
        return False
    style = str(tag.get("style") or "")
    return not _HIDDEN_STYLE.search(style)


def _own_text(tag: Tag) -> str:
    bits = []
    for child in tag.children:
        if isinstance(child, str):
            chunk = normalize_spaces(str(child))
            if chunk:
                bits.append(chunk)
    return mask_volatile(" ".join(bits))[:MAX_TEXT]


_COPY_SKIP = ("style", "link", "base", "meta", "title")


def _sibling_index(tag: Tag, skip: tuple = ()) -> int:
    n = 0
    sib = tag.previous_sibling
    while sib is not None:
        if isinstance(sib, Tag) and sib.name not in skip:
            n += 1
        sib = sib.previous_sibling
    return n


def snapshot_nodes(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "lxml")
    for dead in soup.find_all(SKIP_TAGS):
        dead.decompose()
    body = soup.find("body") or soup
    nodes: list[dict] = []

    def walk(node: Tag, path: str) -> None:
        for child in node.children:
            if not isinstance(child, Tag):
                continue
            if not _visible(child):
                continue
            step = f"{child.name}#{_sibling_index(child)}"
            here = f"{path}/{step}" if path else step
            nodes.append({
                "tag": child.name,
                "path": here,
                "attrs": _clean_attrs(child),
                "text": _own_text(child),
            })
            if len(nodes) >= MAX_NODES:
                return
            walk(child, here)
            if len(nodes) >= MAX_NODES:
                return

    if isinstance(body, Tag):
        walk(body, "body")
    return nodes


def cleaned_body(html: str, limit: int = 60000) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    for dead in soup.find_all(("script", "noscript", "template")):
        dead.decompose()
    head_keep = ""
    head = soup.find("head")
    if isinstance(head, Tag):
        bits = list(head.find_all("style"))
        bits += [l for l in head.find_all("link")
                 if "stylesheet" in str(l.get("rel") or "").lower()
                 or str(l.get("href") or "").endswith(".css")]
        head_keep = "".join(str(s) for s in bits)
    body = soup.find("body") or soup
    if not isinstance(body, Tag):
        return head_keep[:limit]
    for tag in body.find_all(True):
        for attr in ("onclick", "onload", "onerror", "onmouseover", "onfocus", "onblur"):
            tag.attrs.pop(attr, None)
    out = head_keep + (body.decode_contents() or "")
    return out[:limit]


def _sig(node: dict) -> str:
    attrs = " ".join(f"{k}={v}" for k, v in sorted(node["attrs"].items()))
    return f"{node['path']}|{node['tag']}|{attrs}|{node['text']}"


def _content_sig(node: dict) -> str:
    attrs = " ".join(f"{k}={v}" for k, v in sorted(node["attrs"].items()))
    return f"{node['tag']}|{attrs}|{node['text']}"


def fingerprint_nodes(nodes: list[dict]) -> str:
    body = "\n".join(_sig(n) for n in nodes)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _where(node: dict) -> str:
    tail = node["path"].split("/")[-3:]
    anchor = node["text"] or node["attrs"].get("alt") or node["attrs"].get("href") or node["attrs"].get("id") or ""
    if len(anchor) > 60:
        anchor = anchor[:60] + "…"
    place = " → ".join(tail)
    return f"{place} «{anchor}»" if anchor else place


def _fine_kind(old: dict, new: dict) -> tuple[str, str]:
    if old["tag"] != new["tag"]:
        return "tag", f"{old['tag']} → {new['tag']}"
    if old["attrs"] != new["attrs"]:
        shown = {
            "href": "ссылка",
            "src": "картинка",
            "alt": "подпись",
            "disabled": "доступность",
            "checked": "состояние",
            "selected": "состояние",
            "open": "состояние",
        }
        bits = []
        old_style = old["attrs"].get("style", "")
        new_style = new["attrs"].get("style", "")
        old_cls = old["attrs"].get("class", "")
        new_cls = new["attrs"].get("class", "")
        if old_cls != new_cls or old_style != new_style:
            bits.append(f"оформление {old_cls or '—'} → {new_cls or '—'}")
        for k in sorted(set(old["attrs"]) | set(new["attrs"])):
            if k in ("class", "style"):
                continue
            o, n = old["attrs"].get(k), new["attrs"].get(k)
            if o == n:
                continue
            bits.append(f"{shown.get(k, k)} {o or '—'} → {n or '—'}")
            if len(bits) >= 3:
                break
        return "attr", "; ".join(bits)
    return "text", f"{old['text']} → {new['text']}" if old["text"] != new["text"] else "порядок"


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _same_spot(old: dict, new: dict) -> bool:
    if _parent(old["path"]) != _parent(new["path"]):
        return False
    for key in ("text",):
        if old[key] and old[key] == new[key]:
            return True
    for key in ("alt", "href", "id"):
        if old["attrs"].get(key) and old["attrs"].get(key) == new["attrs"].get(key):
            return True
    return False


def diff_nodes(old: list[dict], new: list[dict]) -> list[dict]:
    old_sigs = [_sig(n) for n in old]
    new_sigs = [_sig(n) for n in new]
    matcher = difflib.SequenceMatcher(a=old_sigs, b=new_sigs, autojunk=False)

    gone: list[int] = []
    came: list[int] = []
    events: list[dict] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_idx = list(range(i1, i2)) if tag != "insert" else []
        new_idx = list(range(j1, j2)) if tag != "delete" else []
        used: set[int] = set()
        for a in old_idx:
            best = None
            for b in new_idx:
                if b in used:
                    continue
                if old[a]["path"] == new[b]["path"] or _same_spot(old[a], new[b]):
                    best = b
                    break
            if best is None:
                for b in new_idx:
                    if b not in used and old[a]["tag"] == new[b]["tag"]:
                        best = b
                        break
            if best is not None:
                used.add(best)
                kind, detail = _fine_kind(old[a], new[best])
                events.append({
                    "kind": kind, "tag": new[best]["tag"], "old_tag": old[a]["tag"],
                    "path": new[best]["path"],
                    "where": _where(new[best]), "old_text": old[a]["text"],
                    "new_text": new[best]["text"], "detail": detail,
                    "old_attrs": old[a]["attrs"], "attrs": new[best]["attrs"],
                })
            else:
                gone.append(a)
        for b in new_idx:
            if b not in used:
                came.append(b)

    if not gone and not came and events:
        from collections import Counter
        olds = [e["old_text"] for e in events if e["kind"] == "text" and e["old_text"]]
        news = [e["new_text"] for e in events if e["kind"] == "text" and e["new_text"]]
        if olds and Counter(olds) == Counter(news) and olds != news:
            for e in events:
                if e["kind"] == "text":
                    e["kind"] = "moved"
                    e["detail"] = "блоки поменялись местами"
    old_content = [_content_sig(old[i]) for i in gone]
    new_content = [_content_sig(new[j]) for j in came]
    by_content: dict[str, list[int]] = {}
    for k, j in zip(new_content, came):
        by_content.setdefault(k, []).append(j)
    moved_new: set[int] = set()
    moved_old: set[int] = set()
    for k, i in zip(old_content, gone):
        pile = by_content.get(k)
        if pile:
            j = pile.pop(0)
            moved_new.add(j)
            moved_old.add(i)
            events.append({
                "kind": "moved", "tag": new[j]["tag"], "path": new[j]["path"],
                "where": _where(new[j]), "old_text": old[i]["text"],
                "new_text": new[j]["text"],
                "detail": f"{old[i]['path']} → {new[j]['path']}",
                "attrs": new[j]["attrs"], "old_attrs": old[i]["attrs"],
            })
    gone = [i for i in gone if i not in moved_old]
    for i in gone:
        events.append({
            "kind": "removed", "tag": old[i]["tag"], "path": old[i]["path"],
            "where": _where(old[i]), "old_text": old[i]["text"],
            "new_text": "", "detail": old[i]["text"] or _sig(old[i]).split("|")[2][:80],
            "attrs": old[i]["attrs"], "old_attrs": old[i]["attrs"],
        })
    for j in came:
        if j in moved_new:
            continue
        events.append({
            "kind": "added", "tag": new[j]["tag"], "path": new[j]["path"],
            "where": _where(new[j]), "old_text": "",
            "new_text": new[j]["text"], "detail": new[j]["text"] or _sig(new[j]).split("|")[2][:80],
            "attrs": new[j]["attrs"], "old_attrs": {},
        })

    events.sort(key=lambda e: ({"added": 0, "removed": 1, "moved": 2,
                                "tag": 3, "attr": 4, "text": 5}.get(e["kind"], 6),
                               e["path"]))
    if len(events) > MAX_EVENTS:
        events = events[:MAX_EVENTS]
        events.append({"kind": "more", "tag": "", "path": "",
                       "where": "", "old_text": "", "new_text": "",
                       "detail": "показаны первые 200 изменений"})
    return events


def mark_copy(body: str, old_nodes: list[dict], new_nodes: list[dict],
              events: list[dict]) -> str:
    soup = BeautifulSoup(f"<div>{body or ''}</div>", "lxml")
    container = soup.find("div")
    if not isinstance(container, Tag):
        return (body or "")[:COPY_LIMIT]

    by_path: dict[str, Tag] = {}

    def walk(node: Tag, path: str) -> None:
        for child in list(node.children):
            if not isinstance(child, Tag):
                continue
            if child.name in ("style", "link", "base", "meta", "title"):
                continue
            step = f"{child.name}#{_sibling_index(child, _COPY_SKIP)}"
            here = f"{path}/{step}" if path else step
            by_path[here] = child
            walk(child, here)

    walk(container, "body")

    paint = soup.new_tag("style")
    paint["data-pvwatch"] = "marks"
    paint.string = (
        ".pvwatch-is-added,.pvwatch-is-text{background:#ddf4ef;border-bottom:2px solid #00a88e;border-radius:2px}"
        ".pvwatch-is-attr,.pvwatch-is-moved,.pvwatch-is-tag{background:#fdf7ec;border-bottom:2px solid #c2820b;border-radius:2px}"
        ".pvwatch-is-removed,.pvwatch-ghost{margin:8px 0;padding:8px 10px;color:#9d2c24;background:#fdf1f0;border:1px dashed #d52a1d;border-radius:8px}"
        ".pvwatch-active{outline:3px solid #0f766e;outline-offset:3px;border-radius:4px}"
    )
    if isinstance(container, Tag):
        container.insert(0, paint)

    kinds = {e.get("kind") for e in events if e.get("kind") != "more"}
    for event in events:
        kind = event.get("kind") or ""
        if kind == "more":
            continue
        if kind == "text" and len(kinds) == 1:
            path = event.get("path") or ""
            target = by_path.get(path)
            if target is not None:
                cls = list(target.get("class") or [])
                if isinstance(cls, str):
                    cls = cls.split()
                if "pvwatch-is-text" not in cls:
                    cls.append("pvwatch-is-text")
                target["class"] = cls
                target["data-pvwatch-path"] = path
                target["data-pvwatch-kind"] = kind
            continue
        path = event.get("path") or ""
        if kind == "removed":
            ghost = soup.new_tag("div")
            ghost["class"] = ["pvwatch-ghost", "pvwatch-is-removed"]
            label = event.get("old_text") or event.get("detail") or "блок"
            ghost.string = f"Тут был блок «{label}» — его убрали"
            anchor = by_path.get(path)
            if anchor is not None and anchor.parent is not None:
                anchor.insert_after(ghost)
            elif isinstance(container, Tag):
                container.append(ghost)
            continue
        target = by_path.get(path)
        if target is None:
            continue
        cls = list(target.get("class") or [])
        if isinstance(cls, str):
            cls = cls.split()
        mark = f"pvwatch-is-{kind}"
        if mark not in cls:
            cls.append(mark)
        target["data-pvwatch-path"] = path
        target["data-pvwatch-kind"] = kind

    out = container.decode_contents() if isinstance(container, Tag) else str(soup)
    return (out or "")[:COPY_LIMIT]


def copy_document(url: str, body: str) -> str:
    soup = BeautifulSoup(f"<div>{body or ''}</div>", "lxml")
    holder = soup.find("div")
    head_bits: list[str] = []
    body_bits: list[str] = []
    if isinstance(holder, Tag):
        for child in list(holder.children):
            if isinstance(child, Tag) and child.name in ("style", "link"):
                head_bits.append(str(child))
            else:
                body_bits.append(str(child))
    else:
        body_bits.append(body or "")
    safe_url = (url or "").replace('"', "")
    base = f'<base href="{safe_url}" target="_blank">' if safe_url.startswith("http") else ""
    doc = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"{base}{''.join(head_bits)}</head>"
        f"<body>{''.join(body_bits)}</body></html>"
    )
    return doc[: COPY_LIMIT + 4000]
