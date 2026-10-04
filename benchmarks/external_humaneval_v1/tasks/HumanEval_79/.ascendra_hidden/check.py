import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('def check(candidate):\n\n    # Check some simple cases\n    assert candidate(0) == "db0db"\n    assert candidate(32) == "db100000db"\n    assert candidate(103) == "db1100111db"\n    assert candidate(15) == "db1111db", "This prints if this assert fails 1 (good for debugging!)"\n\n    # Check some edge cases that are easy to work out by hand.\n    assert True, "This prints if this assert fails 2 (also good for debugging!)"\n\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['decimal_to_binary'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
