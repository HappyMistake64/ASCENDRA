"""Independent input-domain review of the hard-development public controls.

These checks inspect generated/public data only, never dataset private cases.
"""
import importlib
import json
from pathlib import Path
from collections import deque
from functools import lru_cache
import heapq
import itertools
import unittest


MODULES = ('hard_checks_math', 'hard_checks_graphs', 'hard_checks_mixed')


def domain_check(task_id, text):
    tokens = text.split()
    offset = 0
    def integer():
        nonlocal offset
        result = int(tokens[offset]); offset += 1
        return result
    def word():
        nonlocal offset
        result = tokens[offset]; offset += 1
        return result
    def bounded(low, high):
        value = integer()
        assert low <= value <= high, (task_id, value, low, high)
        return value
    if task_id == 'abc392_g':
        n = bounded(1, 10**6)
        values = [bounded(1, 10**6) for _ in range(n)]
        assert len(set(values)) == n
    elif task_id == 'abc399_f':
        n = bounded(1, 200000); bounded(1, 10)
        for _ in range(n): bounded(0, 998244352)
    elif task_id == 'arc194_b':
        n = bounded(2, 200000)
        assert set(integer() for _ in range(n)) == set(range(1, n+1))
    elif task_id == 'arc194_e':
        n = bounded(1, 500000); bounded(1, n); bounded(1, n)
        for _ in range(2):
            value = word()
            assert len(value) == n and set(value) <= {'0', '1'}
    elif task_id == 'abc394_e':
        n = bounded(1, 100)
        for _ in range(n):
            value = word()
            assert len(value) == n and set(value) <= set('-abcdefghijklmnopqrstuvwxyz')
    elif task_id == 'abc394_g':
        h = bounded(1, 500); w = bounded(1, 500)
        floors = [bounded(1, 1000000) for _ in range(h*w)]
        q = bounded(1, 200000)
        for _ in range(q):
            a = bounded(1, h); b = bounded(1, w); y = bounded(1, floors[(a-1)*w+b-1])
            c = bounded(1, h); d = bounded(1, w); z = bounded(1, floors[(c-1)*w+d-1])
            assert (a, b, y) != (c, d, z)
    elif task_id in ('abc395_e', 'abc397_g', 'abc398_g', 'abc394_f'):
        n = bounded(1 if task_id in ('abc398_g', 'abc394_f') else 2,
                    30 if task_id == 'abc397_g' else 200000)
        m = n-1 if task_id == 'abc394_f' else bounded(0 if task_id == 'abc398_g' else 1,
                                                                    100 if task_id == 'abc397_g' else 200000)
        if task_id == 'abc395_e': bounded(1, 10**9)
        if task_id == 'abc397_g': bounded(1, m)
        adjacency = [[] for _ in range(n)]
        directed = [[] for _ in range(n)]
        edges = set()
        for _ in range(m):
            u = bounded(1, n)-1; v = bounded(1, n)-1
            if task_id in ('abc397_g', 'abc394_f'): assert u != v
            if task_id == 'abc398_g':
                assert u < v and (u, v) not in edges
            edges.add((u, v))
            adjacency[u].append(v); adjacency[v].append(u); directed[u].append(v)
        colors = {}
        for start in range(n):
            if start in colors: continue
            if task_id == 'abc394_f': assert start == 0, 'disconnected tree'
            queue = [start]; colors[start] = 0
            for u in queue:
                for v in adjacency[u]:
                    if v not in colors:
                        colors[v] = 1-colors[u]; queue.append(v)
                    elif task_id == 'abc398_g': assert colors[u] != colors[v]
            if start == 0 and task_id == 'abc395_e': assert n-1 in queue
        if task_id == 'abc397_g':
            seen = {0}; queue = [0]
            for u in queue:
                for v in directed[u]:
                    if v not in seen: seen.add(v); queue.append(v)
            assert n-1 in seen
    elif task_id == 'abc399_e':
        n = bounded(1, 200000)
        for _ in range(2):
            value = word()
            assert len(value) == n and set(value) <= set('abcdefghijklmnopqrstuvwxyz')
    elif task_id == 'abc390_e':
        n = bounded(1, 5000); x = bounded(1, 5000)
        for _ in range(n): bounded(1, 3); bounded(1, 200000); bounded(1, x)
    else:
        raise AssertionError('Unreviewed public contract: ' + task_id)
    assert offset == len(tokens), (task_id, 'unexpected trailing input')


@lru_cache(None)
def permutation_costs(n):
    start = tuple(range(1, n+1)); costs = {start: 0}; heap = [(0, start)]
    while heap:
        distance, state = heapq.heappop(heap)
        if distance != costs[state]: continue
        for i in range(n-1):
            other = list(state); other[i], other[i+1] = other[i+1], other[i]; other = tuple(other)
            cost = distance+i+1
            if cost < costs.get(other, 10**9):
                costs[other] = cost; heapq.heappush(heap, (cost, other))
    return costs


def independent_small_answer(task_id, text):
    words = text.split(); n = int(words[0])
    if task_id == 'abc392_g' and n <= 40:
        values = sorted(map(int, words[1:]))
        return str(sum(a+c == 2*b for a, b, c in itertools.combinations(values, 3)))
    if task_id == 'abc399_f' and n <= 40:
        k = int(words[1]); values = list(map(int, words[2:])); answer = 0
        for left in range(n):
            total = 0
            for right in range(left, n):
                total += values[right]; answer += pow(total, k, 998244353)
        return str(answer % 998244353)
    if task_id == 'arc194_b' and n <= 7:
        return str(permutation_costs(n)[tuple(map(int, words[1:]))])
    if task_id == 'arc194_e' and n <= 9:
        x, y = map(int, words[1:3]); source, target = words[3:5]
        a, b = '0'*x+'1'*y, '1'*y+'0'*x
        seen = {source}; queue = [source]
        for state in queue:
            for i in range(n-x-y+1):
                chunk = state[i:i+x+y]
                if chunk not in (a, b): continue
                other = state[:i] + (b if chunk == a else a) + state[i+x+y:]
                if other not in seen: seen.add(other); queue.append(other)
        return 'Yes' if target in seen else 'No'
    if task_id == 'abc394_e' and n <= 3:
        rows = words[1:]; alphabet = sorted(set(''.join(rows))-{'-'})
        answers = [[0 if a == b else -1 for b in range(n)] for a in range(n)]
        # Enumerate literal palindrome words, not product-graph transitions.
        # A shortest center-expansion path has at most N^2 distinct pair states.
        for length in range(1, 2*n*n):
            for half in itertools.product(alphabet, repeat=(length+1)//2):
                word = half + (half[:-1] if length % 2 else half)[::-1]
                for start in range(n):
                    positions = {start}
                    for char in word:
                        positions = {v for u in positions for v in range(n) if rows[u][v] == char}
                        if not positions: break
                    for end in positions:
                        if answers[start][end] < 0: answers[start][end] = length
            if all(value >= 0 for row in answers for value in row): break
        return '\n'.join(' '.join(map(str, row)) for row in answers)
    if task_id == 'abc394_g' and n*int(words[1]) <= 12:
        h, w = map(int, words[:2]); floors = list(map(int, words[2:2+h*w]))
        if max(floors) > 8: return None
        q = int(words[2+h*w]); raw = list(map(int, words[3+h*w:])); answers = []
        for i in range(q):
            a, b, y, c, d, z = raw[6*i:6*i+6]
            start = ((a-1)*w+b-1, y); target = ((c-1)*w+d-1, z)
            distance = {start: 0}; heap = [(0, start)]
            while heap:
                cost, position = heapq.heappop(heap)
                if distance[position] != cost: continue
                if position == target: answers.append(cost); break
                block, floor = position; row, column = divmod(block, w)
                choices = []
                for otherfloor in (floor-1, floor+1):
                    if 1 <= otherfloor <= floors[block]: choices.append(((block, otherfloor), 1))
                for r, c in ((row-1,column), (row+1,column), (row,column-1), (row,column+1)):
                    if 0 <= r < h and 0 <= c < w and floors[r*w+c] >= floor:
                        choices.append(((r*w+c, floor), 0))
                for other, step in choices:
                    if cost+step < distance.get(other, 10**9):
                        distance[other] = cost+step; heapq.heappush(heap, (cost+step, other))
        return '\n'.join(map(str, answers))
    if task_id == 'abc395_e' and n <= 10:
        m, x = map(int, words[1:3]); values = list(map(int, words[3:])); edges = []
        for u, v in zip(values[::2], values[1::2]):
            edges.extend([(u-1, v-1, 1), (v-1+n, u-1+n, 1)])
        for u in range(n): edges.extend([(u, u+n, x), (u+n, u, x)])
        distance = [10**30]*(2*n); distance[0] = 0
        for _ in range(2*n):
            changed = False
            for u, v, w in edges:
                if distance[u]+w < distance[v]: distance[v] = distance[u]+w; changed = True
            if not changed: break
        return str(min(distance[n-1], distance[2*n-1]))
    if task_id == 'abc394_f' and n <= 12:
        raw = list(map(int, words[1:])); edges = list(zip(raw[::2], raw[1::2])); answer = -1
        for mask in range(1, 1 << n):
            degree = [0]*n; count = 0
            for a, b in edges:
                if (mask >> (a-1)) & 1 and (mask >> (b-1)) & 1:
                    degree[a-1] += 1; degree[b-1] += 1; count += 1
            selected = [degree[i] for i in range(n) if (mask >> i) & 1]
            if count == len(selected)-1 and 4 in selected and set(selected) <= {1, 4}:
                answer = max(answer, len(selected))
        return str(answer)
    if task_id == 'abc397_g' and int(words[1]) <= 12 and n <= 10:
        m, k = map(int, words[1:3]); raw = list(map(int, words[3:])); edges = list(zip(raw[::2], raw[1::2])); answer = 0
        for chosen in itertools.combinations(range(m), k):
            chosen = set(chosen); distance = [1000]*n; distance[0] = 0
            for _ in range(n):
                for index, (a, b) in enumerate(edges):
                    distance[b-1] = min(distance[b-1], distance[a-1]+(index in chosen))
            answer = max(answer, distance[-1])
        return str(answer)
    if task_id == 'abc399_e' and n <= 4:
        source, target = words[1:3]
        alphabet = set(source+target)
        alphabet.add(next(c for c in 'abcdefghijklmnopqrstuvwxyz' if c not in alphabet))
        queue = deque([(source, 0)]); seen = {source}
        while queue:
            state, depth = queue.popleft()
            if state == target: return str(depth)
            for a in set(state):
                for b in alphabet-{a}:
                    other = state.replace(a, b)
                    if other not in seen: seen.add(other); queue.append((other, depth+1))
        return '-1'
    if task_id == 'abc390_e' and n <= 16:
        x = int(words[1]); raw = list(map(int, words[2:])); foods = list(zip(raw[::3], raw[1::3], raw[2::3])); answer = 0
        for mask in range(1 << n):
            total = [0, 0, 0]; calories = 0
            for i, (v, a, c) in enumerate(foods):
                if (mask >> i) & 1: total[v-1] += a; calories += c
            if calories <= x: answer = max(answer, min(total))
        return str(answer)
    if task_id == 'abc398_g' and n <= 5:
        raw = list(map(int, words[2:])); given = set((a-1, b-1) for a, b in zip(raw[::2], raw[1::2]))
        edges = list(itertools.combinations(range(n), 2))
        def bipartite(mask):
            adjacency = [[] for _ in range(n)]
            for i, (u, v) in enumerate(edges):
                if (mask >> i) & 1: adjacency[u].append(v); adjacency[v].append(u)
            colors = {}
            for start in range(n):
                if start in colors: continue
                colors[start] = 0; queue = [start]
                for u in queue:
                    for v in adjacency[u]:
                        if v not in colors: colors[v] = 1-colors[u]; queue.append(v)
                        elif colors[v] == colors[u]: return False
            return True
        @lru_cache(None)
        def winning(mask):
            return any(not winning(mask | (1 << i)) for i in range(len(edges))
                       if not (mask >> i) & 1 and bipartite(mask | (1 << i)))
        mask = sum(1 << i for i, edge in enumerate(edges) if edge in given)
        return 'Aoki' if winning(mask) else 'Takahashi'
    return None


class HardInputContractTests(unittest.TestCase):
    def test_every_generated_input_obeys_independent_public_contract(self):
        tasks = {t['task_id']: t for t in json.loads((Path(__file__).parent/'fixtures'/'hard_public_tasks.json').read_text())}
        for module_name in MODULES:
            module = importlib.import_module('ascendra.' + module_name)
            for task_id in module.TASK_IDS:
                bundle = module.build_cases(tasks[task_id])
                self.assertTrue(bundle['cases'])
                for i, case in enumerate(bundle['cases']):
                    with self.subTest(task_id=task_id, case=i):
                        domain_check(task_id, case['input'])
                        self.assertLessEqual(len(case['output'].encode()), 4*1024*1024)
                        expected = independent_small_answer(task_id, case['input'])
                        if expected is not None:
                            self.assertEqual(case['output'].strip(), expected)


if __name__ == '__main__':
    unittest.main()
