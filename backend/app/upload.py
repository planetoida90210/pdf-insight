import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from fastapi import UploadFile

from app.errors import ApiError, ErrorCode

PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}
READ_CHUNK = 1024 * 1024


async def read_pdf_upload(file: UploadFile, max_bytes: int) -> bytes:
    """Reads at most `max_bytes` + 1 bytes and checks that the upload looks like a PDF."""
    if file.content_type not in PDF_CONTENT_TYPES:
        raise ApiError(ErrorCode.UNSUPPORTED_TYPE)
    data = bytearray()
    while chunk := await file.read(READ_CHUNK):
        data += chunk
        if len(data) > max_bytes:
            raise ApiError(
                ErrorCode.FILE_TOO_LARGE,
                f"Plik jest za duży. Maksymalny rozmiar to {max_bytes // (1024 * 1024)} MB.",
            )
    # PDF readers accept a header within the first 1024 bytes, so we do too.
    if b"%PDF-" not in data[:1024]:
        raise ApiError(ErrorCode.UNSUPPORTED_TYPE)
    return bytes(data)


def open_pdf(data: bytes, max_pages: int) -> pdfium.PdfDocument:
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        if error.err_code == pdfium_raw.FPDF_ERR_PASSWORD:
            raise ApiError(ErrorCode.ENCRYPTED_PDF) from error
        raise ApiError(ErrorCode.INVALID_PDF) from error
    if len(pdf) == 0:
        pdf.close()
        raise ApiError(ErrorCode.INVALID_PDF)
    if len(pdf) > max_pages:
        pdf.close()
        raise ApiError(
            ErrorCode.TOO_MANY_PAGES,
            f"Dokument ma za dużo stron. Maksymalna liczba stron to {max_pages}.",
        )
    return pdf
