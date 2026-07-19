# Query Pipeline

Answer natural-language questions over **Open Knowledge Format (OKF)** bundles using deterministic, explainable retrieval — no embeddings, no vector database.

This package is the third stage of the OKF_RAG pipeline. It consumes bundles produced by the [Knowledge Builder](../Knowledge_Builder/README.md) and returns grounded answers with page-level citations.

## Features

- Deterministic retrieval via keyword, alias, concept, and relationship indexes
- BM25 + alias + graph ranking fused with Reciprocal Rank Fusion (RRF)
- Two-tier, token-budgeted context building
- Grounded answer generation with explicit page-level citations
- Provider-agnostic LLM layer via LiteLLM
- No-results short-circuit with a deterministic fallback message

## Installation

The Query Pipeline has no `pyproject.toml`; add `libs/Query_Pipeline` to `PYTHONPATH` or install its runtime dependency directly:

```bash
pip install "litellm>=1.40.0,<1.92.0"
```

When running scripts from the repository root, add the package to `sys.path`:

```python
import sys
sys.path.append("libs/Query_Pipeline")

from query_engine import ask
```

## Usage

```python
import os
import sys

sys.path.append("libs/Query_Pipeline")

from query_engine import ask

config = {
    "model_name": "moonshot/kimi-k2.6",
    "provider": "moonshot",
    "api_key": os.environ["MOONSHOT_API_KEY"],
    "base_url": "https://api.moonshot.ai/v1",
    "extra_body": {"thinking": {"type": "disabled"}},
    "knowledge_store_path": "./knowledge_store",
    "top_k_concepts": 5,
    "top_k_evidence_pages": 2,
    "max_context_tokens": 50000,
    "relationship_depth": 1,
}

result = ask("who was Dumbledore?", "all", config)
print(result.answer)
print(result.citations)
print(result.documents_used)
print(result.concepts_used)
```

`scope` can be `"all"` to search every bundle, or a list of document names/IDs to restrict the search.

## Pipeline Stages

`ask()` wires the stages in this order:

1. `resolve_scope` — resolve `"all"` or a list of document names
2. `understand_query` — LLM-based intent extraction with deterministic fallback
3. `build_retrieval_plan` — derive retrieval strategy
4. `retrieve_candidates` — deterministic lookup via keyword/alias/graph indexes
5. `rank_candidates` — BM25 + alias + graph ranking fused with RRF
6. `load_evidence` — load top-N relevant raw pages per candidate
7. `build_context` — two-tier context with a hard token ceiling
8. `generate_answer` — grounded answer synthesis (LLM)
9. `build_citations` — page-level citations with provenance

## Deterministic Retrieval

The engine does not use embeddings or vector search. It queries:

- `knowledge_store/registry/keywords.json`
- `knowledge_store/registry/aliases.json`
- `knowledge_store/registry/concepts.json`
- `knowledge_store/registry/relationships.json`
- `knowledge_store/registry/global_graph.json`
- Per-bundle indexes under `knowledge_store/<document-id>/indexes/`

Candidates are scored and fused with RRF to produce a final ranked list.

## Configuration

Key config keys recognized by `ask()`:

| Key | Default | Description |
|-----|---------|-------------|
| `knowledge_store_path` | `"./knowledge"` | Root of the OKF knowledge store |
| `top_k_concepts` | `25` | Number of top-ranked concepts to keep |
| `top_k_evidence_pages` | `5` | Relevant pages loaded per candidate |
| `max_context_tokens` | `6000` | Hard token ceiling for the LLM context |
| `relationship_depth` | `1` | Graph hops when planning retrieval |
| `model_name` | — | LLM model identifier (e.g. `moonshot/kimi-k2.6`) |
| `provider` | — | LLM provider |
| `api_key` | — | API key |
| `base_url` | `None` | Optional proxy/self-hosted endpoint |
| `extra_body` | `{}` | Provider-specific extra body params |

## Result Object

```python
@dataclass
class QueryResult:
    answer: str
    citations: list
    documents_used: list[str]
    concepts_used: list[str]
```

## Testing

```bash
cd libs/Query_Pipeline
pytest tests
```

## License

MIT
