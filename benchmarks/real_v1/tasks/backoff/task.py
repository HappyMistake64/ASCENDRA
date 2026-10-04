def backoff(attempt, base=1.0, cap=60.0):
    return min(base * attempt, cap)
