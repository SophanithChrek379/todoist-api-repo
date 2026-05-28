import os
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict
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


@app.get("/")
def read_root():
    return {"message": "Todoist API is running"}


TODO_COLUMNS = "id,title,is_completed,created_at,updated_at"


ALLOWED_SORT_FIELDS = {"id", "title", "is_completed", "created_at", "updated_at"}


@app.get("/todos")
def list_todos(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    sort_by: str = Query("created_at"),
    order: Literal["asc", "desc"] = Query("desc"),
):
    if sort_by not in ALLOWED_SORT_FIELDS:
        raise HTTPException(
            status_code=422,
            detail=f"sort_by must be one of {sorted(ALLOWED_SORT_FIELDS)}",
        )

    start = (page - 1) * limit
    end = start + limit - 1

    response = (
        supabase.table("todoist_data")
        .select(TODO_COLUMNS, count="exact")
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
def get_todo(todo_id: str):
    response = (
        supabase.table("todoist_data")
        .select(TODO_COLUMNS)
        .eq("id", todo_id)
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Todo not found")

    return response.data[0]


@app.post("/todos", status_code=201)
def create_todo(todo: TodoCreate):
    response = (
        supabase.table("todoist_data")
        .insert(todo.model_dump())
        .execute()
    )
    return response.data[0]


@app.put("/todos/{todo_id}")
def update_todo(todo_id: str, todo: TodoUpdate):
    updates = todo.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    response = (
        supabase.table("todoist_data")
        .update(updates)
        .eq("id", todo_id)
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Todo not found")

    return response.data[0]


@app.patch("/todos/{todo_id}/completed")
def update_todo_completed(todo_id: str, todo: TodoCompletedUpdate):
    response = (
        supabase.table("todoist_data")
        .update({"is_completed": todo.is_completed})
        .eq("id", todo_id)
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Todo not found")

    return response.data[0]


@app.delete("/todos/{todo_id}")
def delete_todo(todo_id: str):
    response = (
        supabase.table("todoist_data")
        .delete()
        .eq("id", todo_id)
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Todo not found")

    return {"deleted": response.data[0]}
