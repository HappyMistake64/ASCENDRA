import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('def check(candidate):\n\n    # Check some simple cases\n    assert candidate(3, 4, 5) == 6.00, "This prints if this assert fails 1 (good for debugging!)"\n    assert candidate(1, 2, 10) == -1\n    assert candidate(4, 8, 5) == 8.18\n    assert candidate(2, 2, 2) == 1.73\n    assert candidate(1, 2, 3) == -1\n    assert candidate(10, 5, 7) == 16.25\n    assert candidate(2, 6, 3) == -1\n\n    # Check some edge cases that are easy to work out by hand.\n    assert candidate(1, 1, 1) == 0.43, "This prints if this assert fails 2 (also good for debugging!)"\n    assert candidate(2, 2, 10) == -1\n\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['triangle_area'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
