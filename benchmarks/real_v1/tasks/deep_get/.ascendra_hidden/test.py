from task import deep_get
d={"a":{"b":{"c":3}},"x":None}
assert deep_get(d,"a.b.c")==3
assert deep_get(d,"a.missing",9)==9
assert deep_get(d,"x.y",7)==7
assert deep_get(d,"",5)==5
