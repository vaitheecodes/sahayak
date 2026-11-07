"""A minimal PDF writer for tests: each page's lines as Helvetica text,
or no text at all (what a scanned page looks like to a text extractor)."""

from __future__ import annotations


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[list[str]], title: str | None = None) -> bytes:
    objects: dict[int, str] = {3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    kids, number = [], 4
    for lines in pages:
        content = ("BT /F1 11 Tf 14 TL 72 740 Td " + " ".join(f"({_escape(line)}) Tj T*" for line in lines)
                   + " ET") if lines else "0.9 g 72 72 468 648 re f"
        objects[number] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                           f"/Resources << /Font << /F1 3 0 R >> >> /Contents {number + 1} 0 R >>")
        objects[number + 1] = f"<< /Length {len(content)} >>\nstream\n{content}\nendstream"
        kids.append(number)
        number += 2
    objects[1] = "<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    info = None
    if title:
        info = number
        objects[info] = f"<< /Title ({_escape(title)}) >>"
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for n in sorted(objects):
        offsets[n] = len(out)
        out += f"{n} 0 obj\n{objects[n]}\nendobj\n".encode("latin-1")
    xref = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    for n in range(1, size):
        out += f"{offsets.get(n, 0):010d} {'00000 n' if n in offsets else '65535 f'} \n".encode()
    trailer = f"<< /Size {size} /Root 1 0 R{f' /Info {info} 0 R' if info else ''} >>"
    out += f"trailer\n{trailer}\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
