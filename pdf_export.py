"""Minimal text-to-PDF writer (stdlib only)."""

from __future__ import annotations

from pathlib import Path


def _escape_pdf(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", "")
    )


def _latin1_safe(text: str) -> str:
    """Helvetica core fonts are Latin-1; replace unsupported chars."""
    return text.encode("latin-1", errors="replace").decode("latin-1")


def write_text_pdf(
    path: str | Path,
    text: str,
    *,
    title: str = "HumanPredict Report",
    font_size: int = 10,
    line_height: float = 12,
    margin: float = 48,
) -> Path:
    """
    Write a simple multi-page PDF from plain text.
    Uses built-in Helvetica — no third-party packages.
    """
    path = Path(path)
    page_width = 612  # Letter
    page_height = 792
    usable_width = page_width - (2 * margin)
    chars_per_line = max(40, int(usable_width / (font_size * 0.5)))

    wrapped: list[str] = []
    for raw in text.splitlines():
        line = _latin1_safe(raw.rstrip("\n"))
        if not line:
            wrapped.append("")
            continue
        while len(line) > chars_per_line:
            cut = line.rfind(" ", 0, chars_per_line)
            if cut < chars_per_line // 2:
                cut = chars_per_line
            wrapped.append(line[:cut].rstrip())
            line = line[cut:].lstrip()
        wrapped.append(line)

    lines_per_page = max(1, int((page_height - 2 * margin) / line_height))
    pages: list[list[str]] = []
    for i in range(0, max(len(wrapped), 1), lines_per_page):
        pages.append(wrapped[i : i + lines_per_page])
    if not pages:
        pages = [[""]]

    objects: list[bytes] = []

    def add_object(body: str) -> int:
        objects.append(body.encode("latin-1", errors="replace"))
        return len(objects)

    # 1: Catalog, 2: Pages, 3: Font — page content objects follow
    add_object("<< /Type /Catalog /Pages 2 0 R >>")
    # Placeholder for pages object; filled after kids known
    pages_obj_index = add_object("")  # will be object 2
    add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_obj_nums: list[int] = []
    for page_lines in pages:
        y = page_height - margin
        content_parts = ["BT", "/F1 {0} Tf".format(font_size), "16 TL"]
        first = True
        for line in page_lines:
            safe = _escape_pdf(line)
            if first:
                content_parts.append(
                    "1 0 0 1 {0:.2f} {1:.2f} Tm ({2}) Tj".format(margin, y, safe)
                )
                first = False
            else:
                content_parts.append("T*")
                content_parts.append("({0}) Tj".format(safe))
        content_parts.append("ET")
        stream = "\n".join(content_parts)
        content_num = add_object(
            "<< /Length {0} >>\nstream\n{1}\nendstream".format(len(stream.encode("latin-1", errors="replace")), stream)
        )
        page_num = add_object(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {0} {1}] "
            "/Resources << /Font << /F1 3 0 R >> >> /Contents {2} 0 R >>".format(
                page_width, page_height, content_num
            )
        )
        page_obj_nums.append(page_num)

    kids = " ".join("{0} 0 R".format(n) for n in page_obj_nums)
    objects[pages_obj_index - 1] = (
        "<< /Type /Pages /Kids [{0}] /Count {1} >>".format(kids, len(page_obj_nums))
    ).encode("latin-1")

    # Assemble PDF
    out = bytearray()
    out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend("{0} 0 obj\n".format(i).encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref_pos = len(out)
    out.extend("xref\n0 {0}\n".format(len(objects) + 1).encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend("{0:010d} 00000 n \n".format(off).encode("ascii"))
    out.extend(
        (
            "trailer\n<< /Size {0} /Root 1 0 R /Info << /Title ({1}) >> >>\n"
            "startxref\n{2}\n%%EOF\n"
        ).format(
            len(objects) + 1,
            _escape_pdf(_latin1_safe(title)),
            xref_pos,
        ).encode("latin-1", errors="replace")
    )
    path.write_bytes(bytes(out))
    return path
