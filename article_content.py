import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


ARTICLE_FETCH_TIMEOUT = 15
MAX_ARTICLE_DOWNLOAD_BYTES = 2 * 1024 * 1024
MAX_ARTICLE_TEXT_CHARS = 16000


def _is_public_http_url(url):
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return False

    try:
        addresses = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        return False

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            return False
    return True


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        target = urljoin(request.full_url, new_url)
        if not _is_public_http_url(target):
            raise ValueError("redirect target is not a public HTTP URL")
        return super().redirect_request(request, file_pointer, code, message, headers, target)


class _ArticleHTMLParser(HTMLParser):
    excluded_tags = {
        "script",
        "style",
        "noscript",
        "svg",
        "canvas",
        "nav",
        "header",
        "footer",
        "form",
        "button",
    }
    text_tags = {"p", "h1", "h2", "h3", "h4", "li", "blockquote", "pre", "td"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.excluded_depth = 0
        self.preferred_depth = 0
        self.capture_depth = 0
        self.all_parts = []
        self.preferred_parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.excluded_tags:
            self.excluded_depth += 1
            return
        if self.excluded_depth:
            return
        if tag in {"article", "main"}:
            self.preferred_depth += 1
        if tag in self.text_tags:
            self.capture_depth += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.excluded_tags:
            self.excluded_depth = max(0, self.excluded_depth - 1)
            return
        if self.excluded_depth:
            return
        if tag in self.text_tags:
            self.capture_depth = max(0, self.capture_depth - 1)
        if tag in {"article", "main"}:
            self.preferred_depth = max(0, self.preferred_depth - 1)

    def handle_data(self, data):
        if self.excluded_depth or not self.capture_depth:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        self.all_parts.append(text)
        if self.preferred_depth:
            self.preferred_parts.append(text)

    def article_text(self):
        preferred = "\n".join(self.preferred_parts)
        text = preferred if len(preferred) >= 300 else "\n".join(self.all_parts)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text[:MAX_ARTICLE_TEXT_CHARS]


def extract_article_text(html_text):
    parser = _ArticleHTMLParser()
    parser.feed(str(html_text or ""))
    parser.close()
    return parser.article_text()


def fetch_article_text(url):
    """Download a public HTML article and return bounded visible article text."""

    if not _is_public_http_url(url):
        return ""

    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
            "User-Agent": "AI-Trend-Dashboard/1.0 (+article analysis)",
        },
    )
    opener = build_opener(_SafeRedirectHandler())
    try:
        with opener.open(request, timeout=ARTICLE_FETCH_TIMEOUT) as response:
            final_url = response.geturl()
            if not _is_public_http_url(final_url):
                return ""

            content_type = str(response.headers.get("Content-Type") or "").lower()
            if content_type and not any(
                allowed in content_type
                for allowed in ("text/html", "application/xhtml+xml", "text/plain")
            ):
                return ""

            data = response.read(MAX_ARTICLE_DOWNLOAD_BYTES + 1)
            if len(data) > MAX_ARTICLE_DOWNLOAD_BYTES:
                return ""
            charset = response.headers.get_content_charset() or "utf-8"
            html_text = data.decode(charset, errors="replace")
    except Exception:
        return ""

    if "text/plain" in content_type:
        return re.sub(r"\s+", " ", html_text).strip()[:MAX_ARTICLE_TEXT_CHARS]
    return extract_article_text(html_text)
