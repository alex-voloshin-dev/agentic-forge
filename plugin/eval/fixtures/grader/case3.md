# Work under test

The candidate output is a validator `check`:

    def check(payload):
        if "email" not in payload:
            raise ValueError("email required")
        return True

Specification: the validator must verify BOTH required inputs — `email` and `age`. The code
above validates only `email`; `age` is never checked.

## Assertion to grade

1. validates all required inputs (email and age)
