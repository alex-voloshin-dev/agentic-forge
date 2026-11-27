"""The discriminating Tier-2 fixtures do what their cases claim (ADR 0114 amendment).

The harder cases of `reviewer` and `software-engineer` rest on claims about code: a naive fix turns
the visible tests green while breaking a stated invariant, a diff's own tests pass while the defect
it carries is real, an approve-case diff is correct. A claim like that rots silently when a fixture
is edited, so this module executes each one, offline and in-process, against copies of the fixtures
in a temp dir. The careful fix is executed too, so a case cannot demand something impossible.
"""

from __future__ import annotations

import importlib
import inspect
import re
import shutil
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "plugin" / "eval" / "fixtures"
SE = FIXTURES / "software-engineer"
REVIEWER = FIXTURES / "reviewer"

# Top-level module names the fixtures import; dropped from sys.modules around each test so one
# test's copy never leaks into another's.
_FIXTURE_ROOTS = ("case5_allocate", "pricing", "client", "auth")


@pytest.fixture
def fixture_imports(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[Path], None]]:
    """Put a temp dir first on sys.path; forget the fixture modules before and after."""

    def forget() -> None:
        for name in [n for n in sys.modules if n.split(".")[0] in _FIXTURE_ROOTS]:
            del sys.modules[name]

    forget()
    yield lambda root: monkeypatch.syspath_prepend(str(root))
    forget()


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"anchor not unique in {path.name}: {old!r}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def _load(path: Path) -> dict[str, Any]:
    """Execute a fixture test module; return its namespace."""
    namespace: dict[str, Any] = {"__name__": f"_fixture_{path.stem}"}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return namespace


def _run_test_file(path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """Run a fixture test module's ``test_*`` functions: name -> passed."""
    return _run_tests(_load(path), monkeypatch)


def _run_tests(namespace: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for name, fn in namespace.items():
        if not (name.startswith("test_") and callable(fn)):
            continue
        wants = "monkeypatch" in inspect.signature(fn).parameters
        kwargs = {"monkeypatch": monkeypatch} if wants else {}
        try:
            fn(**kwargs)
        except (AssertionError, pytest.fail.Exception):
            results[name] = False
        else:
            results[name] = True
    return results


def _import(name: str) -> ModuleType:
    return importlib.import_module(name)


# --- software-engineer case 5: the lump-sum fix greens the tests but breaks invariant 2 -------

_FLOOR_ONLY = "    return [total_cents * w // whole for w in weights]\n"
_LUMP_SUM = (
    "    parts = [total_cents * w // whole for w in weights]\n"
    "    parts[0] += total_cents - sum(parts)\n"
    "    return parts\n"
)
_LARGEST_REMAINDER = (
    "    parts = [total_cents * w // whole for w in weights]\n"
    "    rest = [total_cents * w % whole for w in weights]\n"
    "    order = sorted(range(len(weights)), key=lambda i: (-rest[i], i))\n"
    "    for i in order[: total_cents - sum(parts)]:\n"
    "        parts[i] += 1\n"
    "    return parts\n"
)


def _within_one_cent(total: int, weights: list[int], parts: list[int]) -> bool:
    whole = sum(weights)
    return sum(parts) == total and all(
        abs(part * whole - total * w) < whole for part, w in zip(parts, weights, strict=True)
    )


def _se5(tmp_path: Path, body: str | None) -> Path:
    for name in ("case5_allocate.py", "test_case5_allocate.py"):
        shutil.copy(SE / name, tmp_path / name)
    if body is not None:
        _replace_once(tmp_path / "case5_allocate.py", _FLOOR_ONLY, body)
    return tmp_path


def test_se5_floor_only_fails_the_visible_test(
    tmp_path: Path, fixture_imports: Callable[[Path], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_imports(_se5(tmp_path, None))
    results = _run_test_file(tmp_path / "test_case5_allocate.py", monkeypatch)
    assert results == {
        "test_allocate_even_split": True,
        "test_allocate_uneven_split_keeps_every_cent": False,
    }


def test_se5_lump_sum_fix_passes_the_tests_but_breaks_the_invariant(
    tmp_path: Path, fixture_imports: Callable[[Path], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_imports(_se5(tmp_path, _LUMP_SUM))
    assert all(_run_test_file(tmp_path / "test_case5_allocate.py", monkeypatch).values())
    parts = _import("case5_allocate").allocate(10, [1] * 7)
    assert parts == [4, 1, 1, 1, 1, 1, 1]
    assert not _within_one_cent(10, [1] * 7, parts)


def test_se5_largest_remainder_fix_passes_and_keeps_the_invariant(
    tmp_path: Path, fixture_imports: Callable[[Path], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_imports(_se5(tmp_path, _LARGEST_REMAINDER))
    assert all(_run_test_file(tmp_path / "test_case5_allocate.py", monkeypatch).values())
    allocate = _import("case5_allocate").allocate
    for total, weights in [(10, [1] * 7), (100, [1, 1, 1]), (1001, [3, 5, 7, 11]), (0, [2, 3])]:
        assert _within_one_cent(total, weights, allocate(total, weights)), (total, weights)


# --- software-engineer case 6: a lookup-only fix breaks single use across case variants -------

_CASE6_TREE = SE / "case6" / "tree"
_COUPONS = "pricing/coupons.py"


def _se6(tmp_path: Path) -> Path:
    root = tmp_path / "tree"
    shutil.copytree(_CASE6_TREE, root)
    return root


def _case_tests(module: ModuleType) -> tuple[bool, bool]:
    """(a lower-case code gets the discount, a customer cannot redeem it again in another case)."""
    accepted = module.CouponBook().apply_coupon("c1", "save10", 2000) == 1800
    book = module.CouponBook()
    book.apply_coupon("c1", "SAVE10", 2000)
    try:
        book.apply_coupon("c1", "save10", 2000)
    except module.CouponError:
        single_use = True
    else:
        single_use = False
    return accepted, single_use


def test_se6_fixture_suite_is_green_and_case_sensitive(
    tmp_path: Path, fixture_imports: Callable[[Path], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _se6(tmp_path)
    fixture_imports(root)
    for test_file in ("test_coupons.py", "test_tax.py"):
        assert all(_run_test_file(root / "tests" / test_file, monkeypatch).values()), test_file
    with pytest.raises(_import("pricing.coupons").CouponError):
        _import("pricing.coupons").CouponBook().apply_coupon("c1", "save10", 2000)
    # the planted unrelated issues the case asserts are left in place
    assert "import os\n" in (root / "pricing" / "format.py").read_text(encoding="utf-8")
    assert "TODO(pricing)" in (root / "pricing" / "tax.py").read_text(encoding="utf-8")


def test_se6_lookup_only_fix_breaks_single_use_across_case(
    tmp_path: Path, fixture_imports: Callable[[Path], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _se6(tmp_path)
    _replace_once(root / _COUPONS, "if code not in COUPONS:", "if code.upper() not in COUPONS:")
    _replace_once(root / _COUPONS, "COUPONS[code] // 100", "COUPONS[code.upper()] // 100")
    fixture_imports(root)
    assert all(_run_test_file(root / "tests" / "test_coupons.py", monkeypatch).values())
    assert _case_tests(_import("pricing.coupons")) == (True, False)


def test_se6_normalise_once_fix_keeps_single_use(
    tmp_path: Path, fixture_imports: Callable[[Path], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _se6(tmp_path)
    _replace_once(
        root / _COUPONS,
        "        if code not in COUPONS:",
        "        code = code.upper()\n        if code not in COUPONS:",
    )
    fixture_imports(root)
    assert all(_run_test_file(root / "tests" / "test_coupons.py", monkeypatch).values())
    assert _case_tests(_import("pricing.coupons")) == (True, True)


# --- reviewer cases 4 and 5: the diffs' code, executed ---------------------------------------

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _whole_files(diff: Path) -> dict[str, str]:
    """The post-image of every file whose single hunk covers the whole file (a new file, or a
    hunk from line 1 that spans it); partial hunks (e.g. a docs table) are skipped."""
    files: dict[str, str] = {}
    lines = diff.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        if not lines[i].startswith("+++ b/"):
            i += 1
            continue
        path, i = lines[i][len("+++ b/") :], i + 1
        match = _HUNK.match(lines[i])
        assert match, f"{diff.name}: no hunk after {path}"
        new_len = int(match.group(4) or 1)
        body: list[str] = []
        i += 1
        while i < len(lines) and not lines[i].startswith(("diff --git", "@@")):
            if not lines[i].startswith("-"):
                body.append(lines[i][1:])
            i += 1
        assert len(body) == new_len, f"{diff.name}: {path} hunk declares {new_len}, has {len(body)}"
        if match.group(1) in ("0", "1"):  # the hunk starts at the top of the file
            files[path] = "\n".join(body) + "\n"
    return files


def _materialise(diff: Path, root: Path, extra: dict[str, str]) -> None:
    for rel, text in {**_whole_files(diff), **extra}.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def test_reviewer4_tests_pass_but_the_boundary_fails(
    tmp_path: Path, fixture_imports: Callable[[Path], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    _materialise(
        REVIEWER / "case4.diff",
        tmp_path,
        {
            "client/__init__.py": "",
            "client/errors.py": "class TransientError(Exception):\n    pass\n",
        },
    )
    fixture_imports(tmp_path)
    namespace = _load(tmp_path / "tests" / "test_fetch.py")
    results = _run_tests(namespace, monkeypatch)
    assert len(results) == 2 and all(results.values()), results  # the diff's own tests are green

    fetch = _import("client.fetch")
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    flaky = namespace["FlakySession"](failures=fetch.MAX_ATTEMPTS - 1)
    with pytest.raises(fetch.RetryExhausted):  # the documented third attempt is never made
        fetch.fetch_with_retry(flaky, "u")
    assert flaky.calls == fetch.MAX_ATTEMPTS - 1 == 2

    # the fix the case asks for makes exactly MAX_ATTEMPTS calls
    loop = "range(1, MAX_ATTEMPTS)"
    _replace_once(tmp_path / "client" / "fetch.py", loop, "range(1, MAX_ATTEMPTS + 1)")
    fetch = importlib.reload(fetch)
    flaky = namespace["FlakySession"](failures=fetch.MAX_ATTEMPTS - 1)
    assert fetch.fetch_with_retry(flaky, "u") == "ok" and flaky.calls == fetch.MAX_ATTEMPTS


def test_reviewer5_diff_is_correct(
    tmp_path: Path, fixture_imports: Callable[[Path], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    _materialise(REVIEWER / "case5.diff", tmp_path, {"auth/__init__.py": ""})
    fixture_imports(tmp_path)
    results = _run_test_file(tmp_path / "tests" / "test_token_cache.py", monkeypatch)
    assert len(results) == 4 and all(results.values()), results
