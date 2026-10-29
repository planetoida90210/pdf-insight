"""Upload checks: size, PDF signature, encryption and page count."""

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from fastapi import UploadFile

from app.config import Settings
from app.errors import ApiError, ErrorCode

# PDF readers accept the header anywhere in the first 1024 bytes, so this check does too.
HEADER_WINDOW = 1024


async def read_pdf_upload(file: UploadFile, settings: Settings) -> bytes:
    """The PDF signature decides the type; the content type sent by the client is not trusted."""
    data = await file.read(settings.max_file_bytes + 1)
    if len(data) > settings.max_file_bytes:
        raise ApiError(ErrorCode.FILE_TOO_LARGE, max_mb=settings.max_file_mb)
    if b"%PDF-" not in data[:HEADER_WINDOW]:
        raise ApiError(ErrorCode.UNSUPPORTED_TYPE)
    return data


def open_pdf(data: bytes, max_pages: int) -> pdfium.PdfDocument:
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        password = error.err_code == pdfium_raw.FPDF_ERR_PASSWORD
        raise ApiError(ErrorCode.ENCRYPTED_PDF if password else ErrorCode.INVALID_PDF) from error
    pages = len(pdf)
    if 0 < pages <= max_pages:
        return pdf
    pdf.close()
    if pages == 0:
        raise ApiError(ErrorCode.INVALID_PDF)
    raise ApiError(ErrorCode.TOO_MANY_PAGES, max_pages=max_pages)
