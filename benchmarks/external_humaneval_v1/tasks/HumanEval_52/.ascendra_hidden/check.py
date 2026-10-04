import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('\n\nMETADATA = {}\n\n\ndef check(candidate):\n    assert candidate([1, 2, 4, 10], 100)\n    assert not candidate([1, 20, 4, 10], 5)\n    assert candidate([1, 20, 4, 10], 21)\n    assert candidate([1, 20, 4, 10], 22)\n    assert candidate([1, 8, 4, 10], 11)\n    assert not candidate([1, 8, 4, 10], 10)\n\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['below_threshold'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
