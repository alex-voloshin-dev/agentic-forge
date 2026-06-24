"""HTTP API for the todo service — the entry point."""

from flask import Flask, jsonify, request

from worker import enqueue

app = Flask(__name__)


@app.post("/todos")
def create_todo():
    data = request.get_json()
    enqueue("index", data["id"])  # hand the indexing job to the background worker
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run()
