from __future__ import annotations

__all__ = [
    "handle",
    "render_debug_ui_html",
    "serve_debug_ui",
]


def __getattr__(name: str) -> object:
    if name == "handle":
        from krtour_map_debug_ui.api import handle

        return handle
    if name in {"render_debug_ui_html", "serve_debug_ui"}:
        from krtour_map_debug_ui.server import render_debug_ui_html, serve_debug_ui

        return {
            "render_debug_ui_html": render_debug_ui_html,
            "serve_debug_ui": serve_debug_ui,
        }[name]
    raise AttributeError(name)
