import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('def check(candidate):\n\n    # Check some simple cases\n    assert candidate(\'TEST\') == \'tgst\', "This prints if this assert fails 1 (good for debugging!)"\n    assert candidate(\'Mudasir\') == \'mWDCSKR\', "This prints if this assert fails 2 (good for debugging!)"\n    assert candidate(\'YES\') == \'ygs\', "This prints if this assert fails 3 (good for debugging!)"\n    \n    # Check some edge cases that are easy to work out by hand.\n    assert candidate(\'This is a message\') == \'tHKS KS C MGSSCGG\', "This prints if this assert fails 2 (also good for debugging!)"\n    assert candidate("I DoNt KnOw WhAt tO WrItE") == \'k dQnT kNqW wHcT Tq wRkTg\', "This prints if this assert fails 2 (also good for debugging!)"\n\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['encode'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
