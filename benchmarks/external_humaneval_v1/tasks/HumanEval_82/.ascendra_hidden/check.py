import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile("def check(candidate):\n\n    # Check some simple cases\n    assert candidate('Hello') == True\n    assert candidate('abcdcba') == True\n    assert candidate('kittens') == True\n    assert candidate('orange') == False\n    assert candidate('wow') == True\n    assert candidate('world') == True\n    assert candidate('MadaM') == True\n    assert candidate('Wow') == True\n    assert candidate('') == False\n    assert candidate('HI') == True\n    assert candidate('go') == True\n    assert candidate('gogo') == False\n    assert candidate('aaaaaaaaaaaaaaa') == False\n\n    # Check some edge cases that are easy to work out by hand.\n    assert candidate('Madam') == True\n    assert candidate('M') == False\n    assert candidate('0') == False\n\n", 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['prime_length'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
