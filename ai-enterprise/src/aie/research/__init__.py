"""Research: läsning av offentliga webbsidor bakom Authorization Engine (PR 5, D-057)."""
from .web import TOOL, Response, WebError, WebLimits, WebPage, WebReader, html_to_text, load_limits

__all__ = ["TOOL", "Response", "WebError", "WebLimits", "WebPage", "WebReader", "html_to_text", "load_limits"]
