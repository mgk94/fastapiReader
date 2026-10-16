import io
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from main import extract_pdf


def pdf_upload(name: str = "application.pdf", content: bytes = b"%PDF-test") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=name,
        headers=Headers({"content-type": "application/pdf"}),
    )


class ExtractEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_extracted_json_with_original_filename(self) -> None:
        seen_path: Path | None = None

        def fake_extract(file_path: str) -> dict[str, str]:
            nonlocal seen_path
            seen_path = Path(file_path)
            self.assertTrue(seen_path.exists())
            return {"givenName": "Asha", "fileName": "document.pdf"}

        with patch("main.extract_ppf", side_effect=fake_extract):
            result = await extract_pdf(pdf_upload("asha.pdf"))

        self.assertEqual(result["givenName"], "Asha")
        self.assertEqual(result["fileName"], "asha.pdf")
        self.assertIsNotNone(seen_path)
        self.assertFalse(seen_path.exists())

    async def test_rejects_non_pdf_content(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await extract_pdf(pdf_upload(content=b"not a pdf"))

        self.assertEqual(raised.exception.status_code, 415)

    async def test_rejects_non_pdf_filename(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await extract_pdf(pdf_upload(name="application.txt"))

        self.assertEqual(raised.exception.status_code, 415)

    async def test_maps_extraction_failure_to_unprocessable_content(self) -> None:
        with patch("main.extract_ppf", side_effect=ValueError("PDF has no pages")):
            with self.assertRaises(HTTPException) as raised:
                await extract_pdf(pdf_upload())

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail, "PDF has no pages")


if __name__ == "__main__":
    unittest.main()
