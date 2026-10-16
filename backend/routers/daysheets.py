from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_active_user
from database import get_db
from models.user import User
from schemas.daysheets import DaySheetSummary, SheetInspection, SheetReturn, SheetReview, SheetUploadResult
from services.daysheet import app, service
from services.daysheet.parse import SheetError

router = APIRouter(prefix="/daysheets", tags=["day-sheets"])

MAX_FILE = 5 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(data: bytes, name: str, code: str, version: int) -> Response:
    return Response(
        content=data,
        media_type=XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Day-Sheet": code,
            "X-Day-Sheet-Version": str(version),
            "Access-Control-Expose-Headers": "Content-Disposition, X-Day-Sheet, X-Day-Sheet-Version",
        },
    )


async def _read(file: UploadFile) -> bytes:
    data = await file.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="The file is larger than 5 MB")
    return data


def _sheet_error(exc: SheetError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=list[DaySheetSummary])
async def list_day_sheets(
    sheet_status: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    return await service.list_sheets(db, user, sheet_status)


@router.post("")
async def new_day_sheet(
    lang: str = Query("pt"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    sheet, data, name = await service.issue_sheet(db, user, lang)
    return _xlsx(data, name, sheet.code, sheet.version)


@router.get("/{sheet_id}/file")
async def day_sheet_file(sheet_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user)):
    sheet, data, name = await service.sheet_file(db, user, sheet_id)
    return _xlsx(data, name, sheet.code, sheet.version)


@router.post("/inspect", response_model=SheetInspection)
async def inspect_day_sheet(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    try:
        return await service.inspect_sheet(db, user, await _read(file))
    except SheetError as exc:
        raise _sheet_error(exc) from exc


@router.post("/refresh")
async def refresh_day_sheet(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    try:
        sheet, data, name = await service.refresh_sheet(db, user, await _read(file))
    except SheetError as exc:
        raise _sheet_error(exc) from exc
    return _xlsx(data, name, sheet.code, sheet.version)


@router.post("/upload", response_model=SheetUploadResult)
async def upload_day_sheet(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    try:
        return await service.upload_sheet(db, user, await _read(file), file.filename)
    except SheetError as exc:
        raise _sheet_error(exc) from exc


# ── Sheets sent from the KEYPOS Sheet app ───────────────────────

@router.get("/{sheet_id}/review", response_model=SheetReview)
async def review_day_sheet(sheet_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user)):
    return await app.review(db, user, sheet_id)


@router.post("/{sheet_id}/approve", response_model=SheetReview)
async def approve_day_sheet(sheet_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user)):
    return await app.approve(db, user, sheet_id)


@router.post("/{sheet_id}/return", response_model=SheetReview)
async def return_day_sheet(
    sheet_id: int, body: SheetReturn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user),
):
    return await app.send_back(db, user, sheet_id, body.note)
