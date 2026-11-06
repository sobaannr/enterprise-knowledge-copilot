from dataclasses import dataclass
from secrets import compare_digest

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    actor: str
    tenant: str
    role: str


def principal(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        raise HTTPException(401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"})
    settings = request.app.state.settings
    if compare_digest(credentials.credentials, settings.admin_token):
        return Principal("local-operator", settings.tenant, "operator")
    if compare_digest(credentials.credentials, settings.reader_token):
        return Principal("local-analyst", settings.tenant, "analyst")
    raise HTTPException(401, "Invalid token", headers={"WWW-Authenticate": "Bearer"})


def operator(user: Principal = Depends(principal)):
    if user.role != "operator":
        raise HTTPException(403, "Operator role required to approve or reject actions")
    return user
