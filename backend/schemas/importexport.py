from pydantic import BaseModel


class ImportSummaryResponse(BaseModel):
    """Returned by all import endpoints."""
    imported_count: int
    updated_count: int
    skipped_count: int
    errors: list[str]


class ImportErrorDetail(BaseModel):
    row_number: int
    field: str
    message: str
