import os
from flask import Flask
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

supabase: Client = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_KEY")
)

@app.route('/')
def index():
    response = supabase.table('tbl_todos').select("id,title,is_completed").execute()
    todos = response.data

    html = '<h1>Todos</h1><ul>'
    for todo in todos:
        checked = "checked" if todo["is_completed"] else ""
        html += f'<li><input type="checkbox" {checked} disabled> {todo["title"]}</li>'
    html += '</ul>'

    return html

if __name__ == '__main__':
    app.run(debug=True)
