import io

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.upload import open_pdf, read_pdf_upload
from tests.pdfs import text_pdf

MB = 1024 * 1024


def upload(data: bytes, content_type: str = "application/pdf") -> UploadFile:
    return UploadFile(
        io.BytesIO(data), filename="f.pdf", headers=Headers({"content-type": content_type})
    )


async def read(data: bytes, content_type: str = "application/pdf") -> bytes:
    return await read_pdf_upload(upload(data, content_type), Settings(max_file_mb=10))


def assert_code(error: pytest.ExceptionInfo[ApiError], code: ErrorCode) -> None:
    assert error.value.code == code


async def test_accepts_pdf() -> None:
    data = text_pdf("Umowa")
    assert await read(data) == data


async def test_content_type_is_not_trusted() -> None:
    data = text_pdf("x")
    assert await read(data, "application/octet-stream") == data


async def test_rejects_not_a_pdf() -> None:
    with pytest.raises(ApiError) as error:
        await read(b"PK\x03\x04 this is a zip")
    assert_code(error, ErrorCode.UNSUPPORTED_TYPE)


async def test_rejects_oversized_file() -> None:
    with pytest.raises(ApiError) as error:
        await read(b"%PDF-1.7\n" + b"0" * (10 * MB))
    assert_code(error, ErrorCode.FILE_TOO_LARGE)
    assert "10 MB" in error.value.message


def test_open_pdf_counts_pages() -> None:
    with open_pdf(text_pdf("a", "b"), max_pages=200) as pdf:
        assert len(pdf) == 2


def test_open_pdf_rejects_encrypted() -> None:
    with pytest.raises(ApiError) as error:
        open_pdf(text_pdf("tajne", password="secret"), max_pages=200)
    assert_code(error, ErrorCode.ENCRYPTED_PDF)


def test_open_pdf_rejects_corrupted() -> None:
    with pytest.raises(ApiError) as error:
        open_pdf(b"%PDF-1.7\nnot really a pdf", max_pages=200)
    assert_code(error, ErrorCode.INVALID_PDF)


def test_open_pdf_rejects_too_many_pages() -> None:
    with pytest.raises(ApiError) as error:
        open_pdf(text_pdf("1", "2", "3"), max_pages=2)
    assert_code(error, ErrorCode.TOO_MANY_PAGES)
