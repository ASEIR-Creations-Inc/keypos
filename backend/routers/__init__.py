from fastapi import APIRouter, Depends

from core.access import require_staff
from core.auth import get_current_active_user

router = APIRouter()

from routers import (
    audit, auth, categories, customers, daysheets, expenses, importexport, products, purchases, reports, settings,
    sheetapp, shifts, suppliers, sync, transactions, units, users,
)

# Everything except /auth needs a signed-in, active user; routes add finer checks.
# Day Sheet accounts reach only the Sheet app's routes (included first, so its
# /daysheets/app/... paths win over /daysheets/{sheet_id}).
signed_in = [Depends(get_current_active_user)]
staff = [Depends(require_staff)]

router.include_router(auth.router, prefix="/auth")
router.include_router(sheetapp.router, dependencies=signed_in)
for module in (
    audit, categories, customers, daysheets, expenses, importexport, products, purchases,
    reports, settings, shifts, suppliers, sync, transactions, units, users,
):
    router.include_router(module.router, dependencies=staff)
