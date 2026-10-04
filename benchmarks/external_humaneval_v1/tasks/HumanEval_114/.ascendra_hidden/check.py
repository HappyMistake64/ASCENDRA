import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('def check(candidate):\n\n    # Check some simple cases\n    assert candidate([2, 3, 4, 1, 2, 4]) == 1, "This prints if this assert fails 1 (good for debugging!)"\n    assert candidate([-1, -2, -3]) == -6\n    assert candidate([-1, -2, -3, 2, -10]) == -14\n    assert candidate([-9999999999999999]) == -9999999999999999\n    assert candidate([0, 10, 20, 1000000]) == 0\n    assert candidate([-1, -2, -3, 10, -5]) == -6\n    assert candidate([100, -1, -2, -3, 10, -5]) == -6\n    assert candidate([10, 11, 13, 8, 3, 4]) == 3\n    assert candidate([100, -33, 32, -1, 0, -2]) == -33\n\n    # Check some edge cases that are easy to work out by hand.\n    assert candidate([-10]) == -10, "This prints if this assert fails 2 (also good for debugging!)"\n    assert candidate([7]) == 7\n    assert candidate([1, -1]) == -1\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['minSubArraySum'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
