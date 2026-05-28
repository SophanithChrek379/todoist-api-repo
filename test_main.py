from datetime import datetime, timezone

from fastapi.testclient import TestClient

import main


SEED_CREATED_AT = "2026-01-01T00:00:00+00:00"
SEED_UPDATED_AT = "2026-01-01T00:00:00+00:00"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, store):
        self.store = store
        self.action = None
        self.payload = None
        self.filters = {}

    def select(self, columns):
        self.action = "select"
        return self

    def insert(self, payload):
        self.action = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.action = "update"
        self.payload = payload
        return self

    def delete(self):
        self.action = "delete"
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def execute(self):
        if self.action == "insert":
            now = _now_iso()
            item = {
                "id": "new-id",
                **self.payload,
                "created_at": now,
                "updated_at": now,
            }
            self.store.append(item)
            return FakeResponse([item])

        if "id" in self.filters:
            matches = [item for item in self.store if item["id"] == self.filters["id"]]
        else:
            matches = list(self.store)

        if self.action == "update":
            for item in matches:
                item.update(self.payload)
                item["updated_at"] = _now_iso()
            return FakeResponse(matches)

        if self.action == "delete":
            for item in matches:
                self.store.remove(item)
            return FakeResponse(matches)

        return FakeResponse(matches)


class FakeSupabase:
    def __init__(self):
        self.store = [
            {
                "id": "todo-1",
                "title": "First todo",
                "isCompleted": False,
                "created_at": SEED_CREATED_AT,
                "updated_at": SEED_UPDATED_AT,
            },
            {
                "id": "todo-2",
                "title": "Second todo",
                "isCompleted": True,
                "created_at": SEED_CREATED_AT,
                "updated_at": SEED_UPDATED_AT,
            },
        ]

    def table(self, name):
        assert name == "todoist_data"
        return FakeQuery(self.store)


# ----- root -----

def test_read_root():
    client = TestClient(main.app)

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Todoist API is running"}


# ----- GET /todos -----

def test_list_todos_wrapped_in_object(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict)
    assert list(body.keys()) == ["todos"]
    assert isinstance(body["todos"], list)
    assert len(body["todos"]) == 2


def test_list_todos_items_include_all_fields(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos")

    assert response.status_code == 200
    first = response.json()["todos"][0]
    assert set(first.keys()) == {"id", "title", "isCompleted", "created_at", "updated_at"}
    assert first["id"] == "todo-1"
    assert first["title"] == "First todo"
    assert first["isCompleted"] is False
    assert first["created_at"] == SEED_CREATED_AT
    assert first["updated_at"] == SEED_UPDATED_AT


# ----- GET /todos/{id} -----

def test_get_todo(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos/todo-1")

    assert response.status_code == 200
    assert response.json() == {
        "id": "todo-1",
        "title": "First todo",
        "isCompleted": False,
        "created_at": SEED_CREATED_AT,
        "updated_at": SEED_UPDATED_AT,
    }


def test_get_todo_not_found(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Todo not found"


# ----- POST /todos -----

def test_create_todo(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.post("/todos", json={"title": "New todo", "isCompleted": False})

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "new-id"
    assert body["title"] == "New todo"
    assert body["isCompleted"] is False
    assert "created_at" in body
    assert "updated_at" in body
    assert body["created_at"] == body["updated_at"]


def test_create_todo_defaults_is_completed(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.post("/todos", json={"title": "Only title"})

    assert response.status_code == 201
    assert response.json()["isCompleted"] is False


def test_create_todo_requires_title(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.post("/todos", json={"isCompleted": True})

    assert response.status_code == 422


# ----- PUT /todos/{id} -----

def test_update_todo(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.put(
        "/todos/todo-1",
        json={"title": "Updated todo", "isCompleted": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Updated todo"
    assert body["isCompleted"] is True
    assert body["created_at"] == SEED_CREATED_AT
    assert body["updated_at"] != SEED_UPDATED_AT


def test_update_todo_partial_title_only(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.put("/todos/todo-1", json={"title": "Just title"})

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Just title"
    assert body["isCompleted"] is False
    assert body["updated_at"] != SEED_UPDATED_AT


def test_update_todo_empty_body(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.put("/todos/todo-1", json={})

    assert response.status_code == 400
    assert response.json()["detail"] == "No fields to update"


def test_update_todo_not_found(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.put("/todos/missing", json={"title": "Nope"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Todo not found"


# ----- PATCH /todos/{id}/completed -----

def test_patch_todo_completed(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.patch("/todos/todo-1/completed", json={"isCompleted": True})

    assert response.status_code == 200
    body = response.json()
    assert body["isCompleted"] is True
    assert body["created_at"] == SEED_CREATED_AT
    assert body["updated_at"] != SEED_UPDATED_AT


def test_patch_todo_completed_rejects_extra_fields(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.patch(
        "/todos/todo-1/completed",
        json={"isCompleted": True, "title": "Not allowed"},
    )

    assert response.status_code == 422


def test_patch_todo_completed_not_found(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.patch("/todos/missing/completed", json={"isCompleted": True})

    assert response.status_code == 404
    assert response.json()["detail"] == "Todo not found"


# ----- DELETE /todos/{id} -----

def test_delete_todo(monkeypatch):
    fake_supabase = FakeSupabase()
    monkeypatch.setattr(main, "supabase", fake_supabase)
    client = TestClient(main.app)

    response = client.delete("/todos/todo-1")

    assert response.status_code == 200
    deleted = response.json()["deleted"]
    assert deleted["id"] == "todo-1"
    assert deleted["created_at"] == SEED_CREATED_AT
    assert deleted["updated_at"] == SEED_UPDATED_AT
    assert all(item["id"] != "todo-1" for item in fake_supabase.store)


def test_delete_todo_not_found(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.delete("/todos/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Todo not found"
