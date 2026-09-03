import base64
import re
from pathlib import Path

import pymupdf as fitz


RESULT_FIELDS = (
    "applicationFileNumber",
    "serviceType",
    "surname",
    "givenName",
    "dateOfBirth",
    "gender",
    "passportNo",
    "contactNo",
    "citizenshipBy",
    "educationalQualification",
    "profession",
    "mothersName",
    "fathersName",
    "passportIssuingOffice",
    "passportDateOfIssue",
    "passportPlaceOfIssue",
    "fileName",
    "personImageBase64",
)

# Longest/most specific variants come first so one label is not mistaken for
# part of another. PPF generators have used small wording variations over time.
LABELS: dict[str, tuple[str, ...]] = {
    "applicationFileNumber": ("Application File Number", "Application File No"),
    "serviceType": ("Service Type",),
    "surname": ("Surname",),
    "givenName": ("Given Name", "Given Names"),
    "dateOfBirth": ("Date Of Birth", "Date of Birth"),
    "gender": ("Gender",),
    "passportNo": ("Passport/Travel Document No", "Passport Number", "Passport No"),
    "contactNo": ("Contact No", "Mobile No", "Phone No"),
    "citizenshipBy": ("Citizenship of India by", "Citizenship By"),
    "educationalQualification": ("Educational Qualification",),
    "profession": ("Profession",),
    "mothersName": ("Mother's Name", "Mothers Name", "Mother Name"),
    "fathersName": (
        "Father's/LG's Name",
        "Father’s/LG’s Name",
        "Father's Name",
        "Father Name",
    ),
    "passportIssuingOffice": ("Passport Issuing Office",),
    "passportDateOfIssue": ("Passport Date Of Issue", "Date of Issue"),
    "passportPlaceOfIssue": ("Passport Place Of Issue", "Place of Issue"),
}

MULTILINE_FIELDS = {"passportIssuingOffice"}
TERMINATOR_LABELS = ("Date & Place of Issue", "Date and Place of Issue")


def _clean(value: str) -> str:
    return " ".join(value.strip(" \t:-,|").split())


def _label_pattern(label: str) -> str:
    # PDF text occasionally separates punctuation or collapses whitespace.
    words = [re.escape(word) for word in label.split()]
    return r"\s+".join(words)


def _all_label_pattern() -> re.Pattern[str]:
    variants = sorted(
        [label for labels in LABELS.values() for label in labels] + list(TERMINATOR_LABELS),
        key=len,
        reverse=True,
    )
    return re.compile(
        r"(?:" + "|".join(_label_pattern(label) for label in variants) + r")\s*:",
        re.IGNORECASE,
    )


ALL_LABELS_RE = _all_label_pattern()


def _extract_from_text(text: str, field: str) -> str:
    """Extract an inline or wrapped label value without consuming the next field."""
    for label in LABELS[field]:
        match = re.search(
            rf"{_label_pattern(label)}\s*:\s*(.*?)"
            rf"(?={ALL_LABELS_RE.pattern}|\n\s*\n|$)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            continue
        value = match.group(1).strip()
        if field not in MULTILINE_FIELDS:
            value = value.splitlines()[0] if value.splitlines() else value
        value = _clean(value)
        if value:
            return value
    return ""


def _extract_by_coordinates(page: fitz.Page, field: str) -> str:
    """Fallback for forms whose visual columns are not preserved in plain text."""
    words = page.get_text("words", sort=True)
    if not words:
        return ""

    label_rects: list[fitz.Rect] = []
    for labels in LABELS.values():
        for label in labels:
            label_rects.extend(page.search_for(label))
    for label in TERMINATOR_LABELS:
        label_rects.extend(page.search_for(label))

    for label in LABELS[field]:
        for rect in page.search_for(label):
            # Values in generated PPFs normally begin to the right of a label.
            right_boundary = page.rect.x1
            for other in label_rects:
                if other.x0 > rect.x1 and abs(other.y0 - rect.y0) <= max(rect.height, other.height):
                    right_boundary = min(right_boundary, other.x0)
            same_line = [
                word
                for word in words
                if word[0] >= rect.x1 - 1
                and word[2] <= right_boundary + 1
                and rect.y0 - 2 <= (word[1] + word[3]) / 2 <= rect.y1 + 2
                and word[4] != ":"
            ]
            value = _clean(" ".join(word[4] for word in same_line))
            if value:
                return value

            # A small box below the label handles intentionally wrapped values.
            next_y = min(
                (other.y0 for other in label_rects if other.y0 > rect.y1 + 1),
                default=rect.y1 + rect.height * 3,
            )
            below = [
                word
                for word in words
                if word[0] >= rect.x0 - 1
                and word[1] >= rect.y1 - 1
                and word[3] <= next_y + 1
            ]
            value = _clean(" ".join(word[4] for word in below))
            if value:
                return value
    return ""


def _extract_issue_pair(text: str, result: dict[str, str]) -> None:
    """Support the common combined 'Date & Place of Issue' PPF row."""
    match = re.search(
        r"Date\s*&\s*Place\s*of\s*Issue\s*:\s*"
        r"([0-9][0-9./-]*)\s+([^\r\n]+)",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        # The combined row is more specific than either standalone fallback.
        result["passportDateOfIssue"] = _clean(match.group(1))
        result["passportPlaceOfIssue"] = _clean(match.group(2))


def _extract_photo(document: fitz.Document) -> str:
    """Return the largest plausible embedded portrait, normalized as JPEG."""
    candidates: dict[int, tuple[int, int, int]] = {}
    for page in document:
        for image in page.get_images(full=True):
            xref, width, height = image[0], image[2], image[3]
            if width >= 80 and height >= 100 and 0.45 <= width / height <= 1.15:
                candidates[xref] = (width * height, width, height)
    if not candidates:
        return ""

    for xref, _ in sorted(candidates.items(), key=lambda item: item[1][0], reverse=True):
        try:
            extracted = document.extract_image(xref)
            pixmap = fitz.Pixmap(extracted["image"])
            if pixmap.colorspace is None:
                continue
            if pixmap.colorspace.n != 3:
                pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
            if pixmap.alpha:
                pixmap = fitz.Pixmap(pixmap, 0)
            jpeg = pixmap.tobytes("jpeg", jpg_quality=90)
            encoded = base64.b64encode(jpeg).decode("ascii")
            return f"data:image/jpeg;base64,{encoded}"
        except Exception:
            continue
    return ""


def extract_ppf(file_path: str) -> dict[str, str]:
    """Extract the fixed PPF fields and embedded applicant photograph."""
    result = {field: "" for field in RESULT_FIELDS}
    result["fileName"] = Path(file_path).name

    with fitz.open(file_path) as document:
        if document.needs_pass:
            raise ValueError("Password-protected PDFs are not supported")
        if document.page_count == 0:
            raise ValueError("PDF has no pages")

        pages = list(document)
        text = "\n".join(page.get_text("text", sort=True) for page in pages)
        for field in LABELS:
            result[field] = _extract_from_text(text, field)
            if not result[field]:
                for page in pages:
                    result[field] = _extract_by_coordinates(page, field)
                    if result[field]:
                        break
        _extract_issue_pair(text, result)
        result["personImageBase64"] = _extract_photo(document)

    return result
