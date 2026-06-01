import os
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from supabase import Client, create_client


load_dotenv()

app = FastAPI()

supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")

if not supabase_url or not supabase_key:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")

supabase: Client = create_client(supabase_url, supabase_key)


class TodoCreate(BaseModel):
    title: str
    is_completed: bool = False


class TodoUpdate(BaseModel):
    title: Optional[str] = None
    is_completed: Optional[bool] = None


class TodoCompletedUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_completed: bool


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str


@app.get("/")
def read_root():
    return {"message": "Todoist API is running"}


# ----- Auth -----

def _auth_payload(auth_response):
    user = auth_response.user
    session = auth_response.session

    if user is None:
        raise HTTPException(status_code=400, detail="Authentication failed")

    payload = {
        "user": {
            "id": user.id,
            "email": user.email,
        }
    }

    if session is not None:
        payload["session"] = {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
            "token_type": session.token_type,
            "expires_in": session.expires_in,
        }

    return payload


@app.post("/auth/register", status_code=201)
def register(body: RegisterRequest):
    try:
        auth_response = supabase.auth.sign_up(
            {"email": body.email, "password": body.password}
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return _auth_payload(auth_response)


@app.post("/auth/login")
def login(body: LoginRequest):
    try:
        auth_response = supabase.auth.sign_in_with_password(
            {"email": body.email, "password": body.password}
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if auth_response.session is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return _auth_payload(auth_response)


@app.post("/auth/refresh")
def refresh(body: RefreshRequest):
    try:
        auth_response = supabase.auth.refresh_session(body.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    session = getattr(auth_response, "session", None)
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
    }


# ----- Auth dependency -----

bearer_scheme = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    token = credentials.credentials
    try:
        result = supabase.auth.get_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = getattr(result, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {"id": user.id, "email": user.email, "token": token}


@app.get("/auth/me")
def me(current_user: dict = Depends(get_current_user)):
    return {"id": current_user["id"], "email": current_user["email"]}


TODO_COLUMNS = "id,title,is_completed,created_at,updated_at"


ALLOWED_SORT_FIELDS = {"id", "title", "is_completed", "created_at", "updated_at"}


@app.get("/todos")
def list_todos(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    sort_by: str = Query("created_at"),
    order: Literal["asc", "desc"] = Query("desc"),
    current_user: dict = Depends(get_current_user),
):
    if sort_by not in ALLOWED_SORT_FIELDS:
        raise HTTPException(
            status_code=422,
            detail=f"sort_by must be one of {sorted(ALLOWED_SORT_FIELDS)}",
        )

    start = (page - 1) * limit
    end = start + limit - 1

    response = (
        supabase.table("tbl_todos")
        .select(TODO_COLUMNS, count="exact")
        .eq("user_id", current_user["id"])
        .order(sort_by, desc=(order == "desc"))
        .range(start, end)
        .execute()
    )

    total = response.count if response.count is not None else len(response.data)
    total_pages = (total + limit - 1) // limit if limit else 0

    return {
        "todos": response.data,
        "meta": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "sort_by": sort_by,
            "order": order,
        },
    }


@app.get("/todos/{todo_id}")
def get_todo(todo_id: str, current_user: dict = Depends(get_current_user)):
    response = (
        supabase.table("tbl_todos")
        .select(TODO_COLUMNS)
        .eq("id", todo_id)
        .eq("user_id", current_user["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Todo not found")

    return response.data[0]


@app.post("/todos", status_code=201)
def create_todo(todo: TodoCreate, current_user: dict = Depends(get_current_user)):
    payload = {**todo.model_dump(), "user_id": current_user["id"]}
    response = (
        supabase.table("tbl_todos")
        .insert(payload)
        .execute()
    )
    return response.data[0]


@app.put("/todos/{todo_id}")
def update_todo(
    todo_id: str,
    todo: TodoUpdate,
    current_user: dict = Depends(get_current_user),
):
    updates = todo.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    response = (
        supabase.table("tbl_todos")
        .update(updates)
        .eq("id", todo_id)
        .eq("user_id", current_user["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Todo not found")

    return response.data[0]


@app.patch("/todos/{todo_id}/completed")
def update_todo_completed(
    todo_id: str,
    todo: TodoCompletedUpdate,
    current_user: dict = Depends(get_current_user),
):
    response = (
        supabase.table("tbl_todos")
        .update({"is_completed": todo.is_completed})
        .eq("id", todo_id)
        .eq("user_id", current_user["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Todo not found")

    return response.data[0]


@app.delete("/todos/{todo_id}")
def delete_todo(todo_id: str, current_user: dict = Depends(get_current_user)):
    response = (
        supabase.table("tbl_todos")
        .delete()
        .eq("id", todo_id)
        .eq("user_id", current_user["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Todo not found")

    return {"deleted": response.data[0]}
