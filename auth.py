"""
FastAPI dependencies for authentication and authorization.
Provides utilities for verifying user access to projects and enforcing multi-tenancy.
"""

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from typing import Optional
from sqlmodel import Session, select

from database import get_session
from models.user import User
from models.associations import UserProject

# 1. Security Configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
SECRET_KEY = "un_cod_foarte_secret_si_lung"  # TODO: Use env variable in production
ALGORITHM = "HS256"


# 2. Password verification
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


# 3. JWT Token utilities
def create_access_token(data: dict, expires_delta: Optional[dict] = None) -> str:
    import copy
    from datetime import datetime, timedelta

    to_encode = copy.deepcopy(data)
    if expires_delta:
        expire = datetime.utcnow() + timedelta(**expires_delta)
    else:
        expire = datetime.utcnow() + timedelta(hours=24)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# 4. Dependency to get current user from token
def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> User:
    """
    Extract and validate current user from JWT token.
    Returns the User object from the database.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None or not isinstance(user_id, str):
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Query database for user
    stmt = select(User).where(User.id == user_id)
    user = session.exec(stmt).first()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    return user


def get_current_user_id(user: User = Depends(get_current_user)) -> str:
    """
    Extract user ID from the current user object.
    Convenience dependency for routes that only need the ID.
    """
    return user.id


# 5. Dependency to get project_id from query parameter
def get_current_project_id(project_id: str = Query(...)) -> str:
    """
    Extract and validate project_id from query parameters.
    This is a required parameter for all endpoints to enforce project isolation.
    """
    if not project_id or project_id.strip() == "":
        raise HTTPException(status_code=400, detail="project_id is required")
    return project_id


# 6. Dependency to verify user has access to project
def get_current_project(
    project_id: str = Depends(get_current_project_id),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> str:
    """
    Verify that the current user has access to the requested project.

    Queries the UserProject association table to ensure the user
    has permission to access this project. Raises 403 Forbidden if not authorized.
    """
    # Query UserProject table to verify access
    stmt = select(UserProject).where(
        (UserProject.user_id == user.id) & (UserProject.project_id == project_id)
    )
    user_project = session.exec(stmt).first()

    if not user_project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this project",
        )

    return project_id
