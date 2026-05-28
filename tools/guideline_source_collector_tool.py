from __future__ import annotations

import html
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from tools.guideline_section_mapper_tool import GuidelineSectionMapperTool


PDFTextExtractor = Callable[[Path], str]


@dataclass(frozen=True)
class CollectedSource:
    source: str
    content_type: str
    text: str


class GuidelineSourceCollectorTool:
    """Fetches real guideline HTML/PDF sources and writes raw import text."""

    REQUIRED_METADATA = {
        "disease_key",
        "disease_name",
        "source_type",
        "evidence_level",
        "title",
        "publisher",
        "source_id",
    }

    def __init__(
        self,
        timeout_seconds: float = 20.0,
        pdf_text_extractor: PDFTextExtractor | None = None,
        section_mapper: GuidelineSectionMapperTool | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.pdf_text_extractor = pdf_text_extractor
        self.section_mapper = section_mapper or GuidelineSectionMapperTool()

    def collect_to_raw_file(
        self,
        source: str,
        raw_output_path: Path | str,
        metadata: dict[str, str],
        semantic_map: bool = False,
    ) -> dict[str, Any]:
        missing = sorted(self.REQUIRED_METADATA - set(metadata))
        if missing:
            raise ValueError(f"Missing guideline metadata: {', '.join(missing)}")

        collected = self.collect(source)
        raw_text = self.build_raw_text(
            collected=collected,
            metadata=metadata,
            semantic_map=semantic_map,
        )
        raw_path = Path(raw_output_path)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(raw_text, encoding="utf-8")
        return {
            "source": source,
            "raw_output_path": str(raw_path),
            "content_type": collected.content_type,
            "char_count": len(collected.text),
        }

    def collect(self, source: str) -> CollectedSource:
        content, content_type, suffix = self._read_source(source)
        if "pdf" in content_type or suffix == ".pdf":
            text = self._extract_pdf_text(content=content, source=source)
            return CollectedSource(source=source, content_type="application/pdf", text=text)
        return CollectedSource(
            source=source,
            content_type=content_type or "text/html",
            text=self._extract_html_or_text(content.decode("utf-8", errors="replace")),
        )

    def build_raw_text(
        self,
        collected: CollectedSource,
        metadata: dict[str, str],
        semantic_map: bool = False,
    ) -> str:
        lines: list[str] = []
        normalized_metadata = dict(metadata)
        normalized_metadata.setdefault("url", collected.source)
        for key in [
            "disease_key",
            "disease_name",
            "source_type",
            "evidence_level",
            "title",
            "publisher",
            "source_id",
            "url",
            "source_kind",
            "evidence_note",
            "publication_year",
            "region",
            "source_priority",
        ]:
            value = normalized_metadata.get(key)
            if value:
                lines.append(f"{key}: {value}")
        body = self._ensure_sectioned_text(collected.text)
        if semantic_map:
            body = self.section_mapper.map_text(body)
        return "\n".join(lines) + "\n\n" + body.strip() + "\n"

    def _read_source(self, source: str) -> tuple[bytes, str, str]:
        parsed = urlparse(source)
        if parsed.scheme in {"http", "https"}:
            with urllib.request.urlopen(source, timeout=self.timeout_seconds) as response:
                content_type = response.headers.get_content_type()
                suffix = Path(parsed.path).suffix.lower()
                return response.read(), content_type, suffix

        path = Path(parsed.path if parsed.scheme == "file" else source)
        content = path.read_bytes()
        suffix = path.suffix.lower()
        content_type = self._content_type_from_suffix(suffix)
        return content, content_type, suffix

    def _content_type_from_suffix(self, suffix: str) -> str:
        if suffix == ".pdf":
            return "application/pdf"
        if suffix in {".html", ".htm"}:
            return "text/html"
        return "text/plain"

    def _extract_html_or_text(self, text: str) -> str:
        if "<" not in text or ">" not in text:
            return self._normalize_plain_text(text)
        text = re.sub(
            r"(?is)<(script|style|noscript).*?>.*?</\1>",
            " ",
            text,
        )
        text = re.sub(r"(?i)</h[1-6]>", "\n", text)
        text = re.sub(r"(?i)<h[1-6][^>]*>", "\n## ", text)
        text = re.sub(r"(?i)</(p|div|li|tr|section|article)>", "\n", text)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        return self._normalize_plain_text(html.unescape(text))

    def _normalize_plain_text(self, text: str) -> str:
        normalized_lines: list[str] = []
        for line in text.splitlines():
            stripped = re.sub(r"[ \t]+", " ", line).strip()
            if stripped:
                normalized_lines.append(stripped)
        return "\n".join(normalized_lines)

    def _ensure_sectioned_text(self, text: str) -> str:
        normalized = self._normalize_plain_text(text)
        if re.search(r"(?m)^##\s+\S+", normalized):
            return normalized
        return f"## source_text\n{normalized}"

    def _extract_pdf_text(self, content: bytes, source: str) -> str:
        temp_path = Path("/private/tmp") / (
            "medscope_guideline_source_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(source).name)
        )
        if not temp_path.suffix:
            temp_path = temp_path.with_suffix(".pdf")
        temp_path.write_bytes(content)
        try:
            extractor = self.pdf_text_extractor or self._default_pdf_text_extractor
            text = extractor(temp_path)
            return self._normalize_plain_text(text)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    def _default_pdf_text_extractor(self, path: Path) -> str:
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            try:
                from PyPDF2 import PdfReader  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "PDF guideline extraction requires pypdf or PyPDF2. "
                    "Install one of them, or pass a pdf_text_extractor."
                ) from exc

        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages).strip()
        if not text:
            raise ValueError("PDF text extraction returned empty text")
        return text
