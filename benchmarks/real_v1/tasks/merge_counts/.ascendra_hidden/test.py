from task import merge_counts
a={"x":1,"y":2}; b={"x":4,"z":3}
assert merge_counts(a,b)=={"x":5,"y":2,"z":3}
assert a=={"x":1,"y":2} and b=={"x":4,"z":3}
assert merge_counts()=={}
