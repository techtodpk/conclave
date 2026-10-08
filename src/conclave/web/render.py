"""Turn the Markdown that models and Conclave write into safe HTML for the app.

Model output is untrusted: raw HTML in it is shown as text, never run, and links open
in a new tab without access to the app.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml

LABELS = ("verified", "agreed but unchecked", "single source", "single model", "disputed")
_LABEL = re.compile(r"\[(" + "|".join(re.escape(x) for x in LABELS) + r")\]")
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)

_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
_md.enable("table")
# No images: a model could otherwise make the page fetch a URL that carries your research.
_md.disable("image")
_md.validateLink = lambda url: url.strip().lower().startswith(("http://", "https://", "#"))


def _link_open(renderer, tokens, idx, options, env):
    tokens[idx].attrSet("target", "_blank")
    tokens[idx].attrSet("rel", "noopener noreferrer")
    return renderer.renderToken(tokens, idx, options, env)


_md.add_render_rule("link_open", _link_open)


def label_class(label: str) -> str:
    return "label-" + label.replace(" ", "-")


def _text(renderer, tokens, idx, options, env):
    """Plain text, with claim labels such as [verified] shown as badges.

    Done here, on text only, so a label inside code or a link's title stays as written.
    """
    return _LABEL.sub(
        lambda m: f'<span class="label {label_class(m.group(1))}">{m.group(1)}</span>',
        escapeHtml(tokens[idx].content),
    )


_md.add_render_rule("text", _text)


def markdown(text: str) -> str:
    """HTML for a Markdown text, with claim labels shown as badges."""
    return _md.render(_FRONT_MATTER.sub("", text or ""))


def front_matter(text: str) -> dict[str, str]:
    """The `key: value` lines Conclave writes at the top of answer and review files."""
    match = _FRONT_MATTER.match(text or "")
    if not match:
        return {}
    out = {}
    for line in match.group(0).splitlines()[1:-1]:
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out
