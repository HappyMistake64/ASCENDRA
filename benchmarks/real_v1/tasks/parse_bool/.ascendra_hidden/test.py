from task import parse_bool
for v in [True,"true"," TRUE ","yes","1","on"]: assert parse_bool(v) is True
for v in [False,"false","No","0","off"]: assert parse_bool(v) is False
for v in ["maybe",1,None]:
    try: parse_bool(v)
    except ValueError: pass
    else: raise AssertionError(f"invalid value accepted: {v!r}")
