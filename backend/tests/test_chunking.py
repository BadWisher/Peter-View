import unittest

from app.llm.chunking import chunk_blocks, compress
from app.llm.documents import Block


def _block(index: int, text: str, block_type: str = "paragraph", **metadata) -> Block:
    return Block(index, text, text, {"type": block_type, **metadata})


class ChunkingTests(unittest.TestCase):
    def test_list_introduction_and_list_are_not_split(self):
        blocks = [
            _block(0, "Before"),
            _block(1, "Choose:", introduces_list=2),
            _block(2, "One", "list_item", list_depth=0, list_intro_index=1),
            _block(3, "Two", "list_item", list_depth=0, list_intro_index=1),
            _block(4, "After"),
        ]

        chunks = chunk_blocks(blocks, chunk_size=2, overlap=0)

        self.assertEqual([[block.index for block in chunk.blocks] for chunk in chunks], [
            [0], [1, 2, 3], [4]
        ])

    def test_chunks_expose_full_adjacent_context(self):
        blocks = [_block(index, f"Block {index}") for index in range(5)]

        chunks = chunk_blocks(blocks, chunk_size=2, overlap=0)

        middle = chunks[1]
        self.assertEqual([block.index for block in middle.before], [1])
        self.assertEqual([block.index for block in middle.after], [4])
        self.assertIn("[1] Block 1", middle.context())
        self.assertIn("[4] Block 4", middle.context())

    def test_overlap_remains_backward_compatible_for_plain_blocks(self):
        blocks = [_block(index, str(index)) for index in range(6)]

        chunks = chunk_blocks(blocks, chunk_size=3, overlap=1)

        self.assertEqual([[block.index for block in chunk.blocks] for chunk in chunks], [
            [0, 1, 2], [2, 3, 4], [4, 5]
        ])
        self.assertEqual(chunks[0].plain(), "0\n1\n2")
        self.assertEqual(chunks[0].raw(), "0\n1\n2")

    def test_compress_tracks_nearest_heading(self):
        blocks = [
            _block(0, "Installation", "heading", level=1),
            _block(1, "Run the installer"),
            _block(2, "Linux", "heading", level=2),
            _block(3, "Use the package manager"),
        ]

        result = compress(blocks)

        self.assertIn("[0] heading/1: Installation", result)
        self.assertIn("[1] [Installation] Run the installer", result)
        self.assertIn("[3] [Linux] Use the package manager", result)


if __name__ == "__main__":
    unittest.main()
