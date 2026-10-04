from task import chunks
assert chunks([1,2,3,4,5],2)==[[1,2],[3,4],[5]]
assert chunks([],3)==[]
try: chunks([1],0)
except ValueError: pass
else: raise AssertionError("size<=0 must raise")
