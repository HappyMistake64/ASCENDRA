from task import median
x=[3,1,2]; assert median(x)==2 and x==[3,1,2]
y=[4,1,3,2]; assert median(y)==2.5 and y==[4,1,3,2]
try: median([])
except ValueError: pass
else: raise AssertionError("empty must raise")
