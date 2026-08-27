"""Нарезка документа на чанки по блокам и сжатое представление контекста."""

from __future__ import annotations

from dataclasses import dataclass, field

from .documents import Block

DEFAULT_CHUNK_SIZE = 8
DEFAULT_OVERLAP = 2
COMPRESS_WORDS = 12


@dataclass
class Chunk:
    index: int
    blocks: list[Block]
    before: list[Block] = field(default_factory=list)
    after: list[Block] = field(default_factory=list)

    @property
    def first_block(self) -> int:
        return self.blocks[0].index if self.blocks else 0

    @property
    def last_block(self) -> int:
        return self.blocks[-1].index if self.blocks else 0

    def plain(self) -> str:
        return "\n".join(b.plain for b in self.blocks if b.plain)

    def raw(self) -> str:
        return "\n".join(b.raw for b in self.blocks if b.raw)

    def structured(self) -> str:
        return "\n".join(b.structured() for b in self.blocks)

    def adjacent_blocks(self) -> list[Block]:
        """Полные соседние блоки, доступные вызывающему коду как контекст."""
        return [*self.before, *self.after]

    def context(self) -> str:
        return "\n".join(
            f"[{block.index}] {block.plain}"
            for block in [*self.before, *self.blocks, *self.after]
            if block.plain
        )


def _is_list_item(block: Block) -> bool:
    return block.metadata.get("type") == "list_item"


def _semantic_units(blocks: list[Block]) -> list[list[Block]]:
    """Группирует вводный абзац и непрерывный список в неделимую единицу."""
    units: list[list[Block]] = []
    pos = 0
    while pos < len(blocks):
        block = blocks[pos]
        introduces = block.metadata.get("introduces_list")
        next_is_list = pos + 1 < len(blocks) and _is_list_item(blocks[pos + 1])
        implicit_intro = (
            block.metadata.get("type") in {"paragraph", "blockquote"}
            and next_is_list
            and block.plain.rstrip().endswith((':', '：'))
        )
        if introduces is not None or implicit_intro:
            unit = [block]
            pos += 1
            while pos < len(blocks) and _is_list_item(blocks[pos]):
                unit.append(blocks[pos])
                pos += 1
            units.append(unit)
            continue
        if _is_list_item(block):
            unit = []
            while pos < len(blocks) and _is_list_item(blocks[pos]):
                unit.append(blocks[pos])
                pos += 1
            units.append(unit)
            continue
        units.append([block])
        pos += 1
    return units


def chunk_blocks(
    blocks: list[Block],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Нарезает документ по семантическим единицам с перекрытием.

    Размеры считаются в блоках. Список и вводящий его абзац не разделяются, даже
    если такая единица больше chunk_size. Полные соседние блоки доступны через
    Chunk.before/after и Chunk.context().
    """
    if not blocks:
        return []
    chunk_size = max(1, chunk_size)
    overlap = max(0, overlap)
    if overlap >= chunk_size:
        overlap = chunk_size - 1

    units = _semantic_units(blocks)
    chunks: list[Chunk] = []
    start_unit = 0
    while start_unit < len(units):
        end_unit = start_unit
        count = 0
        while end_unit < len(units):
            unit_size = len(units[end_unit])
            if count and count + unit_size > chunk_size:
                break
            count += unit_size
            end_unit += 1
            if count >= chunk_size:
                break

        window = [block for unit in units[start_unit:end_unit] for block in unit]
        first_pos = blocks.index(window[0])
        last_pos = blocks.index(window[-1])
        chunks.append(Chunk(
            index=len(chunks),
            blocks=window,
            before=blocks[max(0, first_pos - 1):first_pos],
            after=blocks[last_pos + 1:last_pos + 2],
        ))
        if end_unit >= len(units):
            break

        next_start = end_unit
        overlap_count = 0
        while next_start > start_unit and overlap_count < overlap:
            next_start -= 1
            overlap_count += len(units[next_start])
        # A single oversized semantic unit must not make the loop repeat forever.
        start_unit = end_unit if next_start <= start_unit else next_start
    return chunks


def compress(
    blocks: list[Block],
    words: int = COMPRESS_WORDS,
    max_chars: int = 12_000,
) -> str:
    """Сжатое представление блоков: первые N слов каждого блока с его индексом.

    Нужно воркерам 3-4, чтобы видеть весь документ, не утопая в полном тексте.
    """
    lines = []
    heading_path: list[str] = []
    for block in blocks:
        snippet = " ".join(block.plain.split()[:words])
        if snippet:
            if block.metadata.get("type") == "heading":
                level = max(1, int(block.metadata.get("level", 1) or 1))
                heading_path = heading_path[:level - 1]
                heading_path.append(snippet)
                lines.append(f"[{block.index}] heading/{level}: {snippet}")
            else:
                prefix = f" [{heading_path[-1]}]" if heading_path else ""
                lines.append(f"[{block.index}]{prefix} {snippet}")
        if sum(len(line) + 1 for line in lines) >= max_chars:
            lines.append("[context truncated]")
            break
    return "\n".join(lines)
