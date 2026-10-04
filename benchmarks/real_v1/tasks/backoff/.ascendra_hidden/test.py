from task import backoff
assert backoff(0)==1.0
assert backoff(3)==8.0
assert backoff(10,1,60)==60
for args in [(-1,), (1,-1,60), (1,1,-2)]:
    try: backoff(*args)
    except ValueError: pass
    else: raise AssertionError(f"negative accepted: {args}")
