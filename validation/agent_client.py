"""Query a published Fabric data agent over its MCP endpoint (preview).

Kept separate from eval_harness so that the harness stays pure and testable
with no network. This module is the only place that talks to Fabric.

It speaks the MCP streamable HTTP transport directly using the standard
library rather than depending on the `mcp` package. That is a deliberate
choice. Installing `mcp` into a Fabric Spark session pulls new builds of
pydantic, anyio, typing-extensions and jsonschema over the ones the runtime
ships with, which is enough to destabilise the session. The wire protocol is
a handful of JSON-RPC calls, so the dependency buys very little and costs the
one thing a scheduled job cannot afford, which is reliability.

Works unchanged in two places:

* a Fabric notebook, where notebookutils supplies the token
* a laptop, where the Azure CLI supplies the token

Every question opens a fresh MCP session. That is deliberate too. Reusing a
session would let one question's context leak into the next, and the whole
point of the question bank is that each question is asked cold.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

FABRIC_RESOURCE = "https://api.fabric.microsoft.com"
PROTOCOL_VERSION = "2025-06-18"


def mcp_url(workspace_id: str, data_agent_id: str) -> str:
    return (
        f"https://api.fabric.microsoft.com/v1/mcp/workspaces/{workspace_id}"
        f"/dataagents/{data_agent_id}/agent"
    )


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

def token_from_notebookutils() -> str:
    import notebookutils  # noqa: PLC0415

    return notebookutils.credentials.getToken(FABRIC_RESOURCE)


def token_from_azure_cli() -> str:
    result = subprocess.run(
        [
            "az", "account", "get-access-token",
            "--resource", FABRIC_RESOURCE,
            "--query", "accessToken", "-o", "tsv",
        ],
        capture_output=True, text=True, shell=True, check=True,
    )
    return result.stdout.strip()


def get_token() -> str:
    """Prefer the notebook identity, fall back to the Azure CLI."""
    try:
        return token_from_notebookutils()
    except Exception:  # noqa: BLE001 - not running inside a notebook
        return token_from_azure_cli()


# --------------------------------------------------------------------------
# Minimal MCP streamable HTTP client
# --------------------------------------------------------------------------

class McpError(RuntimeError):
    pass


def parse_sse(body: str) -> list[dict]:
    """Pull JSON payloads out of a text/event-stream response."""
    messages = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            messages.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return messages


class McpSession:
    """One MCP session against one endpoint.

    Implements only what the data agent needs: initialize, tools/list and
    tools/call.
    """

    def __init__(self, url: str, token: str, timeout: float = 300.0) -> None:
        self.url = url
        self.token = token
        self.timeout = timeout
        self.session_id: str | None = None
        self._next_id = 0

    def _headers(self) -> dict:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post(self, payload: dict, expect_reply: bool = True) -> dict | None:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.url, data=data, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self.session_id = session_id
                body = response.read().decode("utf-8", errors="replace")
                content_type = (response.headers.get("Content-Type") or "").lower()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:600]
            raise McpError(f"HTTP {exc.code} from MCP endpoint: {detail}") from None

        if not expect_reply:
            return None

        if "text/event-stream" in content_type:
            messages = parse_sse(body)
        elif body.strip():
            messages = [json.loads(body)]
        else:
            messages = []

        target = payload.get("id")
        for message in messages:
            if message.get("id") == target:
                if "error" in message:
                    raise McpError(json.dumps(message["error"])[:600])
                return message.get("result", {})

        if messages:
            return messages[-1].get("result", {})
        raise McpError("no JSON-RPC reply from the MCP endpoint")

    def _call(self, method: str, params: dict) -> dict:
        self._next_id += 1
        return self._post(
            {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        ) or {}

    def initialize(self) -> None:
        self._call(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "contoso-coffee-eval", "version": "1.0"},
            },
        )
        self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            expect_reply=False,
        )

    def list_tools(self) -> list[dict]:
        return self._call("tools/list", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._call("tools/call", {"name": name, "arguments": arguments})
        blocks = result.get("content", []) or []
        texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        return "\n".join(t for t in texts if t)


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------

@dataclass
class AgentReply:
    question: str
    answer: str
    latency_ms: int
    error: str = ""


class DataAgentClient:
    """Ask a published data agent questions.

    Parameters
    ----------
    concurrency:
        How many questions to have in flight at once. Kept low by default.
        The agent is a shared capacity resource, and throttling produces
        failures that look exactly like a flake, which would poison the one
        signal this harness exists to produce.
    """

    def __init__(
        self,
        workspace_id: str,
        data_agent_id: str,
        token: str | None = None,
        timeout: float = 300.0,
        concurrency: int = 3,
    ) -> None:
        self.url = mcp_url(workspace_id, data_agent_id)
        self.token = token or get_token()
        self.timeout = timeout
        self.concurrency = max(1, concurrency)

    def ask_one(self, question: str) -> AgentReply:
        started = time.monotonic()
        try:
            session = McpSession(self.url, self.token, self.timeout)
            session.initialize()
            tools = session.list_tools()
            if not tools:
                raise McpError("the data agent exposed no tools, is it published")
            tool = tools[0]
            schema = tool.get("inputSchema") or tool.get("input_schema") or {}
            properties = schema.get("properties") or {}
            if not properties:
                raise McpError(f"tool {tool.get('name')} declared no input properties")
            argument = next(iter(properties))
            answer = session.call_tool(tool["name"], {argument: question})
            elapsed = int((time.monotonic() - started) * 1000)
            return AgentReply(question, answer, elapsed)
        except Exception as exc:  # noqa: BLE001
            elapsed = int((time.monotonic() - started) * 1000)
            return AgentReply(question, "", elapsed, error=f"{type(exc).__name__}: {exc}")

    def ask(self, questions: list[str]) -> list[AgentReply]:
        """Ask every question. Reply order matches the input order."""
        if self.concurrency == 1:
            return [self.ask_one(q) for q in questions]
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            return list(pool.map(self.ask_one, questions))
