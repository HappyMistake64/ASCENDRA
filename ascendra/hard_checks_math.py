"""Public-only deterministic hard development fixtures with independent oracles.

No private tests are read. Large expected values are derived from structured
families; resource witnesses below are not claims of optimal general algorithms.
"""
from collections import deque
from functools import lru_cache
import hashlib
import heapq
import itertools
import json
import random

TASK_IDS = ('abc392_g', 'abc399_f', 'arc194_b', 'arc194_e')
MOD = 998244353
PUBLIC_HASHES = {
    'abc392_g': '3303d501cee39fde50b22bfc4f990c659722f432e7afc57ccf56771d9e0ce0e6',
    'abc399_f': 'c14892dfb59c23ecb96ddd3f7bb4a9d11d6e20097e5f7006362b678c1f69a5a1',
    'arc194_b': '2219b2479d1f5a891de3acb77a3e712f3f94ebe9804e23dff1750fd7c721baa3',
    'arc194_e': 'a16ebc47cc3bb96b0d632e250b0e190008c63edf1a410e838ad7f145bf9b2bc8',
}


def _check_task(task):
    try:
        task_id = task['task_id']
        snapshot = dict(statement=task['statement'], examples=[
            dict(input=e['input'], output=e['output']) for e in task['examples']])
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if task_id not in TASK_IDS or digest != PUBLIC_HASHES[task_id]:
            raise ValueError('Public statement/examples differ from reviewed source')
        return task_id
    except (KeyError, TypeError) as exc:
        raise ValueError('Malformed public task') from exc


def fine_brute(values):
    """Definition oracle: enumerate unordered triples, without convolution."""
    return sum(a + c == 2*b for a, b, c in itertools.combinations(sorted(values), 3))


def interval_triplets(n, missing=None):
    # Each positive gap d contributes n-2d; summing gives floor((n-1)^2/4).
    result = (n - 1)**2 // 4
    if missing is not None:
        # Triples containing missing as middle, largest, or smallest are disjoint.
        result -= min(missing-1, n-missing) + (missing-1)//2 + (n-missing)//2
    return result


def power_brute(values, k):
    result = 0
    for left in range(len(values)):
        total = 0
        for right in range(left, len(values)):
            total += values[right]
            result = (result + pow(total, k, MOD)) % MOD
    return result


def power_moments(values, k):
    """Independent algebraic check using prefix-power moments."""
    import math
    moments = [1] + [0]*k
    coefficients = [math.comb(k, j) * (-1 if j % 2 else 1) for j in range(k+1)]
    prefix = answer = 0
    for value in values:
        prefix = (prefix + value) % MOD
        powers = [1]
        for _ in range(k):
            powers.append(powers[-1] * prefix % MOD)
        answer = (answer + sum(coefficients[j] * powers[k-j] * moments[j] for j in range(k+1))) % MOD
        for j in range(k+1):
            moments[j] = (moments[j] + powers[j]) % MOD
    return answer


def constant_power(n, k, value):
    return sum((n-length+1) * pow(length*value, k, MOD) for length in range(1, n+1)) % MOD


def sort_cost(permutation):
    """Move the largest remaining value right; evaluate ranks with a Fenwick tree."""
    n = len(permutation)
    positions = [0]*(n+1)
    for index, value in enumerate(permutation, 1):
        positions[value] = index
    tree = [0] + [i & -i for i in range(1, n+1)]
    answer = 0
    for value in range(n, 1, -1):
        index = positions[value]
        rank = 0
        while index:
            rank += tree[index]
            index -= index & -index
        answer += value*(value-1)//2 - rank*(rank-1)//2
        index = positions[value]
        while index <= n:
            tree[index] -= 1
            index += index & -index
    return answer


@lru_cache(maxsize=None)
def sort_distances(n):
    """Independent literal weighted-state shortest paths; all n! states."""
    start = tuple(range(1, n+1))
    distances = {start: 0}
    heap = [(0, start)]
    while heap:
        distance, state = heapq.heappop(heap)
        if distance != distances[state]:
            continue
        for i in range(n-1):
            other = list(state)
            other[i], other[i+1] = other[i+1], other[i]
            other = tuple(other)
            candidate = distance+i+1
            if candidate < distances.get(other, float('inf')):
                distances[other] = candidate
                heapq.heappush(heap, (candidate, other))
    return distances


def bit_neighbors(source, x, y):
    a, b = '0'*x+'1'*y, '1'*y+'0'*x
    for index in range(len(source)-x-y+1):
        piece = source[index:index+x+y]
        if piece == a:
            yield source[:index]+b+source[index+x+y:]
        elif piece == b:
            yield source[:index]+a+source[index+x+y:]


def bit_reachable(source, x, y):
    visited = {source}
    queue = deque([source])
    while queue:
        for other in bit_neighbors(queue.popleft(), x, y):
            if other not in visited:
                visited.add(other)
                queue.append(other)
    return visited


@lru_cache(maxsize=1)
def validate_oracles():
    fine_checks = 0
    for n in range(1, 15):
        for missing in [None, *range(1, n+1)]:
            values = [v for v in range(1, n+1) if v != missing]
            if interval_triplets(n, missing) != fine_brute(values):
                raise ValueError('Fine-triplet formula failed definition oracle')
            fine_checks += 1
    power_checks = 0
    for n in range(1, 5):
        for values in itertools.product((0, 1, MOD-1), repeat=n):
            for k in (1, 2, 3, 10):
                if power_brute(values, k) != power_moments(values, k):
                    raise ValueError('Power moments failed exhaustive oracle')
                power_checks += 1
    for n in range(1, 12):
        for k in (1, 2, 9, 10):
            for value in (0, 1, MOD-1):
                if constant_power(n, k, value) != power_brute([value]*n, k):
                    raise ValueError('Constant-power formula failed oracle')
    sorting_checks = 0
    for n in range(2, 7):
        for permutation, expected in sort_distances(n).items():
            if sort_cost(permutation) != expected:
                raise ValueError('Sorting formula disagrees with Dijkstra')
            sorting_checks += 1
    # All binary states and all legal X,Y through N=5. Check undirected edges
    # and literal-operation invariants; large formulas follow these invariants.
    bit_checks = 0
    for n in range(1, 6):
        for x in range(1, n+1):
            for y in range(1, n+1):
                for bits in itertools.product('01', repeat=n):
                    source = ''.join(bits)
                    for target in bit_neighbors(source, x, y):
                        if source not in set(bit_neighbors(target, x, y)) or source.count('1') != target.count('1'):
                            raise ValueError('Literal bit-operation validation failed')
                    if x == y == 1:
                        if len(bit_reachable(source, x, y)) != sum(''.join(t).count('1') == source.count('1') for t in itertools.product('01', repeat=n)):
                            raise ValueError('Adjacent-swap characterization failed')
                    bit_checks += 1
    return dict(fine_formula_definition_comparisons=fine_checks,
                power_exhaustive_comparisons=power_checks,
                weighted_sort_dijkstra_states=sorting_checks,
                bit_operation_state_parameter_checks=bit_checks)


def _case(label, input_text, output):
    return dict(label=label, input=input_text.rstrip()+'\n', output=str(output).strip()+'\n')


def _array_input(values, first=None):
    return (str(len(values)) if first is None else first)+'\n'+' '.join(map(str, values))+'\n'


def _extra_cases(task_id):
    cases = []
    def add(label, text, output):
        cases.append(_case(label, text, output))
    if task_id == 'abc392_g':
        small = [[1], [1, 1000000], [1, 2, 3], [1, 3, 5, 7, 9],
                 [8, 2, 7, 1, 10, 5], [999996, 999998, 1000000],
                 [1, 2, 4, 8, 16, 32, 64], [1, 4, 5, 6, 8, 9, 12]]
        for i, values in enumerate(small):
            add(f'brute-triples-{i}', _array_input(values), fine_brute(values))
        n = 1_000_000
        add('stress-million-contiguous', _array_input(range(1, n+1)), interval_triplets(n))
        missing = n//2
        values = [v for v in range(1, n+1) if v != missing]
        add('stress-million-missing-middle', _array_input(values), interval_triplets(n, missing))
        add('stress-half-million-even-progression', _array_input(range(2, n+1, 2)), interval_triplets(n//2))
    elif task_id == 'abc399_f':
        small = [([0, 0, 0], 10), ([MOD-1], 9), ([MOD-1, 1, MOD-1, 1], 10),
                 ([1, 2, 3, 4], 1), ([0, MOD-1, 2, 0, 1], 7),
                 ([2, 5, 0, 9, 1, 0], 10), ([MOD-1, MOD-1, MOD-1], 3)]
        for i, (values, k) in enumerate(small):
            add(f'brute-subarrays-{i}', _array_input(values, f'{len(values)} {k}'), power_brute(values, k))
        n = 200_000
        for value, k, label in [(1, 10, 'ones-k10'), (MOD-1, 9, 'minus-one-k9')]:
            add('stress-'+label, _array_input([value]*n, f'{n} {k}'), constant_power(n, k, value))
        # Alternating +1,-1: nonzero sums occur only at odd lengths. For even K
        # every such interval contributes one, independently of its sign.
        add('stress-alternating-sign-k10', _array_input([1, MOD-1]*(n//2), f'{n} 10'), ((n+1)//2)*((n+2)//2) % MOD)
        values = [0]*n
        values[n//2] = MOD-1
        add('stress-one-interior-impulse', _array_input(values, f'{n} 10'), ((n//2+1)*(n-n//2)) % MOD)
    elif task_id == 'arc194_b':
        rng = random.Random(194)
        for i in range(7):
            values = list(range(1, 7))
            rng.shuffle(values)
            add(f'dijkstra-permutation-{i}', _array_input(values), sort_distances(6)[tuple(values)])
        n = 200_000
        add('stress-reverse', _array_input(range(n, 0, -1)), n*(n*n-1)//6)
        add('stress-left-rotation', _array_input([*range(2, n+1), 1]), n*(n-1)//2)
        add('stress-right-rotation', _array_input([n, *range(1, n)]), n*(n-1)//2)
        values = list(range(1, n+1))
        for i in range(0, n, 2):
            values[i], values[i+1] = values[i+1], values[i]
        add('stress-disjoint-neighbor-swaps', _array_input(values), (n//2)**2)
    else:
        # These fixtures include same-popcount but unreachable pairs.
        small = [('001100', '110000', 2, 2), ('010101', '101010', 2, 2),
                 ('001011', '110010', 2, 1), ('000111', '111000', 3, 3),
                 ('010010', '001010', 2, 1), ('110100', '001011', 1, 2),
                 ('0010101', '1010100', 3, 2), ('1010010', '0101010', 1, 3)]
        for i, (source, target, x, y) in enumerate(small):
            answer = 'Yes' if target in bit_reachable(source, x, y) else 'No'
            add(f'bfs-reachability-{i}', f'{len(source)} {x} {y}\n{source}\n{target}', answer)
        n = 500_000
        source, target = '0'*(n//2)+'1'*(n//2), '10'*(n//2)
        add('stress-adjacent-swaps', f'{n} 1 1\n{source}\n{target}', 'Yes')
        add('stress-frozen-different', f'{n} {n} 1\n{source}\n{target}', 'No')
        add('stress-frozen-identical', f'{n} {n} {n}\n{source}\n{source}', 'Yes')
        x, y = 200_000, 300_000
        source, target = '0'*x+'1'*y, '1'*y+'0'*x
        add('stress-one-whole-block-swap', f'{n} {x} {y}\n{source}\n{target}', 'Yes')
        target = '0'+target[1:]
        add('stress-one-count-impossible', f'{n} {x} {y}\n{source}\n{target}', 'No')
        source, target = '01'*(n//2), '10'*(n//2)
        add('stress-no-legal-move-equal-count', f'{n} 2 3\n{source}\n{target}', 'No')
    return cases


def _valid_input(task_id, text):
    try:
        tokens = text.split()
        if task_id == 'arc194_e':
            if len(tokens) != 5:
                raise ValueError('Bit case arity')
            n, x, y = map(int, tokens[:3])
            source, target = tokens[3:]
            valid = 1 <= n <= 500_000 and 1 <= x <= n and 1 <= y <= n and len(source) == len(target) == n and set(source+target) <= {'0', '1'}
        else:
            values = list(map(int, tokens))
            n = values[0]
            offset = 2 if task_id == 'abc399_f' else 1
            array = values[offset:]
            valid = len(array) == n
            if task_id == 'abc392_g':
                valid &= 1 <= n <= 1_000_000 and len(set(array)) == n and all(1 <= v <= 1_000_000 for v in array)
            elif task_id == 'abc399_f':
                valid &= 1 <= n <= 200_000 and 1 <= values[1] <= 10 and all(0 <= v < MOD for v in array)
            else:
                valid &= 2 <= n <= 200_000 and len(set(array)) == n and all(1 <= v <= n for v in array)
        if not valid:
            raise ValueError('Fixture violates public constraints')
    except (IndexError, TypeError) as exc:
        raise ValueError('Malformed fixture input') from exc


def build_cases(task):
    task_id = _check_task(task)
    evidence = validate_oracles()
    cases = [_case(f'sample-{i+1}', e['input'], e['output']) for i, e in enumerate(task['examples'])]
    cases.extend(_extra_cases(task_id))
    for case in cases:
        _valid_input(task_id, case['input'])
    # Samples also have independent definition checks, not merely copied output.
    for case in cases[:len(task['examples'])]:
        tokens = case['input'].split()
        if task_id == 'abc392_g':
            expected = fine_brute(list(map(int, tokens[1:])))
        elif task_id == 'abc399_f':
            expected = power_brute(list(map(int, tokens[2:])), int(tokens[1]))
        elif task_id == 'arc194_b':
            expected = sort_distances(int(tokens[0]))[tuple(map(int, tokens[1:]))]
        else:
            expected = 'Yes' if tokens[4] in bit_reachable(tokens[3], int(tokens[1]), int(tokens[2])) else 'No'
        if str(expected) != case['output'].strip():
            raise ValueError('Sample output disagrees with independent oracle')
    return dict(cases=cases, validation_evidence={
        **evidence, 'public_snapshot_sha256': PUBLIC_HASHES[task_id],
        'fixture_count': len(cases), 'constraints_validated': True,
        'large_case_method': {
            'abc392_g': 'Gap count sum; subtract disjoint missing-as-first/middle/last triplets; affine progression preserves equality.',
            'abc399_f': 'Length multiplicity for constants; parity count for alternating signs; interval count covering single impulse.',
            'arc194_b': 'Reverse triangular sum; one-element rotations cross each boundary once; disjoint swaps cross odd boundaries once.',
            'arc194_e': 'Literal BFS small; adjacent swaps preserve and suffice for popcount; oversized window freezes; one literal block swap; popcount/no-move obstructions.',
        }[task_id],
        'role': 'development_only; generated public diagnostics, not independent improvement evidence',
    })


def verify_cases(task, cases):
    expected = build_cases(task)['cases']
    if cases != expected:
        raise ValueError('Cases differ from canonical reviewed fixtures or expected outputs')
    return True


def bit_normal_form(source, x, y):
    """Correct but not generally fast witness for public resource preflight.

    Orient 0^X1^Y -> 1^Y0^X: each rewrite reduces the number of 0-before-1
    pairs by X*Y. A redex has no proper self-overlap, so simultaneous redexes
    are disjoint and commute. Termination plus local confluence gives a unique
    normal form, invariant under either allowed operation.
    """
    if x == y == 1:
        count = source.count('1')
        return '1'*count+'0'*(len(source)-count)
    if x+y > len(source):
        return source
    pattern, replacement = '0'*x+'1'*y, '1'*y+'0'*x
    while True:
        index = source.find(pattern)
        if index < 0:
            return source
        source = source[:index]+replacement+source[index+x+y:]


def reference_source(task_id):
    """Standalone correct witness for all registered fixture resource checks.

    Fine-triplet fallback is quadratic; bit normal form can take many rewrites.
    These are NOT general worst-case performance-certified contest solutions.
    """
    import inspect
    if task_id == 'abc392_g':
        return inspect.getsource(interval_triplets) + '''
import sys
raw = list(map(int, sys.stdin.buffer.read().split()))
a = sorted(raw[1:])
n = len(a)
if n <= 2:
    print(0)
elif all(a[i]-a[i-1] == a[1]-a[0] for i in range(2, n)):
    print(interval_triplets(n))
elif a[-1]-a[0]+1 == n+1:
    span = n+1
    missing = (a[0]+a[-1])*span//2-sum(a)
    print(interval_triplets(span, missing-a[0]+1))
else:
    values = set(a)
    answer = 0
    for i, left in enumerate(a):
        for middle in a[i+1:]:
            answer += 2*middle-left in values
    print(answer)
'''
    if task_id == 'abc399_f':
        return f'MOD = {MOD}\n' + inspect.getsource(power_moments) + '''
import sys
raw = list(map(int, sys.stdin.buffer.read().split()))
print(power_moments(raw[2:], raw[1]))
'''
    if task_id == 'arc194_b':
        return inspect.getsource(sort_cost) + '''
import sys
raw = list(map(int, sys.stdin.buffer.read().split()))
print(sort_cost(raw[1:]))
'''
    if task_id == 'arc194_e':
        return inspect.getsource(bit_normal_form) + '''
import sys
raw = sys.stdin.buffer.read().decode().split()
n, x, y = map(int, raw[:3])
print('Yes' if bit_normal_form(raw[3], x, y) == bit_normal_form(raw[4], x, y) else 'No')
'''
    raise ValueError('Unknown task')
