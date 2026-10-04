import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('def check(candidate):\n\n    # Check some simple cases\n    assert candidate([]) == 0\n    assert candidate([-1, -2, 0]) == 0\n    assert candidate([1, 1, 2, -2, 3, 4, 5]) == 6\n    assert candidate([1, 6, 9, -6, 0, 1, 5]) == 5\n    assert candidate([1, 100, 98, -7, 1, -1]) == 4\n    assert candidate([12, 23, 34, -45, -56, 0]) == 5\n    assert candidate([-0, 1**0]) == 1\n    assert candidate([1]) == 1\n\n    # Check some edge cases that are easy to work out by hand.\n    assert True, "This prints if this assert fails 2 (also good for debugging!)"\n\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['count_nums'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
