"""Public validation descriptions contain rules and field names, never submitted values."""

from pydantic import ValidationError

RULES = {
    "checkin": ("date_out_of_range", "must be between today (Dubai) and today+365"),
    "nights": ("nights_out_of_range", "must be an integer between 1 and 30"),
    "guests": ("guests_out_of_range", "must be an integer between 1 and 8 and fit the room"),
    "hotel_id": ("unknown_hotel", "must identify a known OSM hotel"),
    "hold_token": ("invalid_hold_token", "must be an unexpired single-use token for this rate"),
}


def validation_detail(exc):
    field = "parameters"
    if isinstance(exc, ValidationError) or hasattr(exc, "errors"):
        errors = exc.errors()
        if errors:
            loc = errors[0].get("loc", ())
            field = str(loc[-1]) if loc else "parameters"
            # Cross-field StayRequest validation has no location.
            msg = errors[0].get("msg", "")
            for candidate in ("checkin", "guests", "as_of"):
                if candidate in msg:
                    field = candidate
                    break
    code, rule = RULES.get(field, ("invalid_input", "must satisfy the published input schema"))
    if field not in RULES and hasattr(exc, "errors") and exc.errors():
        ctx = exc.errors()[0].get("ctx", {})
        bounds = {k: ctx[k] for k in ("ge", "le", "min_length", "max_length") if k in ctx}
        if bounds:
            rule = "must satisfy " + ", ".join(f"{k}={v}" for k, v in bounds.items())
    return {"code": code, "message": rule, "field": field, "rule": rule}
