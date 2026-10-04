from task import safe_div
assert safe_div(6,3)==2
assert safe_div(1,0)==None
assert safe_div(1,0,7)==7
class Bad:
    def __truediv__(self, other): raise TypeError("boom")
try: safe_div(Bad(),1)
except TypeError: pass
else: raise AssertionError("unrelated exception hidden")
