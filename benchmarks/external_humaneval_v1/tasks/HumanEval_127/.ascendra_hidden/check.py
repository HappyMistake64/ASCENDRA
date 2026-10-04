import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('def check(candidate):\n\n    # Check some simple cases\n    assert candidate((1, 2), (2, 3)) == "NO"\n    assert candidate((-1, 1), (0, 4)) == "NO"\n    assert candidate((-3, -1), (-5, 5)) == "YES"\n    assert candidate((-2, 2), (-4, 0)) == "YES"\n\n    # Check some edge cases that are easy to work out by hand.\n    assert candidate((-11, 2), (-1, -1)) == "NO"\n    assert candidate((1, 2), (3, 5)) == "NO"\n    assert candidate((1, 2), (1, 2)) == "NO"\n    assert candidate((-2, -2), (-3, -2)) == "NO"\n\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['intersection'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
