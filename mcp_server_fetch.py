from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("Web Fetch")


class HTMLTextExtractor(HTMLParser):
    """Convert HTML into readable plain text."""

    SKIP_TAGS = {
        "script",
        "style",
        "noscript",
        "svg",
        "head",
    }

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return

        if self.skip_depth == 0 and tag in {
            "p",
            "div",
            "section",
            "article",
            "br",
            "li",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "tr",
        }:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag in self.SKIP_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return

        if self.skip_depth == 0 and tag in {
            "p",
            "div",
            "section",
            "article",
            "li",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "tr",
        }:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth == 0 and data.strip():
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = HTMLTextExtractor()
    parser.feed(html)

    text = "".join(parser.parts)

    lines = []
    previous_blank = False

    for line in text.splitlines():
        line = " ".join(line.split())

        if not line:
            if not previous_blank:
                lines.append("")
            previous_blank = True
        else:
            lines.append(line)
            previous_blank = False

    return "\n".join(lines).strip()


@mcp.tool()
async def fetch(url: str, max_length: int = 4000) -> str:
    """
    Fetch a web page or publicly accessible document URL and return
    readable text.

    Use this tool when the user provides a URL and asks about its content.
    """

    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return "Error: Only HTTP and HTTPS URLs are supported."

    if not parsed.netloc:
        return "Error: Invalid URL."

    max_length = max(500, min(max_length, 10000))

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/151 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/pdf,text/plain;q=0.9,*/*;q=0.8"
        ),
    }

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=20.0,
            headers=headers,
        ) as client:

            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get(
                "content-type",
                ""
            ).lower()

            if "text/plain" in content_type:
                text = response.text

            elif "text/html" in content_type or "application/xhtml+xml" in content_type:
                text = html_to_text(response.text)

            elif "application/json" in content_type:
                text = response.text

            else:
                return (
                    f"URL was reachable, but the returned content type "
                    f"'{content_type}' is not supported as readable text."
                )

            if not text:
                return "The page was fetched successfully but contained no readable text."

            if len(text) > max_length:
                text = text[:max_length] + "\n\n[Content truncated]"

            return (
                f"Source URL: {str(response.url)}\n\n"
                f"{text}"
            )

    except httpx.HTTPStatusError as exc:
        return (
            f"Error fetching URL: HTTP {exc.response.status_code} "
            f"from {url}"
        )

    except httpx.RequestError as exc:
        return f"Error fetching URL: {exc}"

    except Exception as exc:
        return f"Unexpected fetch error: {exc}"


if __name__ == "__main__":
    mcp.run(transport="stdio")