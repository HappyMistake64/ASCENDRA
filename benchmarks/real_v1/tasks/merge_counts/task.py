def merge_counts(*mappings):
    out={}
    for m in mappings:
        out.update(m)
    return out
