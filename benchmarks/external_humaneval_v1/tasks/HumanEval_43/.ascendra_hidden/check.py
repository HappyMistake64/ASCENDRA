import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('\n\nMETADATA = {}\n\n\ndef check(candidate):\n    assert candidate([1, 3, 5, 0]) == False\n    assert candidate([1, 3, -2, 1]) == False\n    assert candidate([1, 2, 3, 7]) == False\n    assert candidate([2, 4, -5, 3, 5, 7]) == True\n    assert candidate([1]) == False\n\n    assert candidate([-3, 9, -1, 3, 2, 30]) == True\n    assert candidate([-3, 9, -1, 3, 2, 31]) == True\n    assert candidate([-3, 9, -1, 4, 2, 30]) == False\n    assert candidate([-3, 9, -1, 4, 2, 31]) == False\n\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['pairs_sum_to_zero'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
