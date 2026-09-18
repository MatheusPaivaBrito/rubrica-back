from urllib.parse import quote


def pdf_content_disposition(filename: str, *, attachment: bool = False) -> str:
    disposition = "attachment" if attachment else "inline"
    # HTTP response headers must be Latin-1 encodable. RFC 5987 carries the
    # original Unicode name, while the ASCII name serves older clients.
    encoded = quote(filename, safe="")
    fallback = filename if filename.isascii() and all(32 <= ord(char) < 127 and char not in '\\"' for char in filename) else "documento.pdf"
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
