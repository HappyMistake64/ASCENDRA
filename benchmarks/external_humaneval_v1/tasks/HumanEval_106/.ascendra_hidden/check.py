import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('def check(candidate):\n\n    assert candidate(5) == [1, 2, 6, 24, 15]\n    assert candidate(7) == [1, 2, 6, 24, 15, 720, 28]\n    assert candidate(1) == [1]\n    assert candidate(3) == [1, 2, 6]\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['f'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
