import logging

import pytest

from app.config import PDF_PARSER_LOGGERS, configure_logging


def test_pdf_parser_warnings_stay_out_of_the_log(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging()
    for name in PDF_PARSER_LOGGERS:
        logging.getLogger(f"{name}.pdfinterp").warning("invalid operand %r", "Umowa poufna")
    assert "Umowa poufna" not in caplog.text
