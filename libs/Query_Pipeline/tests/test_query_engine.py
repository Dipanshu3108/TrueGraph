"""Stage-level and end-to-end tests for the query engine pipeline."""

import json
from pathlib import Path

import pytest

from query_engine import ask
from query_engine.citations import build_citations
from query_engine.context_builder import build_context, estimate_tokens
from query_engine.entry import _NO_RESULTS_ANSWER
from query_engine.evidence import load_evidence
from query_engine.planner import build_retrieval_plan
from query_engine.ranker import (
    alias_ranking,
    bm25_ranking,
    graph_ranking,
    rank_candidates,
)
from query_engine.response import build_response
from query_engine.retriever import retrieve_candidates
from query_engine.scope import resolve_scope
from query_engine.types import Candidate, QueryIntent, RetrievalPlan
from query_engine.understanding import understand_query

from conftest import FakeProvider, _write_json


def make_config(store: Path, **overrides) -> dict:
    config = {
        "model_name": "fake-model",
        "provider": "fake",
        "api_key": "fake",
        "knowledge_store_path": str(store),
        "top_k_concepts": 25,
        "top_k_evidence_pages": 5,
        "max_context_tokens": 6000,
        "relationship_depth": 1,
    }
    config.update(overrides)
    return config


def make_intent(**overrides) -> QueryIntent:
    intent = QueryIntent(
        intent="fact-lookup",
        keywords=["sample magic"],
        concepts=["sample magic"],
        filters={},
    )
    for key, value in overrides.items():
        setattr(intent, key, value)
    return intent


# ---------------------------------------------------------------------------
# Stage 1 — Scope Resolver
# ---------------------------------------------------------------------------
class TestResolveScope:
    def test_all_returns_every_document(self, knowledge_store):
        assert resolve_scope("all", str(knowledge_store)) == ["doc-a", "doc-b"]

    def test_list_restricts_scope(self, knowledge_store):
        assert resolve_scope(["doc-b"], str(knowledge_store)) == ["doc-b"]

    def test_unknown_document_raises(self, knowledge_store):
        with pytest.raises(ValueError, match="Unknown document"):
            resolve_scope(["doc-a", "nope"], str(knowledge_store))

    def test_empty_scope_raises(self, knowledge_store):
        with pytest.raises(ValueError):
            resolve_scope([], str(knowledge_store))

    def test_missing_registry_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            resolve_scope("all", str(tmp_path))


# ---------------------------------------------------------------------------
# Stage 2 — Query Understanding
# ---------------------------------------------------------------------------
class TestUnderstandQuery:
    def test_extracts_intent(self, knowledge_store, monkeypatch):
        from query_engine import understanding

        provider = FakeProvider()
        monkeypatch.setattr(understanding, "build_provider", lambda config: provider)
        intent = understand_query("What is sample magic?", make_config(knowledge_store))
        assert intent.intent == "fact-lookup"
        assert intent.keywords == ["sample magic"]
        assert intent.concepts == ["sample magic"]
        assert intent.filters == {}
        assert provider.complete_json_calls == 1

    def test_fallback_when_provider_fails(self, knowledge_store, monkeypatch):
        from query_engine import understanding

        provider = FakeProvider(fail=True)
        monkeypatch.setattr(understanding, "build_provider", lambda config: provider)
        intent = understand_query("What is sample magic?", make_config(knowledge_store))
        assert "sample" in intent.keywords and "magic" in intent.keywords

    def test_empty_query_raises(self, knowledge_store):
        with pytest.raises(ValueError):
            understand_query("   ", make_config(knowledge_store))


# ---------------------------------------------------------------------------
# Stage 3 — Retrieval Planner
# ---------------------------------------------------------------------------
class TestBuildRetrievalPlan:
    def test_deduplicates_and_defaults(self):
        intent = make_intent(keywords=["magic", "magic"], concepts=["m1", "m1"])
        plan = build_retrieval_plan(intent, ["doc-a"])
        assert plan.keywords == ["magic"]
        assert plan.concepts == ["m1"]
        assert plan.scope == ["doc-a"]
        assert plan.relationship_depth == 1

    def test_empty_scope_raises(self):
        with pytest.raises(ValueError):
            build_retrieval_plan(make_intent(), [])


# ---------------------------------------------------------------------------
# Stage 4 — Deterministic Retrieval
# ---------------------------------------------------------------------------
class TestRetrieveCandidates:
    def make_plan(self, scope, depth=1, **intent_overrides):
        intent = make_intent(**intent_overrides)
        plan = build_retrieval_plan(intent, scope)
        plan.relationship_depth = depth
        return plan

    def test_keyword_alias_and_graph_hits(self, knowledge_store):
        plan = self.make_plan(["doc-a", "doc-b"], keywords=["magic"], concepts=["sample sorcery"])
        candidates = retrieve_candidates(plan, str(knowledge_store))
        by_id = {(c.concept_id, c.document_id): c for c in candidates}

        # keyword "magic" hits doc-a + doc-b; alias "sample sorcery" hits sample-magic;
        # graph expansion from sample-magic reaches sample-energy and sample-potion.
        assert ("sample-magic", "doc-a") in by_id
        assert ("sample-potion", "doc-b") in by_id
        assert ("sample-energy", "doc-a") in by_id

        # Hydrated from concepts/, unranked and unscored.
        magic = by_id[("sample-magic", "doc-a")]
        assert magic.description == "Sample magic is the core concept of the sample world."
        assert magic.evidence_pages == [3]
        assert magic.score == 0.0
        assert magic.rank == 0

    def test_scope_restricts_candidates(self, knowledge_store):
        plan = self.make_plan(["doc-a"], keywords=["magic"], concepts=["sample sorcery"])
        candidates = retrieve_candidates(plan, str(knowledge_store))
        assert all(c.document_id == "doc-a" for c in candidates)
        assert ("sample-potion", "doc-b") not in {(c.concept_id, c.document_id) for c in candidates}

    def test_depth_zero_disables_graph_expansion(self, knowledge_store):
        plan = self.make_plan(["doc-a", "doc-b"], depth=0, keywords=["sample magic"], concepts=[])
        candidates = retrieve_candidates(plan, str(knowledge_store))
        ids = {c.concept_id for c in candidates}
        assert ids == {"sample-magic"}  # no graph neighbours pulled in

    def test_no_match_returns_empty(self, knowledge_store):
        plan = self.make_plan(["doc-a"], keywords=["zzzz"], concepts=[])
        assert retrieve_candidates(plan, str(knowledge_store)) == []


# ---------------------------------------------------------------------------
# Stage 5 — Candidate Ranking (BM25 + alias + graph, RRF fusion)
# ---------------------------------------------------------------------------
class TestRanking:
    def get_candidates(self, knowledge_store, **intent_overrides):
        intent = make_intent(**intent_overrides)
        plan = build_retrieval_plan(intent, ["doc-a", "doc-b"])
        candidates = retrieve_candidates(plan, str(knowledge_store))
        return intent, candidates

    def test_bm25_orders_by_term_relevance(self, knowledge_store):
        intent, candidates = self.get_candidates(knowledge_store, keywords=["magic"], concepts=[])
        ranked = bm25_ranking(candidates, intent, str(knowledge_store))
        assert ranked, "BM25 should rank at least one candidate"
        assert ranked[0].concept_id == "sample-magic"

    def test_alias_ranking_exact_match(self, knowledge_store):
        intent, candidates = self.get_candidates(knowledge_store, keywords=[], concepts=["sample sorcery"])
        ranked = alias_ranking(candidates, intent, str(knowledge_store))
        assert [c.concept_id for c in ranked] == ["sample-magic"]

    def test_graph_ranking_closer_is_better(self, knowledge_store):
        intent, candidates = self.get_candidates(knowledge_store, keywords=[], concepts=["sample magic"])
        ranked = graph_ranking(candidates, intent, str(knowledge_store), relationship_depth=1)
        assert ranked[0].concept_id == "sample-magic"  # distance 0 seed first
        assert {c.concept_id for c in ranked} == {"sample-magic", "sample-energy", "sample-potion"}

    def test_rrf_fusion_assigns_score_and_rank(self, knowledge_store):
        intent, candidates = self.get_candidates(knowledge_store)
        ranked = rank_candidates(candidates, intent, str(knowledge_store), relationship_depth=1)

        assert len(ranked) == len(candidates)
        assert [c.rank for c in ranked] == list(range(1, len(ranked) + 1))
        scores = [c.score for c in ranked]
        assert scores == sorted(scores, reverse=True)
        # sample-magic is strong in all three signals and must come first.
        assert ranked[0].concept_id == "sample-magic"
        # RRF scores live in (0, 3/(k+1)] for three signals.
        assert all(0.0 < c.score <= 3.0 / 61.0 + 1e-12 for c in ranked)

    def test_ranking_is_deterministic(self, knowledge_store):
        intent, candidates = self.get_candidates(knowledge_store)
        first = rank_candidates(list(candidates), intent, str(knowledge_store), 1)
        second = rank_candidates(list(candidates), intent, str(knowledge_store), 1)
        assert [(c.concept_id, c.rank) for c in first] == [(c.concept_id, c.rank) for c in second]

    def test_empty_candidates(self, knowledge_store):
        assert rank_candidates([], make_intent(), str(knowledge_store)) == []


# ---------------------------------------------------------------------------
# Stage 6 — Evidence Loader
# ---------------------------------------------------------------------------
class TestLoadEvidence:
    def make_candidate(self, concept_id, document_id, pages, rank):
        return Candidate(
            concept_id=concept_id,
            document_id=document_id,
            score=0.0,
            rank=rank,
            evidence_pages=pages,
            description="",
        )

    def test_top_n_bound_and_dedup(self, knowledge_store):
        candidates = [
            self.make_candidate("sample-magic", "doc-a", [3, 4], 1),
            self.make_candidate("sample-energy", "doc-a", [3, 5], 2),  # page 3 shared
            self.make_candidate("sample-potion", "doc-b", [2], 3),     # beyond top-2
        ]
        evidence = load_evidence(candidates, str(knowledge_store), top_k_evidence_pages=2)
        keys = [(e.document_id, e.page_number) for e in evidence]
        assert keys == [("doc-a", 3), ("doc-a", 4), ("doc-a", 5)]  # page 3 read once
        assert ("doc-b", 2) not in keys
        assert all(e.content for e in evidence)

    def test_missing_page_is_skipped(self, knowledge_store):
        candidates = [self.make_candidate("ghost", "doc-a", [99], 1)]
        assert load_evidence(candidates, str(knowledge_store), 1) == []

    def test_zero_top_k_reads_nothing(self, knowledge_store):
        candidates = [self.make_candidate("sample-magic", "doc-a", [3], 1)]
        assert load_evidence(candidates, str(knowledge_store), 0) == []


# ---------------------------------------------------------------------------
# Stage 7 — Context Builder (two-tier, hard ceiling)
# ---------------------------------------------------------------------------
class TestBuildContext:
    def test_two_tier_content(self, knowledge_store):
        candidates = [
            Candidate("sample-magic", "doc-a", 0.05, 1, [3], "Core concept."),
            Candidate("sample-energy", "doc-a", 0.04, 2, [4], "Powers magic."),
        ]
        evidence = load_evidence(candidates, str(knowledge_store), 1)
        context = build_context(candidates, evidence, 6000)
        assert "## Tier 1: Concept Descriptions" in context
        assert "## Tier 2: Evidence Pages" in context
        assert "Core concept." in context
        assert "Page three reveals sample magic in detail." in context

    def test_hard_ceiling_with_25_concepts_and_30_plus_pages(self, tmp_path):
        """Definition of Done #7: a 25-concept, 30+ page query stays within
        max_context_tokens — verified, not assumed."""
        store = tmp_path / "knowledge"
        candidates = []
        for i in range(25):
            concept_id = f"concept-{i:02d}"
            pages = [2 * i + 1, 2 * i + 2]  # 50 pages across the candidate list
            for page_number in pages:
                _write_json(
                    store / "doc-x" / "pages" / f"{page_number}.json",
                    {"page_number": page_number,
                     "content": f"Full text of page {page_number}. " * 100},  # ~2.9 KB each
                )
            candidates.append(
                Candidate(
                    concept_id=concept_id,
                    document_id="doc-x",
                    score=1.0 / (i + 1),
                    rank=i + 1,
                    evidence_pages=pages,
                    description=f"Curated description of {concept_id}. " * 3,
                )
            )

        evidence = load_evidence(candidates, str(store), top_k_evidence_pages=5)
        assert len(evidence) == 10  # top-5 candidates x 2 pages, not 50

        for ceiling in (6000, 1500, 250):
            context = build_context(candidates, evidence, ceiling)
            assert estimate_tokens(context) <= ceiling

        # Breadth is preserved where budget allows: all 25 descriptions appear.
        full = build_context(candidates, evidence, 6000)
        assert "concept-24" in full

    def test_ceiling_truncates_tier_one_too(self, knowledge_store):
        candidates = [
            Candidate(f"c{i}", "doc-a", 0.0, i + 1, [3], "x" * 400) for i in range(10)
        ]
        context = build_context(candidates, [], 200)
        assert estimate_tokens(context) <= 200

    def test_invalid_ceiling_raises(self):
        with pytest.raises(ValueError):
            build_context([], [], 0)


# ---------------------------------------------------------------------------
# Stage 9 — Citation Builder
# ---------------------------------------------------------------------------
class TestBuildCitations:
    def test_page_level_citations_with_provenance(self, knowledge_store):
        candidates = [
            Candidate("sample-magic", "doc-a", 0.05, 1, [3, 4], "d1"),
            Candidate("sample-energy", "doc-a", 0.04, 2, [3], "d2"),
        ]
        evidence = load_evidence(candidates, str(knowledge_store), 1)  # only rank-1 pages
        citations = build_citations(candidates, evidence)

        by_key = {(c["document_id"], c["page_number"]): c for c in citations}
        assert set(by_key) == {("doc-a", 3), ("doc-a", 4)}
        assert by_key[("doc-a", 3)]["concepts"] == ["sample-magic", "sample-energy"]
        assert by_key[("doc-a", 3)]["evidence_loaded"] is True
        assert by_key[("doc-a", 4)]["evidence_loaded"] is True  # rank-1 candidate's page
        assert by_key[("doc-a", 4)]["concepts"] == ["sample-magic"]


# ---------------------------------------------------------------------------
# Response assembly
# ---------------------------------------------------------------------------
class TestBuildResponse:
    def test_documents_and_concepts_used(self):
        candidates = [
            Candidate("b-concept", "doc-b", 0.05, 1, [1], "d"),
            Candidate("a-concept", "doc-a", 0.04, 2, [2], "d"),
        ]
        result = build_response("answer", [{"page_number": 1}], candidates)
        assert result.answer == "answer"
        assert result.citations == [{"page_number": 1}]
        assert result.documents_used == ["doc-a", "doc-b"]  # sorted
        assert result.concepts_used == ["b-concept", "a-concept"]  # rank order


# ---------------------------------------------------------------------------
# End-to-end — ask()
# ---------------------------------------------------------------------------
class TestAsk:
    def test_global_query(self, knowledge_store, fake_provider):
        result = ask("What is sample magic?", "all", make_config(knowledge_store))

        assert result.answer == "Grounded fake answer."
        assert result.documents_used == ["doc-a", "doc-b"]
        assert result.concepts_used[0] == "sample-magic"
        assert len(result.concepts_used) <= 25
        assert result.citations, "expected page-level citations"
        for citation in result.citations:
            assert {"document_id", "page_number", "concepts", "evidence_loaded"} <= set(citation)
        # LLM used exactly twice: understanding + generation.
        assert fake_provider.complete_json_calls == 1
        assert fake_provider.complete_calls == 1

    def test_scoped_query(self, knowledge_store, fake_provider):
        result = ask("What is sample magic?", ["doc-b"], make_config(knowledge_store))
        assert result.documents_used == ["doc-b"]
        assert all(c["document_id"] == "doc-b" for c in result.citations)

    def test_top_k_concepts_truncates(self, knowledge_store, fake_provider):
        result = ask(
            "What is sample magic?", "all",
            make_config(knowledge_store, top_k_concepts=1),
        )
        assert result.concepts_used == ["sample-magic"]

    def test_no_results_short_circuits_generation(self, knowledge_store, monkeypatch):
        from query_engine import generator, understanding

        provider = FakeProvider(
            intent_data={"intent": "fact-lookup", "keywords": ["zzzz"], "concepts": [], "filters": {}}
        )
        monkeypatch.setattr(understanding, "build_provider", lambda config: provider)
        monkeypatch.setattr(generator, "build_provider", lambda config: provider)

        result = ask("Anything?", "all", make_config(knowledge_store))
        assert result.answer == _NO_RESULTS_ANSWER
        assert result.citations == []
        assert result.documents_used == []
        assert result.concepts_used == []
        assert provider.complete_calls == 0  # no wasted generation call

    def test_unknown_scope_raises(self, knowledge_store, fake_provider):
        with pytest.raises(ValueError, match="Unknown document"):
            ask("Anything?", ["missing-doc"], make_config(knowledge_store))

    def test_writes_usage_log(self, knowledge_store, fake_provider, tmp_path):
        result = ask(
            "What is sample magic?",
            "all",
            make_config(
                knowledge_store,
                usage_dir=str(tmp_path),
                usage_document_name="sample_query",
            ),
        )

        assert result.answer == "Grounded fake answer."
        log_path = tmp_path / "Usage_sample_query.log"
        assert log_path.exists(), "Usage log was not written"

        text = log_path.read_text(encoding="utf-8")
        assert "Total LLM Calls: 2" in text
        # FakeProvider returns 11 input + 7 output per call; 2 calls = 22/14/36
        assert "Total Input Tokens: 22" in text
        assert "Total Output Tokens: 14" in text
        assert "Total Tokens: 36" in text

    def test_no_results_writes_usage_log_with_one_call(
        self, knowledge_store, monkeypatch, tmp_path
    ):
        from query_engine import generator, understanding

        provider = FakeProvider(
            intent_data={"intent": "fact-lookup", "keywords": ["zzzz"], "concepts": [], "filters": {}}
        )
        monkeypatch.setattr(understanding, "build_provider", lambda config: provider)
        monkeypatch.setattr(generator, "build_provider", lambda config: provider)

        result = ask(
            "Anything?",
            "all",
            make_config(
                knowledge_store,
                usage_dir=str(tmp_path),
                usage_document_name="no_results",
            ),
        )
        assert result.answer == _NO_RESULTS_ANSWER
        assert provider.complete_calls == 0  # generation stage never reached

        log_path = tmp_path / "Usage_no_results.log"
        assert log_path.exists(), "Usage log was not written for no-results path"
        text = log_path.read_text(encoding="utf-8")
        assert "Total LLM Calls: 1" in text
