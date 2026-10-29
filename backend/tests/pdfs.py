from fpdf import FPDF


def text_pdf(*pages: str, password: str | None = None) -> bytes:
    pdf = FPDF()
    pdf.set_font("helvetica", size=12)
    for text in pages:
        pdf.add_page()
        pdf.multi_cell(w=0, text=text)
    if password:
        pdf.set_encryption(owner_password="owner", user_password=password)
    return bytes(pdf.output())
