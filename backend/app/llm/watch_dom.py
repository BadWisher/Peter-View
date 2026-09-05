"""Структура страницы для сравнения: теги, порядок, атрибуты."""

from __future__ import annotations

import difflib
import hashlib
import re

from bs4 import BeautifulSoup, Tag

from ..extractors import normalize_spaces

# Волатильный мусор маскируем так же, как в тексте: даты, счётчики, токены.
# Иначе каждый прогон будет «изменилась» из-за цифр, а не правок.
_VOLATILE = [
    re.compile(r"\b\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2}(?::\d{2})?)?"),
    re.compile(r"\b\d{2}:\d{2}(?::\d{2})?\b"),
    re.compile(r"\b[0-9a-f]{16,}\b", re.I),
    re.compile(r"\b\d[\d\s]*просмотр\w*", re.I),
    re.compile(r"обновлено.*", re.I),
]

# Классы со сборочным хэшем (css-1a2b3c, block_x7f9a2) меняются при каждом
# деплое фронта и не означают правку. Человеческие классы оставляем —
# смена класса часто и есть визуальное изменение.
_HASHY_CLASS = re.compile(r"[0-9a-f]{6,}|\d{4,}", re.I)

SKIP_TAGS = frozenset({
    "script", "style", "noscript", "template", "head",
    "meta", "link", "base", "title",
})

# Атрибуты, которые влияют на интерфейс. class/style осознанно урезаны
# (см. _clean_attrs): полный style с хэшами даст шум на каждом прогоне.
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
    """Только собственный текст узла, без потомков.

    Если брать текст всего поддерева, одна правка слова пометит всю цепочку
    предков — шум вместо позиции. Контейнеры получают пустой текст и
    сравниваются по структуре, листья — по словам.

    Важно: текст контейнера НЕ входит в сигнатуру сравнения потомков.
    Иначе перестановка двух абзацев поменяет и текст родителя, и дифф
    решит, что изменился сам контейнер, а не порядок детей.
    """
    bits = []
    for child in tag.children:
        if isinstance(child, str):
            chunk = normalize_spaces(str(child))
            if chunk:
                bits.append(chunk)
    return mask_volatile(" ".join(bits))[:MAX_TEXT]


def _nth(tag: Tag) -> int:
    n = 0
    sib = tag.previous_sibling
    while sib is not None:
        if isinstance(sib, Tag) and sib.name == tag.name:
            n += 1
        sib = sib.previous_sibling
    return n


def _child_position(tag: Tag) -> int:
    """Порядковый номер среди всех соседей-тегов, не только одноимённых.

    p[0]/p[1] не различают «первый абзац» и «второй абзац» при перестановке:
    в обоих снимках есть p[0] и p[1], только тексты разные — и дифф видит
    «текст сменён», а не «переехало». Сквозной индекс чинит это: уехавший
    блок получает другой путь, одинаковый контент в разных местах — moved.
    """
    n = 0
    sib = tag.previous_sibling
    while sib is not None:
        if isinstance(sib, Tag):
            n += 1
        sib = sib.previous_sibling
    return n


def snapshot_nodes(html: str) -> list[dict]:
    """Видимые элементы body по порядку: тег, путь, атрибуты, текст."""
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
            step = f"{child.name}#{_child_position(child)}"
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
    # Тело без скриптов и чужого style. Свой style с метками (data-pvwatch)
    # переживает чистку — иначе песочница не видит подсветку.
    soup = BeautifulSoup(html or "", "lxml")
    for dead in soup.find_all(("script", "noscript", "template")):
        dead.decompose()
    for tag in soup.find_all("style"):
        if tag.get("data-pvwatch") != "marks":
            tag.decompose()
    body = soup.find("body") or soup
    if not isinstance(body, Tag):
        return ""
    for tag in body.find_all(True):
        for attr in ("onclick", "onload", "onerror", "onmouseover", "onfocus", "onblur"):
            tag.attrs.pop(attr, None)
    out = body.decode_contents() or ""
    return out[:limit]


def _sig(node: dict) -> str:
    attrs = " ".join(f"{k}={v}" for k, v in sorted(node["attrs"].items()))
    return f"{node['path']}|{node['tag']}|{attrs}|{node['text']}"


def _content_sig(node: dict) -> str:
    """Тот же узел без позиции: тег + атрибуты + текст.

    Нужен, чтобы отличить «поменялся href» от «блок переехал»: сначала ищем
    правку по тому же пути, и только остаток считаем переездом/появлением.
    """
    attrs = " ".join(f"{k}={v}" for k, v in sorted(node["attrs"].items()))
    return f"{node['tag']}|{attrs}|{node['text']}"


def fingerprint_nodes(nodes: list[dict]) -> str:
    body = "\n".join(_sig(n) for n in nodes)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _where(node: dict) -> str:
    """Человекочитаемая позиция: последние звенья пути + свой текст/атрибут."""
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
        keys = sorted(set(old["attrs"]) | set(new["attrs"]))
        bits = [f"{k}: {old['attrs'].get(k, '—')} → {new['attrs'].get(k, '—')}"
                for k in keys if old["attrs"].get(k) != new["attrs"].get(k)][:3]
        return "attr", "; ".join(bits)
    return "text", f"{old['text']} → {new['text']}" if old["text"] != new["text"] else "порядок"


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _same_spot(old: dict, new: dict) -> bool:
    """Тот же узел, даже если имя тега или индекс в пути уплыли.

    Путь включает имя тега (p#0 → h2#0 при смене тега) и сквозной индекс
    (#4 → #5, когда выше добавился сосед). Поэтому «то же место» — это
    один родитель плюс совпадающий якорь: текст, alt, href или id.
    Без якоря (два пустых контейнера) ровнять нельзя — это разные узлы.
    """
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
    """События интерфейса: added/removed/moved/tag/attr/text с позициями."""
    old_sigs = [_sig(n) for n in old]
    new_sigs = [_sig(n) for n in new]
    matcher = difflib.SequenceMatcher(a=old_sigs, b=new_sigs, autojunk=False)

    gone: list[int] = []
    came: list[int] = []
    events: list[dict] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        # Кусок replace/delete/insert: сначала ровняем те же узлы по месту
        # (родитель + якорь), потом остаток — в переезды/появления/удаления.
        # Делить replace пополам «по индексам» нельзя: смена href у ссылки
        # и вставка кнопки рядом приходят одним куском 1:2.
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

    # Один и тот же узел исчез там и появился тут — переезд, а не пара
    # «удалено + добавлено». Сравниваем без позиции: тот же контент
    # в другом месте — moved, иначе это правда удаление и появление.
    #
    # Отдельный случай — перестановка соседей: пути у обоих уцелели
    # (p#0 и p#1 на месте), но содержимое поменялось местами. Позиционный
    # SequenceMatcher видит это как replace 1:1 по тем же путям и зовёт
    # _fine_kind, который скажет «текст сменён». Проверяем набор текстов:
    # если мультимножество текстов блока совпало, а попарно — нет,
    # это переезд внутри родителя, а не две независимые правки.
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
    # Тот же сохранённый body, но узлы с изменениями уже помечены классами.
    # Краски едут внутри (песочница не видит общий style.css), чужой style
    # cleaned_body вырезает — свой помечен data-pvwatch и переживает чистку.
    soup = BeautifulSoup(body or "", "lxml")
    container = soup.find("body")
    if container is None:
        container = soup
    if not isinstance(container, Tag):
        return (body or "")[:COPY_LIMIT]

    paint = soup.new_tag("style")
    paint["data-pvwatch"] = "marks"
    paint.string = (
        ".pvwatch-is-added,.pvwatch-is-text{background:#ddf4ef;border-bottom:2px solid #00a88e;border-radius:2px}"
        ".pvwatch-is-attr,.pvwatch-is-moved,.pvwatch-is-tag{background:#fdf7ec;border-bottom:2px solid #c2820b;border-radius:2px}"
        ".pvwatch-is-removed,.pvwatch-ghost{margin:8px 0;padding:8px 10px;color:#9d2c24;background:#fdf1f0;border:1px dashed #d52a1d;border-radius:8px}"
    )

    by_path: dict[str, Tag] = {}

    def walk(node: Tag, path: str) -> None:
        for child in list(node.children):
            if not isinstance(child, Tag) or child.name == "style":
                continue
            step = f"{child.name}#{_child_position(child)}"
            here = f"{path}/{step}" if path else step
            by_path[here] = child
            walk(child, here)

    walk(container, "body")

    if isinstance(container, Tag):
        container.insert(0, paint)

    kinds = {e.get("kind") for e in events if e.get("kind") != "more"}
    for event in events:
        kind = event.get("kind") or ""
        if kind == "more":
            continue
        # Слово поменялось, структура та же: структурный diff молчит,
        # текстовый видит. Подсвечиваем абзац, иначе самая частая правка без метки.
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
        target["class"] = cls

    out = container.decode_contents() if isinstance(container, Tag) else str(soup)
    return (out or "")[:COPY_LIMIT]
