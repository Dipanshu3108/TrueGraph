# Agent Guide — Knowledge_Base

This document is written for AI coding agents that need to work on the project without prior context. It describes the architecture, technology stack, build/test commands, conventions, and security considerations found in the repository as of the latest inspection.

## Project Overview

Knowledge_Base is an end-to-end, deterministic Retrieval-Augmented Generation (RAG) pipeline built around the **Open Knowledge Format (OKF)**. It converts raw documents into self-contained, embedding-free knowledge bundles and answers questions over them using deterministic indexes, concept graphs, and page-level evidence.

The pipeline has four stages:

1. **Parse** — `UniversalDocumentParser` converts PDF, DOCX, PPTX, PPT, and Markdown into Markdown/Text/JSON.
2. **Build knowledge** — `knowledge_builder.build_kb()` extracts concepts, relationships, keywords, aliases, and indexes into an OKF bundle.
3. **Store** — bundles live under `knowledge_store/` plus a global `knowledge_store/registry/` for cross-document lookup.
4. **Query** — `query_engine.ask()` answers natural-language questions using deterministic retrieval and grounded generation.

A browser-based UI (`UI/`) lets users explore bundles, concept graphs, pages, indexes, and ask questions.

## Technology Stack

- **Language**: Python 3.9+ (development notebooks and scripts use Python 3.13).
- **Virtual environment**: `.venv/` at the repository root (ignored by Git).
- **LLM orchestration**: [LiteLLM](https://docs.litellm.ai/) (`litellm>=1.40.0,<1.92.0`) for provider-agnostic chat completions.
- **Document parsing**: PyMuPDF, pdfplumber, pdfminer.six, python-docx, python-pptx, mammoth, Pillow, pytesseract, BeautifulSoup4, lxml, markdown.
- **Web UI**: Plain HTML/CSS/JS frontend, `http.server`-based Python backend, Vite for optional frontend dev server, graph libraries `3d-force-graph`, `force-graph`, `d3-force-3d`.
- **Testing**: `pytest`, `pytest-cov`, `pytest-asyncio` (for Knowledge Builder tests).
- **Type checking / formatting**: `black` (line length 100), `mypy`.

## Repository Layout

```text
.
├── input/                         # Raw source documents (PDFs)
├── ParsedOutput/                  # Parser output (Markdown, JSON, TXT)
├── knowledge_store/               # Generated OKF bundles + global registry
│   ├── <document-slug>/           # Per-document bundle
│   │   ├── document.json
│   │   ├── metadata.json
│   │   ├── relationship_graph.json
│   │   ├── validation_report.json
│   │   ├── concepts/
│   │   ├── indexes/
│   │   ├── pages/
│   │   ├── documents/
│   │   └── assets/                # Copied image-page assets
│   └── registry/                  # Cross-document indexes and stats
├── libs/                          # Three Python packages
│   ├── UDP/                       # universal_document_parser
│   │   ├── pyproject.toml
│   │   └── universal_document_parser/
│   ├── Knowledge_Builder/         # knowledge_builder
│   │   ├── pyproject.toml
│   │   └── knowledge_builder/
│   └── Query_Pipeline/            # query_engine
│       └── query_engine/
├── UI/                            # Knowledge Store Explorer frontend/backend
│   ├── server.py                  # Python HTTP server + API
│   ├── index.html, app.js, graph.js, styles.css
│   ├── package.json, vite.config.js
│   └── node_modules/              # Graph libraries
├── master_pipeline.ipynb          # Jupyter example for parser usage
├── k_builder_test.py              # Ad-hoc Knowledge Builder invocation
├── query_test.py                  # Ad-hoc query invocation
└── Local_personal_observation/    # Debug stage dumps from query pipeline
```

### Package Details

#### `libs/UDP` — Universal Document Parser

- **Build config**: `libs/UDP/pyproject.toml` (note: the file is physically at `libs/pyproject.toml` and declares package `universal_document_parser`).
- **Public API**: `UniversalDocumentParser.parse(path, metadata=[], output_format="markdown", input_format="default")`.
- **Supported input extensions**: `.pdf`, `.docx`, `.pptx`, `.ppt`, `.md`, `.markdown`.
- **Supported output formats**: `markdown`, `text`, `json`.
- **Special modes**:
  - `input_format="image"` renders PDF pages to images and stores them under `image_storage/`.
  - `.ppt` is converted to `.pptx` via LibreOffice when `enable_ppt_conversion=True`.
- **CLI**: `universal-document-parser parse <path> [--output-format ...] [--output ...] [--metadata ...] [--input-format image] [--verbose]`.
- **Modules**:
  - `parser.py` — main dispatch and orchestration.
  - `parsers/` — format-specific extractors (`pdf_parser.py`, `docx_parser.py`, `pptx_parser.py`, `markdown_parser.py`).
  - `cleanup/text_cleanup.py` — unicode normalization, whitespace, header/footer removal, paragraph merging.
  - `formatters/` — markdown, text, JSON output formatters.
  - `config.py` — default thresholds and parser priorities.

#### `libs/Knowledge_Builder` — Knowledge Builder

- **Build config**: `libs/Knowledge_Builder/pyproject.toml`, package name `knowledge-builder`.
- **Public API**: `from knowledge_builder import build_kb; build_kb(file_path, config)`.
- **Pipeline stages** (`entry.py`):
  1. `load_pages` — load Markdown or JSON parser output, classify text vs. image pages.
  2. `filter_empty_pages` — drop blank text pages and missing image files.
  3. `make_batches` — group pages into text/image batches (never mixed).
  4. `run_batches` — async concurrent extraction via LiteLLM.
  5. `validate_extractions` — schema/quality validation.
  6. `merge_document` — de-duplicate concepts, merge aliases/keywords/page numbers.
  7. `build_relationships` — document-local concept graph.
  8. `write_concepts` / `build_indexes` — OKF artifacts.
  9. `write_bundle` — assemble self-contained bundle directory.
  10. `update_registry` — merge into global registry.
- **LLM provider**: `knowledge_builder.providers.litellm_provider.LiteLLMProvider` with exponential-backoff retries, JSON parsing, and provider-error classification.
- **Image-page support**: pages whose content is an image file path are sent to a vision-capable model as base64 image URLs. `build_kb` checks vision support and rejects non-vision models for image documents.

#### `libs/Query_Pipeline` — Query Engine

- **No build config** — import directly by adding `libs/Query_Pipeline` to `sys.path`.
- **Public API**: `from query_engine import ask; ask(query, scope, config)`.
- **Pipeline stages** (`entry.py`):
  1. `resolve_scope` — resolve `"all"` or a list of document names.
  2. `understand_query` — LLM-based intent extraction with deterministic fallback.
  3. `build_retrieval_plan` — derive retrieval strategy.
  4. `retrieve_candidates` — deterministic lookup via keyword/alias/graph indexes.
  5. `rank_candidates` — BM25 + alias + graph ranking fused with RRF.
  6. `load_evidence` — load top-N relevant raw pages per candidate.
  7. `build_context` — two-tier context with a hard token ceiling.
  8. `generate_answer` — grounded answer synthesis (LLM).
  9. `build_citations` — page-level citations with provenance.
- **Deterministic retrieval**: no embeddings, no vector DB. Uses `knowledge_store/registry/{keywords,aliases,concepts,relationships,global_graph}.json` and per-bundle indexes.
- **LLM reuse**: imports `LiteLLMProvider` from `Knowledge_Builder` via `query_engine.llm` with a sync bridge for use in synchronous stages.

#### `UI/` — Knowledge Store Explorer

- **Backend**: `UI/server.py` runs a `ThreadingHTTPServer` on `PORT` (default 8000).
- **Frontend**: static HTML/JS/CSS; graph rendered with `3d-force-graph` / `force-graph`.
- **API endpoints**:
  - `GET /api/bundles`
  - `GET /api/registry`
  - `GET /api/graph/all`
  - `GET /api/bundle/<id>`
  - `GET /api/bundle/<id>/concepts`
  - `GET /api/bundle/<id>/concept/<concept_id>`
  - `GET /api/bundle/<id>/graph`
  - `GET /api/bundle/<id>/indexes`
  - `GET /api/bundle/<id>/page/<num>`
  - `POST /api/ask` — calls `query_engine.ask()`.
- **Server environment variables**: `MOONSHOT_API_KEY` is required; `OKF_MODEL`, `OKF_PROVIDER`, `OKF_BASE_URL`, `OKF_EXTRA_BODY`, `OKF_TOP_K_CONCEPTS`, `OKF_TOP_K_EVIDENCE_PAGES`, `OKF_MAX_CONTEXT_TOKENS`, `OKF_RELATIONSHIP_DEPTH`.

## Build and Installation

Each Python package can be installed in editable mode independently.

```bash
# Universal Document Parser
cd libs
pip install -e .
# or with dev tools
pip install -e ".[dev]"

# Knowledge Builder
cd libs/Knowledge_Builder
pip install -e .
# or with dev tools
pip install -e ".[dev]"
```

The Query Pipeline has no `pyproject.toml`; add `libs/Query_Pipeline` to `PYTHONPATH` or install its runtime dependency directly:

```bash
pip install "litellm>=1.40.0,<1.92.0"
```

For the UI graph libraries:

```bash
cd UI
npm install
```

### System Dependencies

- **Tesseract OCR** — optional; only for scanned PDF fallback in UDP.
- **LibreOffice** — optional; only for `.ppt` to `.pptx` conversion.

## Running the Project

### Parse a document

```python
from libs.UDP.universal_document_parser import UniversalDocumentParser as UDP
parser = UDP(verbose=True)
result = parser.parse("input/doc.pdf", output_format="markdown")
```

### Build a knowledge bundle

```python
from libs.Knowledge_Builder.knowledge_builder import build_kb

config = {
    "model_name": "moonshot/kimi-k2.6",
    "provider": "moonshot",
    "api_key": os.environ["MOONSHOT_API_KEY"],
    "base_url": "https://api.moonshot.ai/v1",
    "knowledge_store_path": "./knowledge_store",
    "num_sub_agents": 5,
    "page_batch": 2,
    "image_page_batch": 2,
    "extra_body": {"thinking": {"type": "disabled"}},
}
result = build_kb("ParsedOutput/doc.md", config)
```

### Query the knowledge store

```python
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
```

### Start the UI

```bash
# From repository root; requires MOONSHOT_API_KEY exported
python UI/server.py
```

Open http://localhost:8000.

For Vite frontend-only development:

```bash
cd UI
npm run dev
```

## Testing

Run tests from inside each package directory so imports resolve correctly.

```bash
# UDP
cd libs
pytest universal_document_parser/tests

# Knowledge Builder
cd libs/Knowledge_Builder
pytest tests

# Query Pipeline
cd libs/Query_Pipeline
pytest tests
```

- UDP tests use `unittest` style mixed with `pytest` discovery.
- Knowledge Builder and Query Pipeline tests use `pytest` with fixtures; Knowledge Builder tests are async-enabled (`asyncio_mode = "auto"`).
- Query Pipeline tests rely on `conftest.py` to build an in-memory OKF knowledge store and a `FakeProvider`.

## Code Style and Conventions

- **Formatter**: `black`, line length 100 for both packages.
- **Type checker**: `mypy` (configured in each `pyproject.toml`).
- **Imports**: prefer explicit local imports; both packages add themselves to `sys.path` in test/example scripts when needed.
- **Data passing**: stages communicate through explicit dataclasses (`knowledge_builder.types`, `query_engine.types`).
- **Logging**: each module uses `logging.getLogger(__name__)`; UDP centralizes logging in `logger.py`.
- **Error handling**: domain exceptions live in `exceptions.py` (`KnowledgeBuilderError`, `ProviderError`, etc.).
- **Async**: Knowledge Builder uses `asyncio` for concurrent LLM calls; Query Pipeline wraps the async provider in `query_engine.llm.run_sync()`.
- **Hard-coded debug paths**: the Query Pipeline writes stage outputs to `D:\PROJECTS\Knowledge_Base\Local_personal_observation` when that directory exists.

## Security Considerations

- **API keys in source files**: `k_builder_test.py`, `query_test.py`, and `master_pipeline.ipynb` contain plaintext API keys. Do not commit these files; rotate any exposed keys. Prefer environment variables (`MOONSHOT_API_KEY`) as `UI/server.py` does.
- **`.env`**: a `.env` file exists at the repository root but is not read by any inspected code path. It is ignored by Git; treat it as sensitive.
- **CORS**: `UI/server.py` sends `Access-Control-Allow-Origin: *` on all responses. This is convenient for local development but should be restricted before any production deployment.
- **No authentication**: the UI server and query API have no auth; run only in trusted local environments.
- **Input paths**: ensure parser input paths come from trusted sources; the code reads files and executes LibreOffice for `.ppt` conversion.

## Deployment Notes

There is no containerization, CI/CD, or production deployment config in the repository. The project is currently designed for local execution:

- Install packages in editable mode.
- Export `MOONSHOT_API_KEY`.
- Run `python UI/server.py`.

If deploying publicly, add authentication, restrict CORS, move secrets to a proper secret manager, and run behind a reverse proxy.

## Common Pitfalls

- **Import paths**: `query_engine` and `knowledge_builder` are separate package trees under `libs/`. When running scripts from the repository root, add the relevant `libs/<Package>` directory to `sys.path` or install the package in editable mode.
- **Vision model requirement**: building knowledge from documents with image pages requires a vision-capable model. `build_kb` raises `KnowledgeBuilderError` otherwise.
- **Bundle slug collisions**: `build_kb` derives the document ID by slugifying the file stem. Duplicate names overwrite existing bundles and registry entries.
- **No results short-circuit**: `ask()` returns a deterministic no-results message and skips answer generation when retrieval is empty.
- **UI graph libraries**: the frontend expects libraries in `UI/node_modules/`. Run `npm install` in `UI/` before using the graph view, even though `server.py` itself has no npm dependency.
