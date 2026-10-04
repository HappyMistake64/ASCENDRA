import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('def check(candidate):\n\n    # Check some simple cases\n    assert True, "This prints if this assert fails 1 (good for debugging!)"\n    assert candidate([2, 1, 1, 4, 5, 8, 2, 3]) == ["Eight", "Five", "Four", "Three", "Two", "Two", "One", "One"], "Error"\n    assert candidate([]) == [], "Error"\n    assert candidate([1, -1 , 55]) == [\'One\'], "Error"\n\n    # Check some edge cases that are easy to work out by hand.\n    assert True, "This prints if this assert fails 2 (also good for debugging!)"\n    assert candidate([1, -1, 3, 2]) == ["Three", "Two", "One"]\n    assert candidate([9, 4, 8]) == ["Nine", "Eight", "Four"]\n\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['by_length'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
