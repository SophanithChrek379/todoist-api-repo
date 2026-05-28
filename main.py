import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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
    isCompleted: bool = False


class TodoUpdate(BaseModel):
    title: Optional[str] = None
    isCompleted: Optional[bool] = None


class TodoCompletedUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    isCompleted: bool


@app.get("/")
def read_root():
    return {"message": "Todoist API is running"}


@app.get("/todos")
def list_todos():
    response = supabase.table("todoist_data").select("id,title,isCompleted").execute()
    return {"todos": response.data}


@app.get("/todos/{todo_id}")
def get_todo(todo_id: str):
    response = (
        supabase.table("todoist_data")
        .select("id,title,isCompleted")
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
        .update({"isCompleted": todo.isCompleted})
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
