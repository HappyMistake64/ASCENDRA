import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('def check(candidate):\n\n    # Check some simple cases\n    assert candidate("1/5", "5/1") == True, \'test1\'\n    assert candidate("1/6", "2/1") == False, \'test2\'\n    assert candidate("5/1", "3/1") == True, \'test3\'\n    assert candidate("7/10", "10/2") == False, \'test4\'\n    assert candidate("2/10", "50/10") == True, \'test5\'\n    assert candidate("7/2", "4/2") == True, \'test6\'\n    assert candidate("11/6", "6/1") == True, \'test7\'\n    assert candidate("2/3", "5/2") == False, \'test8\'\n    assert candidate("5/2", "3/5") == False, \'test9\'\n    assert candidate("2/4", "8/4") == True, \'test10\'\n\n\n    # Check some edge cases that are easy to work out by hand.\n    assert candidate("2/4", "4/2") == True, \'test11\'\n    assert candidate("1/5", "5/1") == True, \'test12\'\n    assert candidate("1/5", "1/5") == False, \'test13\'\n\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['simplify'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
