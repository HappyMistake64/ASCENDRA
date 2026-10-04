def safe_div(a,b,default=None):
    try:
        return a/b
    except Exception:
        return default
