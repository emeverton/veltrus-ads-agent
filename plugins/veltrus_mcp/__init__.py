"""Veltrus Ads Agent — MCP plugin package.

Exposes the running Veltrus Ads Agent (FastAPI service) as an MCP server so it can
be plugged into any MCP-compatible client (Cursor, Claude Desktop, etc.).

The server lives in ``plugins.veltrus_mcp.server``; import it lazily to avoid a
double-import warning when running ``python -m plugins.veltrus_mcp.server``.
"""

__all__ = ["mcp"]


def __getattr__(name: str):  # pragma: no cover - thin lazy accessor
    if name == "mcp":
        from .server import mcp

        return mcp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
