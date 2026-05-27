from fastapi.testclient import TestClient

import main


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
            item = {"id": "new-id", **self.payload}
            self.store.append(item)
            return FakeResponse([item])

        if "id" in self.filters:
            matches = [item for item in self.store if item["id"] == self.filters["id"]]
        else:
            matches = list(self.store)

        if self.action == "update":
            for item in matches:
                item.update(self.payload)
            return FakeResponse(matches)

        if self.action == "delete":
            for item in matches:
                self.store.remove(item)
            return FakeResponse(matches)

        return FakeResponse(matches)


class FakeSupabase:
    def __init__(self):
        self.store = [
            {"id": "todo-1", "title": "First todo", "isCompleted": False},
            {"id": "todo-2", "title": "Second todo", "isCompleted": True},
        ]

    def table(self, name):
        assert name == "todoist_data"
        return FakeQuery(self.store)


def test_read_root():
    client = TestClient(main.app)

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Todoist API is running"}


def test_list_todos(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos")

    assert response.status_code == 200
    assert response.json()[0]["title"] == "First todo"


def test_get_todo(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos/todo-1")

    assert response.status_code == 200
    assert response.json() == {
        "id": "todo-1",
        "title": "First todo",
        "isCompleted": False,
    }


def test_get_todo_not_found(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Todo not found"


def test_create_todo(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.post("/todos", json={"title": "New todo", "isCompleted": False})

    assert response.status_code == 201
    assert response.json() == {
        "id": "new-id",
        "title": "New todo",
        "isCompleted": False,
    }


def test_update_todo(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.put(
        "/todos/todo-1",
        json={"title": "Updated todo", "isCompleted": True},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Updated todo"
    assert response.json()["isCompleted"] is True


def test_update_todo_empty_body(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.put("/todos/todo-1", json={})

    assert response.status_code == 400
    assert response.json()["detail"] == "No fields to update"


def test_patch_todo_completed(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.patch("/todos/todo-1/completed", json={"isCompleted": True})

    assert response.status_code == 200
    assert response.json()["isCompleted"] is True


def test_patch_todo_completed_rejects_extra_fields(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.patch(
        "/todos/todo-1/completed",
        json={"isCompleted": True, "title": "Not allowed"},
    )

    assert response.status_code == 422


def test_delete_todo(monkeypatch):
    fake_supabase = FakeSupabase()
    monkeypatch.setattr(main, "supabase", fake_supabase)
    client = TestClient(main.app)

    response = client.delete("/todos/todo-1")

    assert response.status_code == 200
    assert response.json()["deleted"]["id"] == "todo-1"
    assert all(item["id"] != "todo-1" for item in fake_supabase.store)
