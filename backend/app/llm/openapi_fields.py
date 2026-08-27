"""Извлечение вычитываемых текстовых полей из OpenAPI YAML.

В документации API нас интересуют только человекочитаемые поля:
- summary – заголовок метода (в paths.<url>.<method>);
- description – описание метода, ответа (responses.<код>.description) или поля схемы
  (components.schemas...properties.<field>.description, в т.ч. вложенные в anyOf/items).

Для каждого поля сохраняем YAML-путь (для сопоставления RU↔EN и диффа), номер строки
в файле (чтобы писатель нашёл место в GitLab/VS Code), сам текст, тип и человекочитаемый
контекст блока. Парсим через ruamel.yaml в round-trip режиме – он сохраняет номера строк.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

logger = logging.getLogger(__name__)

TARGET_KEYS = ("summary", "description")
HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head", "trace"}

# Кэш разобранных полей по содержимому файла: пагинация и дифф не переразбирают
# один и тот же 18k-строчный YAML повторно.
_CACHE: dict[str, list[dict]] = {}
_CACHE_MAX = 8


_KV_LINE = re.compile(r"^(\s*(?:-\s+)?)([^:\n]+?):(\s+)(\S.*?)\s*$")


def _new_yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    return yaml


def _sanitize_inline_colons(text: str) -> str:
    """Экранирует строковые значения с «: » внутри (напр. «Возможные значения: A, B»).

    Реальные OpenAPI-файлы из JS-тулинга часто содержат двоеточие с пробелом в
    неэкранированных summary/description – это нарушает строгий YAML. Заворачиваем
    такие однострочные значения в кавычки, не меняя число строк (номера сохраняются).
    """
    fixed: list[str] = []
    for line in text.split("\n"):
        m = _KV_LINE.match(line)
        if not m:
            fixed.append(line)
            continue
        indent, key, sep, val = m.groups()
        if ": " not in val:
            fixed.append(line)
            continue
        if val[0] in "\"'|>[{!&*#":
            fixed.append(line)
            continue
        safe = val.replace("\\", "\\\\").replace('"', '\\"')
        fixed.append(f'{indent}{key}:{sep}"{safe}"')
    return "\n".join(fixed)


def _load(yaml_bytes: bytes):
    text = yaml_bytes.decode("utf-8", errors="replace")
    try:
        return _new_yaml().load(io.StringIO(text))
    except YAMLError:
        try:
            return _new_yaml().load(io.StringIO(_sanitize_inline_colons(text)))
        except YAMLError as e:
            raise ValueError(f"Не удалось разобрать YAML: {e}") from e


def _kind(path: list[str]) -> str:
    last = path[-1]
    if last == "summary":
        return "summary"
    if path and path[0] == "components":
        return "schema_description"
    if "responses" in path:
        return "response_description"
    if path and path[0] == "paths":
        return "path_description"
    return "description"


def _context(path: list[str]) -> str:
    """Человекочитаемый контекст блока из YAML-пути.

    Главное – где находится поле и что это за поле, чтобы писатель сразу понял,
    к какому методу/схеме относится текст.
    """
    if path and path[0] == "paths" and len(path) >= 3:
        url, method = path[1], path[2].upper()
        tail = path[3:]
        base = f"{method} {url}"
        if "responses" in tail:
            i = tail.index("responses")
            code = tail[i + 1] if len(tail) > i + 1 else "?"
            return f"{base} · ответ {code}"
        if tail and tail[-1] == "summary":
            return f"{base} · заголовок"
        return f"{base} · описание метода"
    if path and path[0] == "components" and len(path) >= 3:
        schema = path[2]
        if "properties" in path:
            i = path.index("properties")
            if len(path) > i + 1:
                return f"Схема {schema} · поле «{path[i + 1]}»"
        return f"Схема {schema} · описание"
    return ".".join(path)


def _key_line(node, key) -> int | None:
    """Номер строки (1-based) объявления ключа в файле."""
    lc = getattr(node, "lc", None)
    if lc is not None and getattr(lc, "data", None) and key in lc.data:
        return int(lc.data[key][0]) + 1
    return None


def _walk(node, path: list[str], out: list[dict]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child = path + [str(key)]
            if key in TARGET_KEYS and isinstance(value, str):
                out.append({
                    "key": str(key),
                    "path": child,
                    "path_str": "/".join(child),
                    "line": _key_line(node, key),
                    "text": value,
                    "kind": _kind(child),
                    "context": _context(child),
                })
            else:
                _walk(value, child, out)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _walk(item, path + [f"[{i}]"], out)


def extract_fields(yaml_bytes: bytes) -> list[dict]:
    """Все вычитываемые поля (summary/description) с путём, строкой и контекстом."""
    key = hashlib.sha256(yaml_bytes).hexdigest()
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    root = _load(yaml_bytes)
    out: list[dict] = []
    if root is not None:
        _walk(root, [], out)
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = out
    return out


_KEY_RE = re.compile(r"^(\s*)([^:]+):(.*)$")
_BOOL_NULL = {"true", "false", "null", "~", "yes", "no", "on", "off"}


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _needs_quote(v: str) -> bool:
    if v == "" or v != v.strip():
        return True
    if v[0] in "!&*?|>%@`\"'#,[]{}-":
        return True
    if ": " in v or " #" in v:
        return True
    if v.lower() in _BOOL_NULL:
        return True
    stripped = v.replace(",", "").replace(" ", "")
    if stripped and (stripped.lstrip("-+").replace(".", "", 1).isdigit()):
        return True
    return False


def _dq(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _serialize_inline(key_indent: int, key: str, style: str, value: str) -> list[str]:
    pad = " " * key_indent
    if "\n" in value:
        cpad = " " * (key_indent + 2)
        out = [f"{pad}{key}: |-"]
        out += [(cpad + ln if ln else "") for ln in value.split("\n")]
        return out
    if style == "'" and "'" not in value and not _needs_quote(value):
        return [f"{pad}{key}: '{value}'"]
    if style == '"' or _needs_quote(value):
        return [f"{pad}{key}: {_dq(value)}"]
    return [f"{pad}{key}: {value}"]


def _block_content_end(lines: list[str], i0: int, key_indent: int) -> tuple[int, int]:
    """Возвращает (последний индекс строки контента блочного скаляра, отступ контента)."""
    last = i0
    cind = None
    j = i0 + 1
    while j < len(lines):
        if lines[j].strip() == "":
            j += 1
            continue
        if _indent(lines[j]) > key_indent:
            if cind is None:
                cind = _indent(lines[j])
            last = j
            j += 1
        else:
            break
    return last, (cind if cind is not None else key_indent + 2)


def _inline_value_end(lines: list[str], i0: int, key_indent: int) -> int:
    """Последняя строка инлайн-скаляра (учитывает многострочные plain-значения)."""
    last = i0
    j = i0 + 1
    while j < len(lines) and lines[j].strip() != "" and _indent(lines[j]) > key_indent:
        last = j
        j += 1
    return last


def apply_edits(yaml_bytes: bytes, edits: dict[str, str]) -> bytes:
    """Применяет правки к исходному тексту минимально: меняются только строки

    отредактированных полей, всё остальное остаётся байт-в-байт. Это сохраняет
    чистый дифф в Git (полный round-trip ruamel переписал бы тысячи строк).
    """
    if not edits:
        return yaml_bytes
    text = yaml_bytes.decode("utf-8", errors="replace")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()

    by_path = {f["path_str"]: f for f in extract_fields(yaml_bytes)}
    items = []
    for path, value in edits.items():
        f = by_path.get(path)
        if f and f.get("line"):
            items.append((int(f["line"]), value))
    # снизу вверх, чтобы правки не сдвигали номера строк ниже
    items.sort(key=lambda x: x[0], reverse=True)

    for line, value in items:
        i0 = line - 1
        if i0 < 0 or i0 >= len(lines):
            continue
        m = _KEY_RE.match(lines[i0])
        if not m:
            continue
        key_indent = len(m.group(1))
        key = m.group(2)
        rest = m.group(3).strip()
        if rest[:1] in ("|", ">"):
            last, cind = _block_content_end(lines, i0, key_indent)
            cpad = " " * cind
            new_content = [(cpad + ln if ln else "") for ln in value.split("\n")]
            lines = lines[:i0 + 1] + new_content + lines[last + 1:]
        else:
            style = rest[:1] if rest[:1] in ('"', "'") else ""
            last = _inline_value_end(lines, i0, key_indent)
            new_lines = _serialize_inline(key_indent, key, style, value)
            lines = lines[:i0] + new_lines + lines[last + 1:]

    out = newline.join(lines)
    if text.endswith("\n") and not out.endswith("\n"):
        out += newline
    return out.encode("utf-8")


def pair_fields(ru_fields: list[dict], en_fields: list[dict]) -> list[dict]:
    """Сопоставляет RU и EN поля по одинаковому YAML-пути (Smartcat-сетка).

    Порядок – как в RU-файле; поля, которые есть только в EN, добавляются в конец.
    """
    en_by_path = {f["path_str"]: f for f in en_fields}
    used: set[str] = set()
    rows: list[dict] = []

    for ru in ru_fields:
        en = en_by_path.get(ru["path_str"])
        if en is not None:
            used.add(ru["path_str"])
        rows.append({
            "path_str": ru["path_str"],
            "kind": ru["kind"],
            "context": ru["context"],
            "ru_text": ru["text"],
            "ru_line": ru["line"],
            "en_text": en["text"] if en else None,
            "en_line": en["line"] if en else None,
        })

    for en in en_fields:
        if en["path_str"] in used:
            continue
        rows.append({
            "path_str": en["path_str"],
            "kind": en["kind"],
            "context": en["context"],
            "ru_text": None,
            "ru_line": None,
            "en_text": en["text"],
            "en_line": en["line"],
        })
    return rows


def _field_name(field: dict) -> str | None:
    """Имя свойства схемы (лист после последнего properties)."""
    path = field.get("path", [])
    if "properties" in path:
        i = len(path) - 1 - path[::-1].index("properties")
        if len(path) > i + 1:
            return path[i + 1]
    return None


def _norm_text(t: str) -> str:
    t = re.sub(r"\s+", " ", (t or "").strip())
    return t.rstrip(" .;:").casefold()


def _text_reason(texts: list[str]) -> str:
    """Чем именно отличаются варианты, совпадающие по смыслу."""
    if len({t.lower() for t in texts}) == 1:
        return "разный регистр"
    if len({re.sub(r"\s+", " ", t).strip() for t in texts}) == 1:
        return "лишние пробелы"
    if len({t.rstrip(" .,;:!?").strip() for t in texts}) == 1:
        return "разный знак в конце"
    return "разное написание"


def consistency_report(fields: list[dict], limit: int = 60, top: int = 8) -> dict:
    """Находит описания, которые стоило бы привести к единому виду.

    by_name – поля схем с одинаковым именем, но разными описаниями.
    by_text – описания, совпадающие по смыслу, но отличающиеся написанием
      (регистр/пунктуация/пробелы), напр. «Дата создания» и «Дата создания.».
    """
    # by_name: группировка полей схем по имени свойства
    name_groups: dict[str, list[dict]] = {}
    for f in fields:
        if f["kind"] != "schema_description":
            continue
        name = _field_name(f)
        if name:
            name_groups.setdefault(name, []).append(f)

    by_name = []
    for name, items in name_groups.items():
        variants: dict[str, list[dict]] = {}
        for f in items:
            variants.setdefault(f["text"].strip(), []).append(f)
        if len(variants) > 1:
            norms = [_norm_text(t) for t in variants]
            near = len(set(norms)) < len(norms)
            full = _variants(variants)
            by_name.append({
                "name": name,
                "count": len(items),
                "near": near,
                "variants_total": len(variants),
                "variants": full[:top],
            })
    # сначала почти-дубли (быстрые правки), затем компактные группы, где выбор очевиднее
    by_name.sort(key=lambda g: (not g["near"], g["variants_total"], -g["count"]))

    # by_text: одинаковый смысл, разное написание
    text_groups: dict[str, list[dict]] = {}
    for f in fields:
        if f["kind"] not in ("schema_description", "response_description", "path_description"):
            continue
        n = _norm_text(f["text"])
        if n:
            text_groups.setdefault(n, []).append(f)

    by_text = []
    for _, items in text_groups.items():
        variants = {}
        for f in items:
            variants.setdefault(f["text"].strip(), []).append(f)
        if len(variants) > 1:
            full = _variants(variants)
            by_text.append({
                "count": len(items),
                "reason": _text_reason(list(variants.keys())),
                "variants_total": len(variants),
                "variants": full[:top],
            })
    by_text.sort(key=lambda g: (-g["count"], -len(g["variants"])))

    return {
        "by_name": by_name[:limit],
        "by_text": by_text[:limit],
        "by_name_total": len(by_name),
        "by_text_total": len(by_text),
    }


def _variants(variants: dict[str, list[dict]]) -> list[dict]:
    return [
        {
            "text": txt,
            "count": len(fs),
            "examples": [{"context": x["context"], "line": x["line"]} for x in fs[:6]],
        }
        for txt, fs in sorted(variants.items(), key=lambda kv: -len(kv[1]))
    ]


def diff_fields(old_fields: list[dict], new_fields: list[dict]) -> list[dict]:
    """Изменённые поля между версиями: added (нового пути не было) / changed (текст другой)."""
    old_by_path = {f["path_str"]: f for f in old_fields}
    changes: list[dict] = []
    for new in new_fields:
        old = old_by_path.get(new["path_str"])
        if old is None:
            status = "added"
            old_text = None
        elif (old.get("text") or "") != (new.get("text") or ""):
            status = "changed"
            old_text = old["text"]
        else:
            continue
        changes.append({
            "path_str": new["path_str"],
            "kind": new["kind"],
            "context": new["context"],
            "line": new["line"],
            "old_text": old_text,
            "new_text": new["text"],
            "status": status,
        })
    return changes
