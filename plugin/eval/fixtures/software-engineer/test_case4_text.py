from case4_text import truncate


def test_truncate() -> None:
    assert truncate("hello world", 5) == "hello"
