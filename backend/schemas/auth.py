from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=72)


class EffectivePermissions(BaseModel):
    """What the user may do, after role and per-user settings (see core/access.py)."""
    is_admin: bool
    sheet_only: bool  # Day Sheet account: only the KEYPOS Sheet app
    inventory_access: str
    purchases_access: str
    reports_access: str
    customers_access: str
    expenses_access: str
    users_access: str
    can_edit_price: bool
    can_refund: bool
    can_discount: bool
    can_approve_sheets: bool


class UserMeResponse(BaseModel):
    id: int
    name: str
    username: str
    role: str
    permissions: EffectivePermissions


class TokenResponse(UserMeResponse):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
