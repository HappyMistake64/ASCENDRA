import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('def check(candidate):\n\n    # Check some simple cases\n    assert candidate([\n        [1,2,3,4,5,6],\n        [1,2,3,4,1,6],\n        [1,2,3,4,5,1]\n    ], 1) == [(0, 0), (1, 4), (1, 0), (2, 5), (2, 0)]\n    assert candidate([\n        [1,2,3,4,5,6],\n        [1,2,3,4,5,6],\n        [1,2,3,4,5,6],\n        [1,2,3,4,5,6],\n        [1,2,3,4,5,6],\n        [1,2,3,4,5,6]\n    ], 2) == [(0, 1), (1, 1), (2, 1), (3, 1), (4, 1), (5, 1)]\n    assert candidate([\n        [1,2,3,4,5,6],\n        [1,2,3,4,5,6],\n        [1,1,3,4,5,6],\n        [1,2,1,4,5,6],\n        [1,2,3,1,5,6],\n        [1,2,3,4,1,6],\n        [1,2,3,4,5,1]\n    ], 1) == [(0, 0), (1, 0), (2, 1), (2, 0), (3, 2), (3, 0), (4, 3), (4, 0), (5, 4), (5, 0), (6, 5), (6, 0)]\n    assert candidate([], 1) == []\n    assert candidate([[1]], 2) == []\n    assert candidate([[], [1], [1, 2, 3]], 3) == [(2, 2)]\n\n    # Check some edge cases that are easy to work out by hand.\n    assert True\n\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['get_row'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
