import os, resource
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
namespace = {}
with open('/task/task.py') as source: candidate = source.read()
exec(compile(candidate, 'task.py', 'exec'), namespace)
exec(compile('def check(candidate):\n\n    # Check some simple cases\n    assert candidate(1, 5) == "0b11"\n    assert candidate(7, 13) == "0b1010"\n    assert candidate(964,977) == "0b1111001010"\n    assert candidate(996,997) == "0b1111100100"\n    assert candidate(560,851) == "0b1011000010"\n    assert candidate(185,546) == "0b101101110"\n    assert candidate(362,496) == "0b110101101"\n    assert candidate(350,902) == "0b1001110010"\n    assert candidate(197,233) == "0b11010111"\n\n\n    # Check some edge cases that are easy to work out by hand.\n    assert candidate(7, 5) == -1\n    assert candidate(5, 1) == -1\n    assert candidate(5, 5) == "0b101"\n\n', 'private_evaluator', 'exec'), namespace)
namespace['check'](namespace['rounded_avg'])
print('ASCENDRA_PRIVATE_CHECK_COMPLETED', flush=True)
