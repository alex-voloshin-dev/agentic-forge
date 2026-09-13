from users_repo import add_user, connect


def test_add_user_returns_an_id() -> None:
    conn = connect()
    assert add_user(conn, "alice", "alice@example.com") == 1
