# Knowledge Builder

Build portable, self-contained **Open Knowledge Format (OKF)** bundles from parsed documents.

This package is the second stage of the OKF_RAG pipeline. It takes already-parsed documents (Markdown, Text, or JSON) produced by the [Universal Document Parser](../README.md) and turns them into deterministic, embedding-free knowledge stores that the [Query Pipeline](../Query_Pipeline/README.md) can answer questions over.

## Features

- Provider-agnostic LLM layer powered by **LiteLLM**
- Async execution with bounded concurrency (`num_sub_agents`)
- Exponential-backoff retry logic and structured JSON extraction
- Self-contained document bundles under `knowledge_store/<document-id>/`
- Global registry for cross-document discovery
- Deterministic, embedding-free retrieval indexes
- Vision-model support for image-based pages

## Installation

```bash
cd libs/Knowledge_Builder
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
```

## Usage

The public API is exactly one function: `build_kb`.

```python
import os
from knowledge_builder import build_kb

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

result = build_kb("ParsedOutput/Astrophysics_for_People_In_Hurry.md", config)
print(result)
```

## Bundle Output

Each document produces a bundle at `knowledge_store/<document-id>/`:

```text
<document-id>/
├── document.json
├── metadata.json
├── relationship_graph.json
├── validation_report.json
├── concepts/
├── indexes/
├── pages/
├── documents/
└── assets/           # copied image-page assets
```

The global registry is updated under `knowledge_store/registry/`.

## Vision Pages

Pages whose content is an image file path are sent to a vision-capable model as base64 image URLs. `build_kb` checks LiteLLM vision support and raises `KnowledgeBuilderError` if a non-vision model is configured for an image-bearing document.

## Testing

```bash
cd libs/Knowledge_Builder
pytest tests
```

## License

MIT
