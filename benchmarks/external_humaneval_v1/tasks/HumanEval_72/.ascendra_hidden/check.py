import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('def check(candidate):\n\n    # Check some simple cases\n    assert candidate([3, 2, 3], 9) is True\n    assert candidate([1, 2], 5) is False\n    assert candidate([3], 5) is True\n    assert candidate([3, 2, 3], 1) is False\n\n\n    # Check some edge cases that are easy to work out by hand.\n    assert candidate([1, 2, 3], 6) is False\n    assert candidate([5], 5) is True\n\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['will_it_fly'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
