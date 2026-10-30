"""Ett giltigt simuleringsunderlag för tester (granskning H5): alla tre scenarierna, vinst i pessimistiskt."""


def evidence(daily_net_minor: int = 1_000) -> dict:
    run = {"adjusted_after_tax_minor": 1}
    return {"ready": True, "reasons": [], "runs": 1, "scenarios": {
        "normal": {"runs": [run]}, "pessimistic": {"runs": [run], "daily_net_minor": daily_net_minor},
        "zero_sales": {"runs": [run]}}}
