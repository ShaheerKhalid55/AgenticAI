(function initializeNexaMarkdown(root, factory) {
  const api = factory();

  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }

  root.NexaMarkdown = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createNexaMarkdown() {
  "use strict";

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function safeHref(value) {
    const href = String(value || "").trim();
    if (/^(https?:|mailto:)/i.test(href) || href.startsWith("/") || href.startsWith("#")) {
      return escapeHtml(href);
    }
    return null;
  }

  function renderInline(value) {
    const placeholders = [];
    const hold = (html) => {
      const key = `\u0000NEXA${placeholders.length}\u0000`;
      placeholders.push(html);
      return key;
    };

    let text = String(value ?? "");

    text = text.replace(/`([^`\n]+)`/g, (_, code) => (
      hold(`<code>${escapeHtml(code)}</code>`)
    ));

    text = text.replace(/\[([^\]]+)\]\(([^\s)]+)(?:\s+["']([^"']*)["'])?\)/g, (_, label, href, title) => {
      const safe = safeHref(href);
      if (!safe) return `${label} (${href})`;
      const titleAttribute = title ? ` title="${escapeHtml(title)}"` : "";
      return hold(
        `<a href="${safe}" target="_blank" rel="noopener noreferrer"${titleAttribute}>${escapeHtml(label)}</a>`
      );
    });

    text = escapeHtml(text)
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_\n]+)__/g, "<strong>$1</strong>")
      .replace(/~~([^~\n]+)~~/g, "<del>$1</del>")
      .replace(/(^|[\s(])\*([^*\n]+)\*(?=$|[\s).,!?;:])/g, "$1<em>$2</em>")
      .replace(/(^|[\s(])_([^_\n]+)_(?=$|[\s).,!?;:])/g, "$1<em>$2</em>")
      .replace(/ {2}\n/g, "<br>")
      .replace(/\n/g, "<br>");

    placeholders.forEach((html, index) => {
      text = text.replace(`\u0000NEXA${index}\u0000`, html);
    });

    return text;
  }

  function isCitation(value) {
    const markerFree = String(value || "")
      .trim()
      .replace(/^[-*+]\s+/, "")
      .replace(/\*\*|__/g, "");
    return /^(?:sources?|citations?|references?|document)\s*:/i.test(markerFree);
  }

  function isBlockStart(value) {
    return /^\s*```/.test(value)
      || /^\s{0,3}#{1,6}\s+/.test(value)
      || /^\s*([-*_])(?:\s*\1){2,}\s*$/.test(value)
      || /^\s*>\s?/.test(value)
      || /^\s*[-*+]\s+/.test(value)
      || /^\s*\d+[.)]\s+/.test(value)
      || isCitation(value);
  }

  function renderMarkdown(value) {
    const lines = String(value ?? "").replace(/\r\n?/g, "\n").split("\n");
    const output = [];
    let index = 0;

    while (index < lines.length) {
      const line = lines[index];

      if (!line.trim()) {
        index += 1;
        continue;
      }

      const fence = line.match(/^\s*```([^\s`]*)\s*$/);
      if (fence) {
        const language = fence[1] ? ` class="language-${escapeHtml(fence[1])}"` : "";
        const code = [];
        index += 1;
        while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
          code.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        output.push(`<pre><code${language}>${escapeHtml(code.join("\n"))}</code></pre>`);
        continue;
      }

      const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
      if (heading) {
        const level = heading[1].length;
        output.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
        index += 1;
        continue;
      }

      if (/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
        output.push("<hr>");
        index += 1;
        continue;
      }

      if (/^\s*>\s?/.test(line)) {
        const quote = [];
        while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
          quote.push(lines[index].replace(/^\s*>\s?/, ""));
          index += 1;
        }
        output.push(`<blockquote>${renderInline(quote.join("\n"))}</blockquote>`);
        continue;
      }

      if (/^\s*[-*+]\s+/.test(line)) {
        const items = [];
        while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
          const item = lines[index].replace(/^\s*[-*+]\s+/, "");
          items.push(`<li${isCitation(item) ? ' class="citation-item"' : ""}>${renderInline(item)}</li>`);
          index += 1;
        }
        output.push(`<ul>${items.join("")}</ul>`);
        continue;
      }

      if (/^\s*\d+[.)]\s+/.test(line)) {
        const items = [];
        const firstNumber = Number(line.match(/^\s*(\d+)/)?.[1] || 1);
        while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) {
          const item = lines[index].replace(/^\s*\d+[.)]\s+/, "");
          items.push(`<li${isCitation(item) ? ' class="citation-item"' : ""}>${renderInline(item)}</li>`);
          index += 1;
        }
        const start = firstNumber !== 1 ? ` start="${firstNumber}"` : "";
        output.push(`<ol${start}>${items.join("")}</ol>`);
        continue;
      }

      if (isCitation(line)) {
        output.push(`<aside class="message-citation">${renderInline(line.trim())}</aside>`);
        index += 1;
        continue;
      }

      const paragraph = [line.trim()];
      index += 1;
      while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index])) {
        paragraph.push(lines[index].trim());
        index += 1;
      }
      output.push(`<p>${renderInline(paragraph.join("\n"))}</p>`);
    }

    return output.join("");
  }

  return Object.freeze({ escapeHtml, render: renderMarkdown });
});
