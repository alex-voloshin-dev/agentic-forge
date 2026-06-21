# Work under test

The candidate output is a script `report.py`:

    def report(nums):
        print("total:", sum(nums))
        average = sum(nums) / len(nums)
        print("average:", average)
        for n in sorted(nums):
            print(n)

Observed behavior:
- On `report([3, 1, 2])` it prints `total: 6`, then `average: 2.0`, then `1`, `2`, `3`.
- On `report([])` it raises `ZeroDivisionError` at `sum(nums) / len(nums)`.

## Assertions to grade

1. prints a total
2. handles an empty list without crashing
3. sorts ascending
