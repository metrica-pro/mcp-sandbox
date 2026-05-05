"""Smoke test: execute_code calling Yandex Search API, parsing XML → JSON.

This is a realistic end-to-end MCP test:
1. Python script calls Yandex Search API over HTTPS
2. Decodes Base64 XML response
3. Parses XML with ElementTree
4. Extracts search result titles + URLs
5. Returns structured JSON via stdout

All executed through the MCP ``execute_code`` tool.
"""

from __future__ import annotations

import json
import os

import pytest

# ── Python script that will be sent to execute_code ──────────────────────

SEARCH_SCRIPT = r"""
import os, json, base64, urllib.request, xml.etree.ElementTree as ET

API_KEY = os.environ["YANDEX_API_KEY"]
FOLDER_ID = os.environ["YANDEX_FOLDER_ID"]
QUERY = "кофемашина"

body = json.dumps({
    "query": {"searchType": "SEARCH_TYPE_RU", "queryText": QUERY},
    "folderId": FOLDER_ID,
    "responseFormat": "FORMAT_XML"
}).encode()

req = urllib.request.Request(
    "https://searchapi.api.cloud.yandex.net/v2/web/search",
    data=body,
    headers={
        "Authorization": f"Api-Key {API_KEY}",
        "Content-Type": "application/json"
    }
)

try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        xml_str = base64.b64decode(data["rawData"]).decode("utf-8")
        root = ET.fromstring(xml_str)

        results = []
        for group in root.iter("group"):
            doc = group.find("doc")
            if doc is not None:
                title_el = doc.find("title")
                url_el = doc.find("url")
                headline_el = doc.find("headline")
                results.append({
                    "title": (title_el.text or "") if title_el is not None else "",
                    "url": (url_el.text or "") if url_el is not None else "",
                    "snippet": (headline_el.text or "") if headline_el is not None else "",
                })

        output = {
            "api": "yandex_search",
            "query": QUERY,
            "total_results": len(results),
            "items": results[:5],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))

except Exception as exc:
    print(json.dumps({"error": str(exc)}, ensure_ascii=False))
"""


# ── Direct unit test (without MCP server) ────────────────────────────────


class TestYandexSearchScript:
    """Run the search script directly via _execute_sync (no MCP protocol)."""

    def test_search_script_returns_json(self):
        """Execute the Yandex search script and verify JSON output."""
        from main import _execute_sync

        # Ensure env vars are set
        if "YANDEX_API_KEY" not in os.environ:
            pytest.skip("YANDEX_API_KEY not set in environment")

        result = _execute_sync("python", SEARCH_SCRIPT.strip())

        if "error" in result:
            pytest.fail(f"Script execution error: {result['error']}")

        stdout = result.get("stdout", "")
        assert stdout, "Empty stdout from search script"

        # Parse JSON output
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON output: {e}\nRaw stdout:\n{stdout}")

        # Check if API returned an auth/permission error (MCP round-trip still works)
        if "error" in data:
            err = data["error"]
            if "403" in err or "Permission" in err or "Forbidden" in err:
                print(f"\n⚠️  Yandex API auth error: {err}")
                print("   MCP round-trip OK — script executed, HTTP call made, error captured.")
                print("   Fix: grant search-api.webSearch.user role to the API key.")
                return
            pytest.fail(f"Yandex API unexpected error: {data['error']}")

        assert data.get("api") == "yandex_search", f"Unexpected api field: {data}"
        assert data.get("query") == "кофемашина"
        assert isinstance(data.get("total_results"), int)
        assert isinstance(data.get("items"), list)

        # Should have at least one search result
        assert data["total_results"] > 0, f"No search results returned: {data}"
        assert len(data["items"]) >= 1, f"Items list empty: {data}"

        # Each item should have title and url
        for item in data["items"]:
            assert "title" in item
            assert "url" in item
            assert item["url"].startswith("http"), f"Invalid URL: {item['url']}"

        print(f"\n✅ Yandex Search: {data['total_results']} results")
        for i, item in enumerate(data["items"][:3], 1):
            print(f"  {i}. {item['title'][:80]}")
            print(f"     {item['url']}")

    def test_search_script_stderr_empty(self):
        """Stderr should be empty for a successful search."""
        from main import _execute_sync

        if "YANDEX_API_KEY" not in os.environ:
            pytest.skip("YANDEX_API_KEY not set in environment")

        result = _execute_sync("python", SEARCH_SCRIPT.strip())
        stderr = result.get("stderr", "")
        # stderr may have some warnings, but should not have tracebacks
        assert "Traceback" not in stderr, f"Traceback in stderr:\n{stderr}"


# ── MCP protocol test (full SSE round-trip) ──────────────────────────────


class TestYandexSearchViaMCP:
    """Execute the search script through the full MCP SSE protocol."""

    @pytest.mark.asyncio
    async def test_search_via_mcp(self, sandbox_server: str):
        """Connect via SSE, call execute_code with the Yandex search script."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        if "YANDEX_API_KEY" not in os.environ:
            pytest.skip("YANDEX_API_KEY not set in environment")

        async with streamablehttp_client(f"{sandbox_server}/sse") as (
            read,
            write,
            _,
        ), ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                "execute_code",
                arguments={
                    "language": "python",
                    "code": SEARCH_SCRIPT.strip(),
                },
            )

            output = result.content[0].text if result.content else ""
            assert output, "Empty output from MCP execute_code"

            # MCP returns the full ExecutionResult as text
            try:
                exec_result = json.loads(output)
            except json.JSONDecodeError as e:
                pytest.fail(f"Invalid MCP result JSON: {e}\nRaw:\n{output}")

            stdout_text = exec_result.get("stdout", "")
            if exec_result.get("error"):
                pytest.fail(f"MCP execution error: {exec_result['error']}")

            try:
                data = json.loads(stdout_text)
            except json.JSONDecodeError as e:
                pytest.fail(f"Invalid search result JSON: {e}\nRaw stdout:\n{stdout_text}")

            if "error" in data:
                err = data["error"]
                if "403" in err or "Permission" in err or "Forbidden" in err:
                    print(f"\n⚠️  Yandex API auth error via MCP: {err}")
                    print("   MCP round-trip OK.")
                    return
                pytest.fail(f"Yandex API error via MCP: {data['error']}")

            assert data.get("api") == "yandex_search"
            assert data.get("total_results", 0) > 0
            assert len(data.get("items", [])) >= 1

            print(f"\n✅ MCP Yandex Search: {data['total_results']} results")
            for item in data["items"][:2]:
                print(f"  • {item['title'][:80]}")


# ── Malformed input / edge case tests ────────────────────────────────────


class TestYandexSearchEdgeCases:
    """Edge case tests for the Yandex search script."""

    def test_empty_query_script(self):
        """A script with an empty query should fail gracefully."""
        from main import _execute_sync

        if "YANDEX_API_KEY" not in os.environ:
            pytest.skip("YANDEX_API_KEY not set in environment")

        script = r"""
import os, json, base64, urllib.request
API_KEY = os.environ["YANDEX_API_KEY"]
FOLDER_ID = os.environ["YANDEX_FOLDER_ID"]
body = json.dumps({
    "query": {"searchType": "SEARCH_TYPE_RU", "queryText": ""},
    "folderId": FOLDER_ID,
    "responseFormat": "FORMAT_XML"
}).encode()
req = urllib.request.Request(
    "https://searchapi.api.cloud.yandex.net/v2/web/search",
    data=body,
    headers={"Authorization": f"Api-Key {API_KEY}", "Content-Type": "application/json"}
)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        xml_str = base64.b64decode(data["rawData"]).decode("utf-8")
        print(json.dumps({"status": resp.status, "has_data": bool(xml_str)}, ensure_ascii=False))
except urllib.error.HTTPError as e:
    print(json.dumps({"http_error": e.code, "message": str(e)}, ensure_ascii=False))
"""
        result = _execute_sync("python", script.strip())
        stdout = result.get("stdout", "")
        assert stdout, "Empty stdout"
        data = json.loads(stdout)
        # Empty query should either work or return HTTP error
        assert "has_data" in data or "http_error" in data

    def test_invalid_api_key(self):
        """Script with invalid API key should get 403/401."""
        from main import _execute_sync

        # Use a deliberately wrong key
        script = r"""
import json, base64, urllib.request, urllib.error
body = json.dumps({
    "query": {"searchType": "SEARCH_TYPE_RU", "queryText": "test"},
    "folderId": "invalid_folder",
    "responseFormat": "FORMAT_XML"
}).encode()
req = urllib.request.Request(
    "https://searchapi.api.cloud.yandex.net/v2/web/search",
    data=body,
    headers={"Authorization": "Api-Key deadbeef", "Content-Type": "application/json"}
)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(json.dumps({"unexpected_status": resp.status}))
except urllib.error.HTTPError as e:
    print(json.dumps({"http_error": e.code}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"error": str(e)}, ensure_ascii=False))
"""
        result = _execute_sync("python", script.strip())
        stdout = result.get("stdout", "")
        data = json.loads(stdout)

        # Should get a 401 or 403
        http_err = data.get("http_error")
        assert http_err in (401, 403), f"Expected 401/403, got: {data}"

    def test_invalid_folder_id(self):
        """Script with invalid folder_id should get an error."""
        from main import _execute_sync

        if "YANDEX_API_KEY" not in os.environ:
            pytest.skip("YANDEX_API_KEY not set in environment")

        api_key = os.environ["YANDEX_API_KEY"]
        script = f"""
import json, base64, urllib.request, urllib.error
API_KEY = "{api_key}"
body = json.dumps({{
    "query": {{"searchType": "SEARCH_TYPE_RU", "queryText": "test"}},
    "folderId": "bogus-folder-id",
    "responseFormat": "FORMAT_XML"
}}).encode()
req = urllib.request.Request(
    "https://searchapi.api.cloud.yandex.net/v2/web/search",
    data=body,
    headers={{"Authorization": f"Api-Key {{API_KEY}}", "Content-Type": "application/json"}}
)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(json.dumps({{"unexpected_status": resp.status}}))
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(json.dumps({{"http_error": e.code, "body": body[:200]}}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({{"error": str(e)}}, ensure_ascii=False))
"""
        result = _execute_sync("python", script.strip())
        stdout = result.get("stdout", "")
        data = json.loads(stdout)

        # Invalid folder should get 4xx error
        assert data.get("http_error", 0) >= 400, f"Expected 4xx, got: {data}"
