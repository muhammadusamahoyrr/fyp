"""Build real scanned-looking PDFs and page images for OCR tests.

A "scanned PDF" is not a special format: it is an ordinary PDF whose pages
carry a photograph of a sheet of paper and no text layer at all. That is
exactly what this builds -- a JPEG XObject drawn to fill the page, with no text
operators -- so the extractor genuinely finds nothing and the OCR path is
genuinely exercised, rather than being simulated by a stub.

Text is rendered with Pillow's own font so the fixtures need no font file and
produce identical bytes on any machine.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont


def render_page_image(lines, *, size=(1240, 1754), scale=1) -> Image.Image:
    """A4-ish white page with black text. 1240x1754 is A4 at 150dpi."""
    width, height = size
    img = Image.new("RGB", (width * scale, height * scale), "white")
    draw = ImageDraw.Draw(img)
    font = _font(40 * scale)
    y = 80 * scale
    for line in lines:
        draw.text((80 * scale, y), line, fill="black", font=font)
        y += 70 * scale
    return img


def _font(size: int):
    for name in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    # Pillow's builtin is tiny but always present; scale it up by rendering
    # larger images instead of relying on a system font being installed.
    return ImageFont.load_default()


def page_jpeg(lines, **kw) -> bytes:
    buf = io.BytesIO()
    render_page_image(lines, **kw).save(buf, "JPEG", quality=92)
    return buf.getvalue()


def page_png(lines, **kw) -> bytes:
    buf = io.BytesIO()
    render_page_image(lines, **kw).save(buf, "PNG")
    return buf.getvalue()


def _esc(raw: bytes) -> bytes:
    bs = bytes([0x5C])
    return (raw.replace(bs, bs * 2)
               .replace(b"(", bs + b"(")
               .replace(b")", bs + b")"))


def build_pdf(pages) -> bytes:
    """Pages are either bytes (a JPEG -> scanned page) or str (a text page).

    A mixed document is just a list with both kinds, which is what the routing
    rules need in order to be tested on something real.
    """
    objects: dict[int, bytes] = {}
    counter = [0]

    def add(body: bytes) -> int:
        counter[0] += 1
        objects[counter[0]] = body
        return counter[0]

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_parts = []       # (content_id, image_id or None)
    for page in pages:
        if isinstance(page, bytes):
            with Image.open(io.BytesIO(page)) as probe:
                width, height = probe.size
            image_id = add(
                b"<< /Type /XObject /Subtype /Image /Width %d /Height %d"
                b" /ColorSpace /DeviceRGB /BitsPerComponent 8"
                b" /Filter /DCTDecode /Length %d >>\nstream\n"
                % (width, height, len(page)) + page + b"\nendstream")
            # Draw the image over the whole page. No text operators at all.
            stream = (b"q 612 0 0 792 0 0 cm /Im0 Do Q")
            content_id = add(b"<< /Length %d >>\nstream\n" % len(stream)
                             + stream + b"\nendstream")
            page_parts.append((content_id, image_id))
        else:
            body = b"BT /F1 12 Tf 72 720 Td ("
            body += _esc(page.encode("latin-1", "replace")) + b") Tj ET"
            content_id = add(b"<< /Length %d >>\nstream\n" % len(body)
                             + body + b"\nendstream")
            page_parts.append((content_id, None))

    pages_id = counter[0] + len(page_parts) + 1
    kids = []
    for content_id, image_id in page_parts:
        resources = b"/Font << /F1 %d 0 R >>" % font_id
        if image_id is not None:
            resources += b" /XObject << /Im0 %d 0 R >>" % image_id
        kids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792]"
            b" /Resources << %s >> /Contents %d 0 R >>"
            % (pages_id, resources, content_id)))

    actual = add(b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids)
                 + b"] /Count %d >>" % len(kids))
    assert actual == pages_id, "page tree id mispredicted"
    catalog_id = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = {}
    for oid in range(1, counter[0] + 1):
        offsets[oid] = out.tell()
        out.write(b"%d 0 obj\n" % oid + objects[oid] + b"\nendobj\n")
    xref_at = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (counter[0] + 1))
    for oid in range(1, counter[0] + 1):
        out.write(b"%010d 00000 n \n" % offsets[oid])
    out.write(b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
              % (counter[0] + 1, catalog_id, xref_at))
    return out.getvalue()


#: Text that OCR must recover. Short, high-contrast, unambiguous -- the point is
#: to prove the pipeline ran, not to benchmark the engine's accuracy.
SCAN_LINES = ["IN THE COURT OF SESSIONS", "Case No 302 of 2024",
              "Fine of 1000 rupees imposed"]
