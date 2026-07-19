"""End-to-end and stage-level tests for the Knowledge Builder pipeline."""

import json
from pathlib import Path
from unittest import mock

import pytest

from knowledge_builder.batching import filter_empty_pages, make_batches
from knowledge_builder.bundle import write_bundle
from knowledge_builder.entry import build_kb
from knowledge_builder.exceptions import ExtractionError
from knowledge_builder.extraction import extract_batch
from knowledge_builder.io_loader import load_pages
from knowledge_builder.merge import merge_document
from knowledge_builder.okf_generator import write_concepts
from knowledge_builder.registry import update_registry
from knowledge_builder.relationships import build_relationships
from knowledge_builder.scheduler import run_batches
from knowledge_builder.search_index import build_indexes
from knowledge_builder.types import (
    Batch,
    Concept,
    ExtractionResult,
    Page,
    Relationship,
    ValidationReport,
)
from knowledge_builder.validation import validate_extractions


@pytest.fixture
def sample_md(tmp_path: Path) -> Path:
    """Create a small parsed markdown file."""
    md = tmp_path / "sample.md"
    md.write_text(
        "# Sample-Document.pdf\n\n"
        "## Metadata\n\n"
        "- title: Sample Document\n"
        "- author: Tester\n\n"
        "---\n\n"
        "# Page 1\n\n"
        "# Page 2\n\n"
        "Introduction to the sample.\n\n"
        "# Page 3\n\n"
        "The core concept is sample magic.\n\n"
        "# Page 4\n\n"
        "Sample magic depends on sample energy.\n\n"
        "# Page 5\n\n\n",
        encoding="utf-8",
    )
    return md


@pytest.fixture
def sample_json(tmp_path: Path) -> Path:
    """Create a normalized JSON input file."""
    data = {
        "file_name": "Sample-Document.pdf",
        "metadata": {"title": "Sample Document"},
        "pages": [
            {"page_number": 1, "content": ""},
            {"page_number": 2, "content": "Introduction."},
            {"page_number": 3, "content": "Core concept."},
        ],
    }
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestLoadPages:
    def test_loads_markdown(self, sample_md: Path):
        file_name, metadata, pages = load_pages(str(sample_md))
        assert file_name == "Sample-Document.pdf"
        assert metadata.get("title") == "Sample Document"
        assert [p.page_number for p in pages] == [1, 2, 3, 4, 5]
        assert pages[0].content == ""
        assert "Introduction" in pages[1].content

    def test_loads_json(self, sample_json: Path):
        file_name, metadata, pages = load_pages(str(sample_json))
        assert file_name == "Sample-Document.pdf"
        assert metadata.get("title") == "Sample Document"
        assert [p.page_number for p in pages] == [1, 2, 3]


class TestBatching:
    def test_filter_empty_pages(self):
        pages = [
            Page(page_number=1, content=""),
            Page(page_number=2, content="   "),
            Page(page_number=3, content="Text"),
            Page(page_number=4, content="More"),
        ]
        kept, dropped = filter_empty_pages(pages)
        assert [p.page_number for p in kept] == [3, 4]
        assert dropped == [1, 2]

    def test_make_batches_covers_all_pages(self):
        pages = [Page(page_number=i, content=f"page {i}") for i in range(1, 6)]
        batches = make_batches(pages, 2)
        assert len(batches) == 3
        assert batches[-1].page_numbers == [5]
        assert [b.page_numbers for b in batches] == [[1, 2], [3, 4], [5]]
        assert all(b.page_numbers for b in batches)

    def test_batch_content_includes_page_markers(self):
        pages = [Page(page_number=1, content="A"), Page(page_number=2, content="B")]
        batch = make_batches(pages, 2)[0]
        assert "### Page 1" in batch.content
        assert "### Page 2" in batch.content


class _FakeLLMProvider:
    """Deterministic LLM provider for pipeline tests."""

    def __init__(self, config=None):
        self.config = config

    def get_last_usage(self) -> tuple[int, int]:
        return (0, 0)

    async def complete_json(self, messages, **kwargs) -> dict:
        # The batch content contains markers like "### Page N".
        content = messages[-1]["content"]
        numbers = [int(n) for n in __import__("re").findall(r"### Page (\d+)", content)]
        concept_name = f"Batch Concept {min(numbers)}-{max(numbers)}"
        return {
            "concepts": [
                {
                    "name": concept_name,
                    "description": f"Concept extracted from pages {numbers}.",
                    "page_numbers": numbers,
                    "aliases": [f"alias-{min(numbers)}"],
                    "keywords": ["sample", "magic"],
                }
            ],
            "relationships": [],
            "keywords": ["sample"],
            "aliases": [],
            "glossary": [],
            "procedures": [],
            "apis": [],
        }


@pytest.fixture
def fake_extraction(monkeypatch):
    """Replace the LiteLLM provider used by extraction with a fake."""
    monkeypatch.setattr(
        "knowledge_builder.extraction.LiteLLMProvider",
        _FakeLLMProvider,
    )


class TestSchedulerAndExtraction:
    async def test_run_batches_returns_results(self, sample_md: Path, fake_extraction):
        _, _, pages = load_pages(str(sample_md))
        content_pages, _ = filter_empty_pages(pages)
        batches = make_batches(content_pages, 2)
        config = {
            "model_name": "fake-model",
            "provider": "fake",
            "api_key": "fake-key",
            "num_sub_agents": 2,
            "page_batch": 2,
        }
        results, _usage_log = await run_batches(batches, config)
        assert len(results) == len(batches)
        assert all(isinstance(r, ExtractionResult) for r in results)
        # Concepts only cite pages from their batch.
        batches_by_id = {b.batch_id: b for b in batches}
        for result in results:
            batch = batches_by_id[result.batch_id]
            for concept in result.concepts:
                assert all(p in batch.page_numbers for p in concept.page_numbers)


class TestValidationAndMerge:
    def test_validate_extractions_drops_invalid_pages(self):
        concept = Concept(
            id="c1",
            name="Valid",
            description="desc",
            page_numbers=[1],
            aliases=["alias"],
            keywords=["kw"],
        )
        bad_concept = Concept(
            id="c2",
            name="Bad",
            description="desc",
            page_numbers=[99],
            aliases=[],
            keywords=[],
        )
        result = ExtractionResult(
            batch_id=1,
            page_numbers=[1, 2],
            concepts=[concept, bad_concept],
            relationships=[],
            keywords=["kw", ""],
            aliases=[("alias", "c1"), ("", "c2")],
        )
        cleaned, report = validate_extractions([result])
        assert len(cleaned[0].concepts) == 1
        assert cleaned[0].concepts[0].id == "c1"
        assert report.dropped_concepts
        assert "" not in cleaned[0].keywords

    def test_merge_document_deduplicates_concepts(self):
        results = [
            ExtractionResult(
                batch_id=1,
                page_numbers=[1, 2],
                concepts=[
                    Concept(
                        id="sample-magic",
                        name="Sample Magic",
                        description="desc",
                        page_numbers=[1],
                        aliases=["magic"],
                        keywords=["a"],
                    )
                ],
                relationships=[],
                keywords=["a"],
                aliases=[("magic", "Sample Magic")],
            ),
            ExtractionResult(
                batch_id=2,
                page_numbers=[3, 4],
                concepts=[
                    Concept(
                        id="sample-magic",
                        name="Sample Magic",
                        description="longer description",
                        page_numbers=[4],
                        aliases=["spell"],
                        keywords=["b"],
                    )
                ],
                relationships=[
                    Relationship(
                        source="sample-magic",
                        target="sample-energy",
                        type="depends_on",
                        page_numbers=[4],
                    )
                ],
                keywords=["b"],
                aliases=[("spell", "Sample Magic")],
            ),
        ]
        merged = merge_document(
            results,
            document_id="sample-document",
            file_name="Sample-Document.pdf",
            pages_total=4,
            dropped_pages=[],
        )
        assert len(merged.concepts) == 1
        concept = merged.concepts[0]
        assert concept.page_numbers == [1, 4]
        assert sorted(concept.aliases) == ["magic", "spell"]
        assert sorted(concept.keywords) == ["a", "b"]
        assert "longer description" == concept.description
        assert len(merged.relationships) == 1


class TestGraphAndOutput:
    def test_build_relationships_resolves_local_graph(self):
        concept = Concept(id="a", name="A", description="", page_numbers=[1])
        rel = Relationship(source="a", target="b", type="references", page_numbers=[1])
        merged = merge_document(
            [
                ExtractionResult(
                    batch_id=1,
                    page_numbers=[1],
                    concepts=[concept],
                    relationships=[rel],
                )
            ],
            document_id="doc",
        )
        graph = build_relationships(merged)
        assert "a" in graph.nodes
        assert len(graph.edges) == 0  # target b is not a known concept

    def test_write_concepts_and_indexes_and_bundle(self, tmp_path: Path):
        concept = Concept(
            id="sample-magic",
            name="Sample Magic",
            description="desc",
            page_numbers=[2, 3],
            aliases=["magic"],
            keywords=["sample"],
        )
        merged = merge_document(
            [
                ExtractionResult(
                    batch_id=1,
                    page_numbers=[2, 3],
                    concepts=[concept],
                    relationships=[],
                    keywords=["sample"],
                    aliases=[("magic", "Sample Magic")],
                )
            ],
            document_id="sample-doc",
            file_name="Sample.pdf",
            metadata={"title": "Sample"},
            append_metadata={"category": "test"},
            pages_total=3,
            dropped_pages=[1],
        )
        graph = build_relationships(merged)
        bundle_dir = tmp_path / "sample-doc"
        write_concepts(merged, graph, str(bundle_dir))
        build_indexes(merged, str(bundle_dir))

        assert (bundle_dir / "concepts" / "sample-magic.json").is_file()
        assert (bundle_dir / "document.json").is_file()
        assert (bundle_dir / "metadata.json").is_file()
        assert (bundle_dir / "indexes" / "keyword_index.json").is_file()
        assert (bundle_dir / "indexes" / "alias_index.json").is_file()

    def test_update_registry_merges_bundle(self, tmp_path: Path):
        bundle_dir = tmp_path / "sample-doc"
        bundle_dir.mkdir()
        (bundle_dir / "concepts").mkdir()
        (bundle_dir / "indexes").mkdir()
        (bundle_dir / "documents").mkdir()
        (bundle_dir / "pages").mkdir()
        (bundle_dir / "assets").mkdir()

        concept = {"id": "sample-magic", "name": "Sample Magic", "page_numbers": [2]}
        (bundle_dir / "concepts" / "sample-magic.json").write_text(
            json.dumps(concept), encoding="utf-8"
        )
        (bundle_dir / "document.json").write_text(
            json.dumps(
                {
                    "id": "sample-doc",
                    "title": "Sample",
                    "pages_total": 3,
                    "append_metadata": {"category": "test"},
                    "relationships_count": 0,
                }
            ),
            encoding="utf-8",
        )
        (bundle_dir / "relationship_graph.json").write_text(
            json.dumps({"nodes": ["sample-magic"], "edges": []}), encoding="utf-8"
        )
        (bundle_dir / "indexes" / "keyword_index.json").write_text(
            json.dumps({"sample": ["sample-magic"]}), encoding="utf-8"
        )
        (bundle_dir / "indexes" / "alias_index.json").write_text(
            json.dumps({"magic": "sample-magic"}), encoding="utf-8"
        )
        (bundle_dir / "validation_report.json").write_text(
            json.dumps({"total_batches": 1, "valid_batches": 1, "invalid_batches": 0}),
            encoding="utf-8",
        )

        knowledge_store = tmp_path / "knowledge"
        update_registry(str(bundle_dir), str(knowledge_store))

        registry = knowledge_store / "registry"
        assert (registry / "documents.json").is_file()
        assert (registry / "concepts.json").is_file()
        assert (registry / "aliases.json").is_file()
        assert (registry / "keywords.json").is_file()
        assert (registry / "statistics.json").is_file()

        documents = json.loads((registry / "documents.json").read_text(encoding="utf-8"))
        assert "sample-doc" in documents
        concepts = json.loads((registry / "concepts.json").read_text(encoding="utf-8"))
        assert concepts["sample-magic"] == ["sample-doc"]


class TestBuildKb:
    def test_full_pipeline(self, sample_md: Path, tmp_path: Path, fake_extraction):
        knowledge_store = tmp_path / "knowledge"
        config = {
            "model_name": "fake-model",
            "provider": "fake",
            "api_key": "fake-key",
            "knowledge_store_path": str(knowledge_store),
            "num_sub_agents": 2,
            "page_batch": 2,
            "append_metadata": {"category": "test", "source": "unit-test"},
        }
        result = build_kb(str(sample_md), config)

        assert result.document_id == "sample-document"
        assert result.pages_total == 5
        assert result.pages_extracted == 3  # pages 1, 2, 5 empty
        assert result.concepts_count > 0
        assert result.validation_report_path

        bundle_path = Path(result.bundle_path)
        assert bundle_path.is_dir()
        assert (bundle_path / "document.json").is_file()
        assert (bundle_path / "metadata.json").is_file()
        assert (bundle_path / "validation_report.json").is_file()
        assert (bundle_path / "concepts").is_dir()
        assert (bundle_path / "indexes").is_dir()
        assert (bundle_path / "pages" / "2.json").is_file()
        assert (bundle_path / "documents" / "sample-document.md").is_file()

        registry = knowledge_store / "registry"
        assert (registry / "documents.json").is_file()
        documents = json.loads((registry / "documents.json").read_text(encoding="utf-8"))
        assert documents[result.document_id]["append_metadata"]["category"] == "test"

    def test_full_pipeline_json_input(self, sample_json: Path, tmp_path: Path, fake_extraction):
        knowledge_store = tmp_path / "knowledge"
        config = {
            "model_name": "fake-model",
            "provider": "fake",
            "api_key": "fake-key",
            "knowledge_store_path": str(knowledge_store),
            "num_sub_agents": 2,
            "page_batch": 2,
        }
        result = build_kb(str(sample_json), config)
        assert result.document_id == "sample-document"
        assert result.pages_total == 3
        assert result.pages_extracted == 2
        assert (Path(result.bundle_path) / "document.json").is_file()


# ---------------------------------------------------------------------------
# Image-page support
# ---------------------------------------------------------------------------

# Smallest valid PNG (1x1 transparent), used as stand-in image bytes.
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d49444154789c6264f8cf500f000318630059c9"
    "7b6b0000000049454e44ae426082"
)


def _write_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_TINY_PNG)
    return path


def _write_image_md(tmp_path: Path, page_lines: list[str]) -> Path:
    """Build a parsed-md fixture whose page bodies are the given lines."""
    parts = ["# Image-Document.pdf", "", "## Metadata", "", "- _No metadata_", "", "---", ""]
    for i, line in enumerate(page_lines, start=1):
        parts.extend([f"# Page {i}", "", line, ""])
    md = tmp_path / "image_doc.md"
    md.write_text("\n".join(parts), encoding="utf-8")
    return md


class _CapturingVisionProvider:
    """Fake provider that records the messages it receives."""

    last_messages: list | None = None

    def __init__(self, config=None):
        self.config = config

    def get_last_usage(self) -> tuple[int, int]:
        return (0, 0)

    async def complete_json(self, messages, **kwargs) -> dict:
        type(self).last_messages = messages
        return {
            "concepts": [
                {
                    "name": "Visual Concept",
                    "description": "Extracted from page images.",
                    "page_numbers": [1],
                    "aliases": [],
                    "keywords": ["visual"],
                }
            ],
            "relationships": [],
            "keywords": ["visual"],
            "aliases": [],
            "glossary": [],
            "procedures": [],
            "apis": [],
        }


class TestImagePageClassification:
    def test_absolute_windows_path_is_image(self, tmp_path: Path):
        image = _write_image(tmp_path / "storage" / "doc" / "doc_page_1.webp")
        md = _write_image_md(tmp_path, [str(image)])
        _, _, pages = load_pages(str(md))
        assert pages[0].content_type == "image"
        assert Path(pages[0].content).is_absolute()

    def test_relative_path_resolves_against_image_storage(self, tmp_path: Path):
        storage = tmp_path / "storage"
        image = _write_image(storage / "doc" / "doc_page_1.webp")
        md = _write_image_md(tmp_path, ["doc/doc_page_1.webp"])
        _, _, pages = load_pages(str(md), image_storage_path=str(storage))
        assert pages[0].content_type == "image"
        assert Path(pages[0].content) == image

    def test_relative_path_falls_back_to_document_dir(self, tmp_path: Path):
        image = _write_image(tmp_path / "doc_page_1.webp")
        md = _write_image_md(tmp_path, ["doc_page_1.webp"])
        _, _, pages = load_pages(str(md))
        assert pages[0].content_type == "image"
        assert Path(pages[0].content) == image

    def test_image_path_embedded_in_prose_stays_text(self, tmp_path: Path):
        md = _write_image_md(tmp_path, ["See figure at images/page_1.webp for details."])
        _, _, pages = load_pages(str(md))
        assert pages[0].content_type == "text"

    def test_multiline_page_with_image_path_stays_text(self, tmp_path: Path):
        md = _write_image_md(tmp_path, ["Intro text.\nimages/page_1.webp"])
        _, _, pages = load_pages(str(md))
        assert pages[0].content_type == "text"


class TestImageFilteringAndBatching:
    def test_filter_drops_missing_image_file(self, tmp_path: Path):
        real = _write_image(tmp_path / "page_1.webp")
        pages = [
            Page(page_number=1, content=str(real), content_type="image"),
            Page(page_number=2, content=str(tmp_path / "nope.webp"), content_type="image"),
        ]
        kept, dropped = filter_empty_pages(pages)
        assert [p.page_number for p in kept] == [1]
        assert dropped == [2]

    def test_batches_split_on_content_type_runs(self, tmp_path: Path):
        img1 = _write_image(tmp_path / "p3.webp")
        img2 = _write_image(tmp_path / "p4.webp")
        pages = [
            Page(page_number=1, content="alpha"),
            Page(page_number=2, content="beta"),
            Page(page_number=3, content=str(img1), content_type="image"),
            Page(page_number=4, content=str(img2), content_type="image"),
            Page(page_number=5, content="gamma"),
        ]
        batches = make_batches(pages, page_batch=2, image_page_batch=1)
        assert [b.content_type for b in batches] == ["text", "image", "image", "text"]
        assert [b.page_numbers for b in batches] == [[1, 2], [3], [4], [5]]
        # Text batches keep the v1 joined-string shape; image batches carry pairs.
        assert "### Page 1" in batches[0].content
        assert batches[1].content == [(3, str(img1))]

    def test_image_run_chunked_by_image_page_batch(self, tmp_path: Path):
        pages = [
            Page(
                page_number=i,
                content=str(_write_image(tmp_path / f"p{i}.webp")),
                content_type="image",
            )
            for i in range(1, 4)
        ]
        batches = make_batches(pages, page_batch=1, image_page_batch=2)
        assert [b.page_numbers for b in batches] == [[1, 2], [3]]
        assert all(b.content_type == "image" for b in batches)


class TestImageExtraction:
    async def test_image_batch_builds_multimodal_message(
        self, tmp_path: Path, monkeypatch
    ):
        img1 = _write_image(tmp_path / "page_1.webp")
        img2 = _write_image(tmp_path / "page_2.png")
        monkeypatch.setattr(
            "knowledge_builder.extraction.LiteLLMProvider", _CapturingVisionProvider
        )
        batch = Batch(
            batch_id=1,
            page_numbers=[1, 2],
            content=[(1, str(img1)), (2, str(img2))],
            content_type="image",
        )
        config = {"model_name": "fake-vision", "provider": "fake", "api_key": "k"}
        result = await extract_batch(batch, config)

        messages = _CapturingVisionProvider.last_messages
        assert messages is not None
        user_content = messages[-1]["content"]
        assert isinstance(user_content, list)
        text_blocks = [b for b in user_content if b["type"] == "text"]
        image_blocks = [b for b in user_content if b["type"] == "image_url"]
        assert any("### Page 1" in b["text"] for b in text_blocks)
        assert any("### Page 2" in b["text"] for b in text_blocks)
        assert len(image_blocks) == 2
        assert image_blocks[0]["image_url"]["url"].startswith("data:image/webp;base64,")
        assert image_blocks[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert result.content_type == "image"
        assert result.concepts[0].name == "Visual Concept"

    async def test_image_batch_missing_file_raises(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(
            "knowledge_builder.extraction.LiteLLMProvider", _CapturingVisionProvider
        )
        batch = Batch(
            batch_id=1,
            page_numbers=[1],
            content=[(1, str(tmp_path / "missing.webp"))],
            content_type="image",
        )
        config = {"model_name": "fake-vision", "provider": "fake", "api_key": "k"}
        with pytest.raises(ExtractionError):
            await extract_batch(batch, config)


class TestImageBundleAndBuild:
    def test_bundle_copies_image_assets(self, tmp_path: Path):
        image = _write_image(tmp_path / "storage" / "page_2.webp")
        store = tmp_path / "store"
        report = ValidationReport(total_batches=1, valid_batches=1)
        pages = [
            Page(page_number=1, content="text page"),
            Page(page_number=2, content=str(image), content_type="image"),
        ]
        bundle_path = Path(
            write_bundle(
                str(store / "image-doc"),
                str(store),
                "image-doc",
                report,
                pages=pages,
            )
        )
        assert (bundle_path / "assets" / "page_2.webp").is_file()
        page_json = json.loads(
            (bundle_path / "pages" / "2.json").read_text(encoding="utf-8")
        )
        assert page_json["content_type"] == "image"
        assert not (bundle_path / "assets" / "page_1.webp").exists()

    def test_build_kb_image_document(self, tmp_path: Path, monkeypatch):
        images = [
            _write_image(tmp_path / "storage" / f"doc_page_{i}.webp") for i in range(1, 4)
        ]
        md = _write_image_md(tmp_path, [str(p) for p in images])
        monkeypatch.setattr(
            "knowledge_builder.extraction.LiteLLMProvider", _CapturingVisionProvider
        )
        monkeypatch.setattr(
            "knowledge_builder.entry._check_vision_capability", lambda config: None
        )
        config = {
            "model_name": "fake-vision",
            "provider": "fake",
            "api_key": "k",
            "knowledge_store_path": str(tmp_path / "knowledge"),
            "num_sub_agents": 2,
            "page_batch": 2,
            "image_page_batch": 2,
        }
        result = build_kb(str(md), config)
        assert result.pages_total == 3
        assert result.pages_extracted == 3
        bundle_path = Path(result.bundle_path)
        for i in range(1, 4):
            assert (bundle_path / "assets" / f"page_{i}.webp").is_file()

    def test_build_kb_rejects_non_vision_model_for_image_doc(
        self, tmp_path: Path, monkeypatch
    ):
        image = _write_image(tmp_path / "storage" / "doc_page_1.webp")
        md = _write_image_md(tmp_path, [str(image)])

        def _reject(config):
            from knowledge_builder.exceptions import KnowledgeBuilderError

            raise KnowledgeBuilderError("model cannot see")

        monkeypatch.setattr("knowledge_builder.entry._check_vision_capability", _reject)
        config = {
            "model_name": "text-only-model",
            "provider": "fake",
            "api_key": "k",
            "knowledge_store_path": str(tmp_path / "knowledge"),
        }
        from knowledge_builder.exceptions import KnowledgeBuilderError

        with pytest.raises(KnowledgeBuilderError):
            build_kb(str(md), config)
