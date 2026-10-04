from task import clamp
assert clamp(5,0,10)==5
assert clamp(-2,0,10)==0
assert clamp(20,0,10)==10
try: clamp(1,3,2)
except ValueError: pass
else: raise AssertionError("low>high must raise")
