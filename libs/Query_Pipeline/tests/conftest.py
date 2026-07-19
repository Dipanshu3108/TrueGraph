"""Test fixtures: an in-memory OKF knowledge store and a fake LLM provider."""

import json
import sys
from pathlib import Path

import pytest

# Make the query_engine package importable when tests run from anywhere.
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def build_store(root: Path) -> Path:
    """Create a minimal two-document OKF knowledge store under ``root``."""
    store = root / "knowledge"

    # --- registry -------------------------------------------------------
    _write_json(
        store / "registry" / "documents.json",
        {
            "doc-a": {"title": "Doc A", "pages": 5, "version": 1, "append_metadata": {}},
            "doc-b": {"title": "Doc B", "pages": 3, "version": 1, "append_metadata": {}},
        },
    )
    _write_json(store / "registry" / "aliases.json", {"sample sorcery": "sample-magic"})
    _write_json(
        store / "registry" / "concepts.json",
        {
            "sample-magic": ["doc-a"],
            "sample-energy": ["doc-a"],
            "sample-wand": ["doc-a"],
            "sample-potion": ["doc-b"],
        },
    )
    _write_json(
        store / "registry" / "keywords.json",
        {
            "sample magic": ["doc-a"],
            "magic": ["doc-a", "doc-b"],
            "sample energy": ["doc-a"],
            "sample wand": ["doc-a"],
            "sample potion": ["doc-b"],
        },
    )
    edges = [
        {"source": "sample-magic", "target": "sample-energy", "type": "relates_to",
         "page_numbers": [4], "document": "doc-a"},
        {"source": "sample-energy", "target": "sample-wand", "type": "relates_to",
         "page_numbers": [5], "document": "doc-a"},
        {"source": "sample-magic", "target": "sample-potion", "type": "relates_to",
         "page_numbers": [2], "document": "doc-b"},
    ]
    _write_json(
        store / "registry" / "global_graph.json",
        {"nodes": ["sample-magic", "sample-energy", "sample-wand", "sample-potion"],
         "edges": edges},
    )
    _write_json(store / "registry" / "relationships.json", {"edges": edges})
    _write_json(store / "registry" / "tags.json", {})
    _write_json(store / "registry" / "statistics.json", {"documents": 2, "concepts": 4})

    # --- doc-a bundle ---------------------------------------------------
    _write_json(
        store / "doc-a" / "concepts" / "sample-magic.json",
        {"id": "sample-magic", "name": "Sample Magic",
         "description": "Sample magic is the core concept of the sample world.",
         "page_numbers": [3], "aliases": ["sample sorcery"],
         "keywords": ["sample magic", "magic"]},
    )
    _write_json(
        store / "doc-a" / "concepts" / "sample-energy.json",
        {"id": "sample-energy", "name": "Sample Energy",
         "description": "Sample energy is what powers sample magic.",
         "page_numbers": [4], "aliases": [],
         "keywords": ["sample energy", "energy"]},
    )
    _write_json(
        store / "doc-a" / "concepts" / "sample-wand.json",
        {"id": "sample-wand", "name": "Sample Wand",
         "description": "A sample wand channels sample magic for the caster.",
         "page_numbers": [5], "aliases": [],
         "keywords": ["sample wand", "wand"]},
    )
    _write_json(
        store / "doc-a" / "indexes" / "alias_index.json",
        {"sample sorcery": "sample-magic"},
    )
    _write_json(
        store / "doc-a" / "indexes" / "keyword_index.json",
        {
            "sample magic": ["sample-magic"],
            "magic": ["sample-magic"],
            "sample energy": ["sample-energy"],
            "energy": ["sample-energy", "sample-magic"],
            "sample wand": ["sample-wand"],
            "wand": ["sample-wand"],
        },
    )
    _write_json(
        store / "doc-a" / "indexes" / "page_index.json",
        {"3": ["sample-magic"], "4": ["sample-energy"], "5": ["sample-wand"]},
    )
    for page_number, text in {
        3: "Page three reveals sample magic in detail.",
        4: "Page four explains sample energy.",
        5: "Page five describes the sample wand.",
    }.items():
        _write_json(
            store / "doc-a" / "pages" / f"{page_number}.json",
            {"page_number": page_number, "content": text},
        )

    # --- doc-b bundle ---------------------------------------------------
    _write_json(
        store / "doc-b" / "concepts" / "sample-potion.json",
        {"id": "sample-potion", "name": "Sample Potion",
         "description": "A sample potion is brewed with a pinch of sample magic.",
         "page_numbers": [2], "aliases": [],
         "keywords": ["sample potion", "potion", "magic"]},
    )
    _write_json(store / "doc-b" / "indexes" / "alias_index.json", {})
    _write_json(
        store / "doc-b" / "indexes" / "keyword_index.json",
        {"sample potion": ["sample-potion"], "potion": ["sample-potion"],
         "magic": ["sample-potion"]},
    )
    _write_json(store / "doc-b" / "indexes" / "page_index.json", {"2": ["sample-potion"]})
    _write_json(
        store / "doc-b" / "pages" / "2.json",
        {"page_number": 2, "content": "Page two covers the sample potion recipe."},
    )

    return store


@pytest.fixture
def knowledge_store(tmp_path: Path) -> Path:
    """A minimal two-document knowledge store."""
    return build_store(tmp_path)


class FakeProvider:
    """Deterministic stand-in for the LiteLLM provider."""

    def __init__(self, intent_data=None, answer="Grounded fake answer.", fail=False):
        self.intent_data = intent_data or {
            "intent": "fact-lookup",
            "keywords": ["sample magic"],
            "concepts": ["sample magic"],
            "filters": {},
        }
        self.answer = answer
        self.fail = fail
        self.complete_calls = 0
        self.complete_json_calls = 0
        self.input_tokens = 11
        self.output_tokens = 7

    async def complete_json(self, messages, **kwargs):
        self.complete_json_calls += 1
        if self.fail:
            raise RuntimeError("provider unavailable")
        return self.intent_data

    async def complete(self, messages, **kwargs):
        self.complete_calls += 1
        if self.fail:
            raise RuntimeError("provider unavailable")
        return self.answer

    def get_last_usage(self):
        return self.input_tokens, self.output_tokens


@pytest.fixture
def fake_provider(monkeypatch):
    """Patch both LLM stages to use a FakeProvider; returns the instance."""
    from query_engine import generator, understanding

    provider = FakeProvider()
    monkeypatch.setattr(understanding, "build_provider", lambda config: provider)
    monkeypatch.setattr(generator, "build_provider", lambda config: provider)
    return provider
