import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('def check(candidate):\n\n    # Check some simple cases\n    assert candidate(7) == (0, 1)\n    assert candidate(-78) == (1, 1)\n    assert candidate(3452) == (2, 2)\n    assert candidate(346211) == (3, 3)\n    assert candidate(-345821) == (3, 3)\n    assert candidate(-2) == (1, 0)\n    assert candidate(-45347) == (2, 3)\n    assert candidate(0) == (1, 0)\n\n\n    # Check some edge cases that are easy to work out by hand.\n    assert True\n\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['even_odd_count'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
