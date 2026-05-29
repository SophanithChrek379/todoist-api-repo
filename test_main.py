from datetime import datetime, timezone

from fastapi.testclient import TestClient

import main


SEED_CREATED_AT = "2026-01-01T00:00:00+00:00"
SEED_UPDATED_AT = "2026-01-01T00:00:00+00:00"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class FakeResponse:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class FakeQuery:
    def __init__(self, store):
        self.store = store
        self.action = None
        self.payload = None
        self.filters = {}
        self.with_count = False
        self.order_by = None
        self.order_desc = False
        self.limit_n = None
        self.range_start = None
        self.range_end = None

    def select(self, columns, count=None):
        self.action = "select"
        self.with_count = count == "exact"
        return self

    def order(self, column, desc=False):
        self.order_by = column
        self.order_desc = desc
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def range(self, start, end):
        self.range_start = start
        self.range_end = end
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

        total = len(matches)
        if self.order_by:
            matches = sorted(
                matches,
                key=lambda x: x.get(self.order_by) or "",
                reverse=self.order_desc,
            )
        if self.range_start is not None and self.range_end is not None:
            matches = matches[self.range_start : self.range_end + 1]
        elif self.limit_n is not None:
            matches = matches[: self.limit_n]
        return FakeResponse(matches, count=total if self.with_count else None)


class FakeUser:
    def __init__(self, id, email):
        self.id = id
        self.email = email


class FakeSession:
    def __init__(self, access_token, refresh_token):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_type = "bearer"
        self.expires_in = 3600


class FakeAuthResponse:
    def __init__(self, user, session):
        self.user = user
        self.session = session


class FakeAuth:
    def __init__(self):
        self.users = {}  # email -> {id, password}

    def sign_up(self, credentials):
        email = credentials["email"]
        password = credentials["password"]
        if email in self.users:
            raise Exception("User already registered")
        user_id = f"user-{len(self.users) + 1}"
        self.users[email] = {"id": user_id, "password": password}
        user = FakeUser(user_id, email)
        session = FakeSession(f"access-{user_id}", f"refresh-{user_id}")
        return FakeAuthResponse(user, session)

    def sign_in_with_password(self, credentials):
        email = credentials["email"]
        password = credentials["password"]
        record = self.users.get(email)
        if not record or record["password"] != password:
            raise Exception("Invalid login credentials")
        user = FakeUser(record["id"], email)
        session = FakeSession(f"access-{record['id']}", f"refresh-{record['id']}")
        return FakeAuthResponse(user, session)


class FakeSupabase:
    def __init__(self):
        self.store = [
            {
                "id": "todo-1",
                "title": "First todo",
                "is_completed": False,
                "created_at": SEED_CREATED_AT,
                "updated_at": SEED_UPDATED_AT,
            },
            {
                "id": "todo-2",
                "title": "Second todo",
                "is_completed": True,
                "created_at": SEED_CREATED_AT,
                "updated_at": SEED_UPDATED_AT,
            },
        ]
        self.auth = FakeAuth()

    def table(self, name):
        assert name == "tbl_todos"
        return FakeQuery(self.store)


# ----- root -----

def test_read_root():
    client = TestClient(main.app)

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Todoist API is running"}


# ----- GET /todos -----

def test_list_todos_default_shape(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"todos", "meta"}
    assert set(body["meta"].keys()) == {
        "page",
        "limit",
        "total",
        "total_pages",
        "sort_by",
        "order",
    }
    assert body["meta"] == {
        "page": 1,
        "limit": 10,
        "total": 2,
        "total_pages": 1,
        "sort_by": "created_at",
        "order": "desc",
    }
    assert len(body["todos"]) == 2


def test_list_todos_items_include_all_fields(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos")

    assert response.status_code == 200
    first = response.json()["todos"][0]
    assert set(first.keys()) == {"id", "title", "is_completed", "created_at", "updated_at"}


def test_list_todos_pagination_total_pages(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos?page=1&limit=1")

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["page"] == 1
    assert body["meta"]["limit"] == 1
    assert body["meta"]["total"] == 2
    assert body["meta"]["total_pages"] == 2
    assert len(body["todos"]) == 1


def test_list_todos_pagination_second_page(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos?page=2&limit=1")

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["page"] == 2
    assert len(body["todos"]) == 1


def test_list_todos_dynamic_sort_by(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos?sort_by=title&order=asc")

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["sort_by"] == "title"
    assert body["meta"]["order"] == "asc"
    assert body["todos"][0]["title"] == "First todo"


def test_list_todos_invalid_sort_by(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos?sort_by=password")

    assert response.status_code == 422


def test_list_todos_invalid_order(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos?order=sideways")

    assert response.status_code == 422


def test_list_todos_invalid_page(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos?page=0")

    assert response.status_code == 422


def test_list_todos_invalid_limit(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos?limit=0")

    assert response.status_code == 422


# ----- GET /todos/{id} -----

def test_get_todo(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.get("/todos/todo-1")

    assert response.status_code == 200
    assert response.json() == {
        "id": "todo-1",
        "title": "First todo",
        "is_completed": False,
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

    response = client.post("/todos", json={"title": "New todo", "is_completed": False})

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "new-id"
    assert body["title"] == "New todo"
    assert body["is_completed"] is False
    assert "created_at" in body
    assert "updated_at" in body
    assert body["created_at"] == body["updated_at"]


def test_create_todo_defaults_is_completed(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.post("/todos", json={"title": "Only title"})

    assert response.status_code == 201
    assert response.json()["is_completed"] is False


def test_create_todo_requires_title(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.post("/todos", json={"is_completed": True})

    assert response.status_code == 422


# ----- PUT /todos/{id} -----

def test_update_todo(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.put(
        "/todos/todo-1",
        json={"title": "Updated todo", "is_completed": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Updated todo"
    assert body["is_completed"] is True
    assert body["created_at"] == SEED_CREATED_AT
    assert body["updated_at"] != SEED_UPDATED_AT


def test_update_todo_partial_title_only(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.put("/todos/todo-1", json={"title": "Just title"})

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Just title"
    assert body["is_completed"] is False
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

    response = client.patch("/todos/todo-1/completed", json={"is_completed": True})

    assert response.status_code == 200
    body = response.json()
    assert body["is_completed"] is True
    assert body["created_at"] == SEED_CREATED_AT
    assert body["updated_at"] != SEED_UPDATED_AT


def test_patch_todo_completed_rejects_extra_fields(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.patch(
        "/todos/todo-1/completed",
        json={"is_completed": True, "title": "Not allowed"},
    )

    assert response.status_code == 422


def test_patch_todo_completed_not_found(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.patch("/todos/missing/completed", json={"is_completed": True})

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


# ----- POST /auth/register -----

def test_register_success(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "Strong123!"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "new@example.com"
    assert body["user"]["id"] == "user-1"
    assert body["session"]["access_token"] == "access-user-1"
    assert body["session"]["refresh_token"] == "refresh-user-1"
    assert body["session"]["token_type"] == "bearer"


def test_register_duplicate_email(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    client.post(
        "/auth/register",
        json={"email": "dup@example.com", "password": "Strong123!"},
    )
    response = client.post(
        "/auth/register",
        json={"email": "dup@example.com", "password": "Strong123!"},
    )

    assert response.status_code == 400


def test_register_invalid_email(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "Strong123!"},
    )

    assert response.status_code == 422


def test_register_short_password(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "short"},
    )

    assert response.status_code == 422


def test_register_rejects_extra_fields(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "Strong123!", "role": "admin"},
    )

    assert response.status_code == 422


# ----- POST /auth/login -----

def test_login_success(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    client.post(
        "/auth/register",
        json={"email": "me@example.com", "password": "Strong123!"},
    )
    response = client.post(
        "/auth/login",
        json={"email": "me@example.com", "password": "Strong123!"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "me@example.com"
    assert body["session"]["access_token"].startswith("access-")
    assert body["session"]["refresh_token"].startswith("refresh-")


def test_login_wrong_password(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    client.post(
        "/auth/register",
        json={"email": "me@example.com", "password": "Strong123!"},
    )
    response = client.post(
        "/auth/login",
        json={"email": "me@example.com", "password": "WrongPass!"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_login_unknown_user(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "Whatever1!"},
    )

    assert response.status_code == 401


def test_login_missing_password(monkeypatch):
    monkeypatch.setattr(main, "supabase", FakeSupabase())
    client = TestClient(main.app)

    response = client.post("/auth/login", json={"email": "me@example.com"})

    assert response.status_code == 422
