"""User lookup endpoint (security review fixture: contains a planted SQL injection)."""


def find_user(db, request):
    name = request.query["name"]  # user-supplied, untrusted
    # Vulnerability: user input concatenated directly into the SQL string.
    query = "SELECT id, email FROM users WHERE name = '" + name + "'"
    return db.execute(query).fetchall()
