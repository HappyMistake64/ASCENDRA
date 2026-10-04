from task import dedupe
assert dedupe([1,2,1,3,2])==[1,2,3]
assert dedupe([[1],[1],[2]])==[[1],[2]]
