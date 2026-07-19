"""Simple HTTP server for the Knowledge Store UI.

Run from the project root:
    python UI/server.py

Then open http://localhost:8000 in a browser.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

DEFAULT_PORT = 8000
# Configuration ----------------------------------------------------------------
ROOT = Path(__file__).resolve().parent  # UI/
PROJECT_ROOT = ROOT.parent               # repository root
KNOWLEDGE_STORE = PROJECT_ROOT / "knowledge_store"
STATIC_DIR = ROOT

QUERY_ROOT = PROJECT_ROOT / "libs" / "Query_Pipeline"
if str(QUERY_ROOT) not in sys.path:
    sys.path.insert(0, str(QUERY_ROOT))

from query_engine import ask  # noqa: E402


def _build_query_config():
    """Build the query-engine config from environment variables."""
    api_key = os.environ.get("MOONSHOT_API_KEY")
    if not api_key:
        raise RuntimeError(
            "MOONSHOT_API_KEY is not set. Export it before starting the server."
        )
    extra_body = os.environ.get("OKF_EXTRA_BODY", '{"thinking": {"type": "disabled"}}')
    try:
        extra_body = json.loads(extra_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OKF_EXTRA_BODY is not valid JSON: {exc}")
    return {
        "model_name": os.environ.get("OKF_MODEL", "moonshot/kimi-k2.6"),
        "provider": os.environ.get("OKF_PROVIDER", "moonshot"),
        "api_key": api_key,
        "base_url": os.environ.get("OKF_BASE_URL", "https://api.moonshot.ai/v1"),
        "extra_body": extra_body,
        "knowledge_store_path": str(PROJECT_ROOT / "knowledge_store"),
        "top_k_concepts": int(os.environ.get("OKF_TOP_K_CONCEPTS", "5")),
        "top_k_evidence_pages": int(os.environ.get("OKF_TOP_K_EVIDENCE_PAGES", "2")),
        "max_context_tokens": int(os.environ.get("OKF_MAX_CONTEXT_TOKENS", "50000")),
        "relationship_depth": int(os.environ.get("OKF_RELATIONSHIP_DEPTH", "1")),
    }


QUERY_CONFIG = _build_query_config()

# Helpers ----------------------------------------------------------------------
def json_response(handler, data, status=200):
    """Send a JSON response with CORS headers."""
    body = json.dumps(data, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def error_response(handler, message, status=404):
    json_response(handler, {"error": message}, status=status)


def list_bundles():
    """Return all knowledge bundles (directories under knowledge_store/ that are not registry)."""
    bundles = []
    if not KNOWLEDGE_STORE.exists():
        return bundles
    for entry in sorted(KNOWLEDGE_STORE.iterdir()):
        if not entry.is_dir() or entry.name == "registry":
            continue
        doc_file = entry / "document.json"
        title = entry.name
        if doc_file.exists():
            try:
                doc = json.loads(doc_file.read_text(encoding="utf-8"))
                title = doc.get("title") or doc.get("id") or entry.name
            except json.JSONDecodeError:
                pass
        bundles.append({"id": entry.name, "title": title, "path": str(entry)})
    return bundles


def read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def build_merged_graph():
    """Merge concepts and relationship graphs from every bundle into one graph.

    Each node is tagged with the source document id/title so the client can
    color nodes per document. Concept ids are assumed globally unique across
    documents (verified for the current knowledge store); on a collision the
    first occurrence wins.
    """
    concepts = []
    nodes = []
    edges = []
    documents = []
    seen_concepts = set()
    seen_nodes = set()

    if not KNOWLEDGE_STORE.exists():
        return {"documents": documents, "concepts": concepts, "nodes": nodes, "edges": edges}

    for entry in sorted(KNOWLEDGE_STORE.iterdir()):
        if not entry.is_dir() or entry.name == "registry":
            continue
        doc_id = entry.name
        title = doc_id
        doc_meta = read_json(entry / "document.json")
        if doc_meta:
            title = doc_meta.get("title") or doc_meta.get("id") or doc_id

        bundle_nodes = 0
        graph = read_json(entry / "relationship_graph.json")
        if graph:
            for node_id in graph.get("nodes", []):
                if node_id in seen_nodes:
                    continue
                seen_nodes.add(node_id)
                nodes.append({"id": node_id, "doc": doc_id})
                bundle_nodes += 1
            for edge in graph.get("edges", []):
                edges.append(
                    {
                        "source": edge.get("source"),
                        "target": edge.get("target"),
                        "type": edge.get("type"),
                        "page_numbers": edge.get("page_numbers", []),
                        "doc": doc_id,
                    }
                )

        concepts_dir = entry / "concepts"
        if concepts_dir.exists():
            for concept_file in sorted(concepts_dir.glob("*.json")):
                data = read_json(concept_file)
                if not data:
                    continue
                cid = data.get("id")
                if cid in seen_concepts:
                    continue
                seen_concepts.add(cid)
                data["doc"] = doc_id
                concepts.append(data)

        documents.append({"id": doc_id, "title": title, "nodes": bundle_nodes})

    return {"documents": documents, "concepts": concepts, "nodes": nodes, "edges": edges}


# Request handler --------------------------------------------------------------
class UIRequestHandler(SimpleHTTPRequestHandler):
    """Serves static UI files and JSON API endpoints."""

    def translate_path(self, path):
        """Serve files from UI/ directory instead of cwd."""
        parsed = urlparse(path)
        clean_path = unquote(parsed.path)
        if clean_path.startswith("/"):
            clean_path = clean_path[1:]
        return str(STATIC_DIR / clean_path)

    def log_message(self, fmt, *args):
        """Suppress request logging."""
        pass

    def _read_json_body(self):
        content_length = self.headers.get("Content-Length")
        if not content_length:
            return None, "Missing Content-Length"
        try:
            length = int(content_length)
            body = self.rfile.read(length).decode("utf-8")
            return json.loads(body), None
        except (ValueError, json.JSONDecodeError) as exc:
            return None, f"Invalid JSON body: {exc}"

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        parts = [p for p in path.split("/") if p]

        if len(parts) >= 2 and parts[0] == "api" and parts[1] == "ask":
            payload, error = self._read_json_body()
            if error:
                return error_response(self, error, 400)
            if not isinstance(payload, dict):
                return error_response(self, "Expected JSON object", 400)

            query = (payload.get("query") or "").strip()
            if not query:
                return error_response(self, "query is required", 400)

            scope = payload.get("scope", "all")
            if scope != "all" and not isinstance(scope, list):
                return error_response(self, "scope must be 'all' or a list", 400)

            try:
                result = ask(query, scope, QUERY_CONFIG)
                return json_response(self, asdict(result))
            except RuntimeError as exc:
                return error_response(self, str(exc), 500)
            except Exception as exc:
                return error_response(self, f"Query failed: {exc}", 500)

        return error_response(self, "Not found", 404)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        # Static files and root
        if path == "/" or not path.startswith("/api/"):
            if path == "/":
                self.path = "/index.html"
            return super().do_GET()

        # API routes
        parts = [p for p in path.split("/") if p]
        # parts = ['api', ...]
        if len(parts) < 2:
            return error_response(self, "Invalid API path", 400)

        resource = parts[1]

        if resource == "bundles" and len(parts) == 2:
            return json_response(self, {"bundles": list_bundles()})

        if resource == "registry" and len(parts) == 2:
            stats = read_json(KNOWLEDGE_STORE / "registry" / "statistics.json")
            if stats is None:
                return error_response(self, "Registry statistics not found", 404)
            return json_response(self, stats)

        # /api/graph/all  -> merged concepts + graph across every bundle
        if resource == "graph" and len(parts) == 3 and parts[2] == "all":
            return json_response(self, build_merged_graph())

        if resource == "bundle" and len(parts) >= 3:
            bundle_id = parts[2]
            bundle_dir = KNOWLEDGE_STORE / bundle_id
            if not bundle_dir.is_dir():
                return error_response(self, f"Bundle '{bundle_id}' not found", 404)

            # /api/bundle/<id>
            if len(parts) == 3:
                document = read_json(bundle_dir / "document.json")
                metadata = read_json(bundle_dir / "metadata.json")
                if document is None:
                    return error_response(self, "document.json missing", 404)
                return json_response(self, {"document": document, "metadata": metadata or {}})

            sub = parts[3]

            # /api/bundle/<id>/concepts
            if sub == "concepts" and len(parts) == 4:
                concepts_dir = bundle_dir / "concepts"
                concepts = []
                if concepts_dir.exists():
                    for concept_file in sorted(concepts_dir.glob("*.json")):
                        data = read_json(concept_file)
                        if data:
                            concepts.append(data)
                return json_response(self, {"concepts": concepts})

            # /api/bundle/<id>/concept/<concept_id>
            if sub == "concept" and len(parts) == 5:
                concept_id = parts[4]
                concept = read_json(bundle_dir / "concepts" / f"{concept_id}.json")
                if concept is None:
                    return error_response(self, f"Concept '{concept_id}' not found", 404)
                return json_response(self, concept)

            # /api/bundle/<id>/graph
            if sub == "graph" and len(parts) == 4:
                graph = read_json(bundle_dir / "relationship_graph.json")
                if graph is None:
                    return error_response(self, "relationship_graph.json not found", 404)
                return json_response(self, graph)

            # /api/bundle/<id>/indexes
            if sub == "indexes" and len(parts) == 4:
                indexes_dir = bundle_dir / "indexes"
                indexes = {}
                if indexes_dir.exists():
                    for index_file in sorted(indexes_dir.glob("*.json")):
                        data = read_json(index_file)
                        if data is not None:
                            indexes[index_file.stem] = data
                return json_response(self, {"indexes": indexes})

            # /api/bundle/<id>/page/<num>
            if sub == "page" and len(parts) == 5:
                page_num = parts[4]
                page = read_json(bundle_dir / "pages" / f"{page_num}.json")
                if page is None:
                    return error_response(self, f"Page '{page_num}' not found", 404)
                return json_response(self, page)

        return error_response(self, "Not found", 404)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


# Entry point ------------------------------------------------------------------
def main():
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    server = ThreadingHTTPServer(("0.0.0.0", port), UIRequestHandler)
    print(f"Knowledge Store UI server running at http://localhost:{port}")
    print(f"Serving static files from: {STATIC_DIR}")
    print(f"Knowledge store path: {KNOWLEDGE_STORE}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
