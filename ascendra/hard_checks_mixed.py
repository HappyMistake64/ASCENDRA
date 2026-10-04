"""Public-only hard development fixtures; exact small oracles and proved families.

The graph-game and interdiction oracles are deliberately bounded. Large cases
belong to explicitly proved families, not a purported general reference solver.
"""
from collections import Counter, deque
from functools import lru_cache
import itertools
import json
import random

TASK_IDS = ("abc398_g", "abc397_g", "abc399_e", "abc390_e")


def validate_input(task_id, raw):
    """Parse and enforce all relevant public domain restrictions."""
    try:
        if task_id == "abc399_e":
            parts = raw.split()
            if len(parts) != 3:
                raise ValueError("Expected N, S, T")
            n, s, t = int(parts[0]), parts[1], parts[2]
            if not 1 <= n <= 200000 or len(s) != n or len(t) != n or any(not "a" <= x <= "z" for x in s+t):
                raise ValueError("Invalid replacement input")
            return n, s, t
        nums = list(map(int, raw.split()))
        if task_id == "abc390_e":
            n, budget = nums[:2]
            if not 1 <= n <= 5000 or not 1 <= budget <= 5000 or len(nums) != 2+3*n:
                raise ValueError("Invalid food dimensions")
            foods = [tuple(nums[i:i+3]) for i in range(2, len(nums), 3)]
            if any(not (1 <= v <= 3 and 1 <= a <= 200000 and 1 <= c <= budget) for v,a,c in foods):
                raise ValueError("Invalid food")
            return n, budget, foods
        if task_id == "abc397_g":
            n, m, k = nums[:3]
            if not 2 <= n <= 30 or not 1 <= k <= m <= 100 or len(nums) != 3+2*m:
                raise ValueError("Invalid interdiction dimensions")
            edges = [tuple(nums[i:i+2]) for i in range(3, len(nums), 2)]
            if any(not (1 <= u <= n and 1 <= v <= n and u != v) for u,v in edges):
                raise ValueError("Invalid directed edge")
            reached = {1}
            for _ in range(n):
                reached.update(v for u,v in edges if u in reached)
            if n not in reached:
                raise ValueError("Destination not reachable")
            return n, k, edges
        if task_id == "abc398_g":
            n, m = nums[:2]
            if not 1 <= n <= 200000 or not 0 <= m <= 200000 or len(nums) != 2+2*m:
                raise ValueError("Invalid graph game dimensions")
            edges = [tuple(nums[i:i+2]) for i in range(2, len(nums), 2)]
            if any(not 1 <= u < v <= n for u,v in edges) or len(set(edges)) != m:
                raise ValueError("Invalid simple graph")
            if _bipartition(n, edges) is None:
                raise ValueError("Odd cycle is forbidden")
            return n, edges
    except (TypeError, IndexError) as exc:
        raise ValueError("Malformed public fixture") from exc
    raise ValueError("Unsupported task")


def _bipartition(n, edges):
    adjacency = [[] for _ in range(n)]
    for u,v in edges:
        adjacency[u-1].append(v-1); adjacency[v-1].append(u-1)
    color = [-1]*n
    components = []
    for start in range(n):
        if color[start] != -1:
            continue
        color[start] = 0; stack = [start]; counts = [1, 0]
        while stack:
            u = stack.pop()
            for v in adjacency[u]:
                if color[v] == -1:
                    color[v] = 1-color[u]; counts[color[v]] += 1; stack.append(v)
                elif color[v] == color[u]:
                    return None
        components.append(tuple(counts))
    return components


@lru_cache(maxsize=None)
def _game_solver(n):
    if not 1 <= n <= 6:
        raise ValueError("Exact game oracle restricted to N <= 6")
    pairs = tuple(itertools.combinations(range(1, n+1), 2))

    @lru_cache(maxsize=None)
    def valid(mask):
        return _bipartition(n, [edge for i,edge in enumerate(pairs) if mask >> i & 1]) is not None

    @lru_cache(maxsize=None)
    def winning(mask):
        for i in range(len(pairs)):
            nxt = mask | (1 << i)
            if nxt != mask and valid(nxt) and not winning(nxt):
                return True
        return False
    return pairs, winning


def game_exact(n, edges):
    pairs, winning = _game_solver(n)
    included = set(edges)
    mask = sum(1 << i for i,e in enumerate(pairs) if e in included)
    return "Aoki" if winning(mask) else "Takahashi"


def game_fixed_parity(n, edges):
    """Proved terminal-edge parity for three restricted graph families."""
    parts = _bipartition(n, edges)
    if parts is None:
        raise ValueError("Invalid graph")
    if n % 2:
        terminal_parity = 0  # a*(n-a) always even for odd n.
    elif len(parts) == 1:
        terminal_parity = parts[0][0]*parts[0][1] % 2
    elif all(a == b for a,b in parts):
        terminal_parity = (n//2)**2 % 2
    else:
        raise ValueError("No fixed-parity proof for this family")
    return "Aoki" if (terminal_parity-len(edges)) % 2 else "Takahashi"


def _distance(n, edges, selected):
    distances = [n+1]*n; distances[0] = 0
    for _ in range(n-1):
        changed = False
        for i,(u,v) in enumerate(edges):
            d = distances[u-1] + int(i in selected)
            if d < distances[v-1]:
                distances[v-1] = d; changed = True
        if not changed:
            break
    return distances[-1]


def interdiction_exact(n, k, edges):
    if len(edges) > 13:
        raise ValueError("Subset oracle restricted to M <= 13")
    return max(_distance(n, edges, set(chosen)) for chosen in itertools.combinations(range(len(edges)), k))


def replacement_exact(s, t):
    """Literal operation BFS on equivalence classes, with one spare symbol.

    All positions originally sharing a letter remain equal forever. Compressing
    these classes is exact. At most one unused temporary name is needed: two
    temporary classes never need the same name unless they are to merge.
    """
    mapping = {}
    for a,b in zip(s,t):
        if a in mapping and mapping[a] != b:
            return -1
        mapping[a] = b
    if s == t:
        return 0
    if len(mapping) > 5:
        raise ValueError("Replacement BFS restricted to five source classes")
    source = tuple(sorted(mapping)); target = tuple(mapping[a] for a in source)
    alphabet = set(source) | set(target)
    spare = next((chr(i) for i in range(97,123) if chr(i) not in alphabet), None)
    if spare:
        alphabet.add(spare)
    queue = deque([(source, 0)]); seen = {source}
    while queue:
        state, depth = queue.popleft()
        for a in set(state):
            for b in sorted(alphabet):
                if a == b:
                    continue
                nxt = tuple(b if x == a else x for x in state)
                if nxt == target:
                    return depth+1
                if nxt not in seen:
                    seen.add(nxt); queue.append((nxt,depth+1))
    return -1


def vitamins_exact(budget, foods):
    if len(foods) > 16:
        raise ValueError("Subset oracle restricted to N <= 16")
    answer = 0
    for mask in range(1 << len(foods)):
        totals = [0,0,0]; cost = 0
        for i,(vitamin,amount,calories) in enumerate(foods):
            if mask >> i & 1:
                cost += calories; totals[vitamin-1] += amount
        if cost <= budget:
            answer = max(answer, min(totals))
    return answer


def vitamins_dp(budget, foods):
    tables = [[0]*(budget+1) for _ in range(3)]
    for v,a,c in foods:
        table = tables[v-1]
        for b in range(budget,c-1,-1):
            table[b] = max(table[b],table[b-c]+a)
    return max(min(tables[0][a],tables[1][b],tables[2][budget-a-b])
               for a in range(budget+1) for b in range(budget-a+1))


def _graph_text(n, edges, k=None):
    head = f"{n} {len(edges)}" + (f" {k}" if k is not None else "")
    return head+"\n"+"".join(f"{u} {v}\n" for u,v in edges)


def _food_text(budget, foods):
    return f"{len(foods)} {budget}\n"+"".join(f"{v} {a} {c}\n" for v,a,c in foods)


def _replacement_text(s,t):
    return f"{len(s)}\n{s}\n{t}\n"


def build_cases(task):
    task_id = task["task_id"]
    if task_id not in TASK_IDS:
        raise ValueError("Unsupported task")
    cases = [{"input":c["input"], "output":c["output"], "label":f"public-example-{i+1}"}
             for i,c in enumerate(task["examples"])]
    rng = random.Random(20261004+TASK_IDS.index(task_id))
    proofs = []

    def add(raw, expected, label):
        validate_input(task_id, raw)
        cases.append({"input":raw,"output":str(expected)+"\n","label":label})

    if task_id == "abc398_g":
        for i in range(8):
            n = 2+i%5
            sides = [rng.randrange(2) for _ in range(n)]
            edges = [(u+1,v+1) for u in range(n) for v in range(u+1,n)
                     if sides[u] != sides[v] and rng.randrange(2)]
            add(_graph_text(n,edges),game_exact(n,edges),f"exact-game-{i}")
        families = [
            (1, [], "single-vertex"),
            (200000, [(i,i+1) for i in range(1,200000)], "maximum-connected-path"),
            (200000, [(1,i) for i in range(2,200001)], "maximum-connected-star"),
            (200000, [(i,i+1) for i in range(1,200000,2)], "maximum-balanced-components"),
            (199999, [(i,i+1) for i in range(1,199998,2)], "odd-order-components"),
            (199999, [], "odd-order-empty"),
        ]
        for n,edges,label in families:
            add(_graph_text(n,edges),game_fixed_parity(n,edges),label)
        proofs = ["Exact legal-move minimax for small N <= 6; each move independently checks bipartiteness.",
                  "Every terminal graph is complete bipartite: disconnected components can always be joined.",
                  "Connected initial graphs fix partition sizes. Balanced components fix global equal partition sizes.",
                  "For odd N every terminal complete bipartite graph has even edge count, so initial edge parity fixes winner."]
    elif task_id == "abc397_g":
        for i in range(8):
            n = 2+i%5
            edges = [(v,v+1) for v in range(1,n)]
            for _ in range(3):
                u,v = rng.sample(range(1,n+1),2); edges.append((u,v))
            k = rng.randint(1,len(edges))
            add(_graph_text(n,edges,k),interdiction_exact(n,k,edges),f"exact-edge-subsets-{i}")
        for i,(widths,k) in enumerate([([100],99),([100],100),([3]*29,43),([3]*29,86),([1,2,3,4,5]*5,37)]):
            edges = [(stage+1,stage+2) for stage,width in enumerate(widths) for _ in range(width)]
            used = 0; answer = 0
            for width in sorted(widths):
                if used+width > k:
                    break
                used += width; answer += 1
            add(_graph_text(len(widths)+1,edges,k),answer,f"parallel-stage-family-{i}")
        edges = [(i,i+1) for i in range(1,30)]
        while len(edges) < 100:
            edges.append(tuple(rng.sample(range(1,31),2)))
        add(_graph_text(30,edges,100),_distance(30,edges,set(range(100))),"all-edges-weight-one")
        proofs = ["Small oracle enumerates every choice of exactly K edge indices, preserving parallel edges, then Bellman-Ford computes shortest distance.",
                  "In a chain of parallel-edge stages, a stage contributes one iff all its edges are selected; optimal completed stages are the cheapest widths. Leftover selections cannot reduce the optimum.",
                  "When K=M every edge has weight one and ordinary hop distance is exact."]
    elif task_id == "abc399_e":
        small = [("ab","ba"),("abc","baa"),("abc","bca"),("abc","bbb"),
                 ("abcd","badc"),("abca","bcab"),("aba","abc"),("abc","bcd")]
        for i,(s,t) in enumerate(small):
            add(_replacement_text(s,t),replacement_exact(s,t),f"literal-replacement-bfs-{i}")
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        families = [
            ("a"*200000,"a"*200000,0,"maximum-identity"),
            ("a"*200000,"b"*200000,1,"maximum-single-rename"),
            (("ab"*100000),("ba"*100000),3,"maximum-swap-needs-spare"),
            (alphabet*7692, (alphabet[1:]+alphabet[0])*7692,-1,"all-alphabet-permutation-impossible"),
            (alphabet[:25]*8000, (alphabet[1:25]+alphabet[0])*8000,26,"twenty-five-cycle-one-spare"),
            ("a"*200000,"a"*199999+"b",-1,"maximum-inconsistent-map"),
        ]
        for s,t,answer,label in families:
            add(_replacement_text(s,t),answer,label)
        proofs = ["Small oracle performs BFS over literal global replacements on source-letter equivalence classes, with an available spare letter.",
                  "A pure nontrivial permutation cycle of length L with one spare costs L+1: one temporary save plus L final placements; fixed labels cost zero.",
                  "A nonidentity permutation of all 26 present letters is impossible: the first nontrivial replacement irreversibly merges two required distinct classes.",
                  "Two positions with the same initial letter cannot ever acquire different final letters."]
    else:
        for i in range(8):
            budget = rng.randint(1,22)
            foods = [(rng.randint(1,3),rng.randint(1,40),rng.randint(1,budget)) for _ in range(4+i%7)]
            answer = vitamins_exact(budget,foods)
            if answer != vitamins_dp(budget,foods):
                raise ValueError("Independent vitamin oracles disagree")
            add(_food_text(budget,foods),answer,f"subset-vs-budget-dp-{i}")
        families = [
            (5000,[(1,200000,1)]*5000,0,"maximum-missing-vitamins"),
            (5000,[(1,200000,1)]*1666+[(2,200000,1)]*1667+[(3,200000,1)]*1667,333200000,"maximum-eat-all"),
            (4999,[(1,200000,1)]*1666+[(2,200000,1)]*1667+[(3,200000,1)]*1667,333200000,"maximum-one-calorie-short"),
            (5000,[(1,200000,5000),(2,200000,5000),(3,200000,5000)],0,"only-one-food-affordable"),
            (5000,[(1,1,1)]*4998+[(2,200000,1),(3,200000,1)],4998,"unequal-vitamin-bottleneck"),
            (5000,[(1,200000,1666),(2,200000,1667),(3,200000,1667)],200000,"exact-budget-three-foods"),
        ]
        for budget,foods,answer,label in families:
            add(_food_text(budget,foods),answer,label)
        proofs = ["Small subset enumeration independently agrees with per-vitamin 0/1 knapsack and exhaustive budget allocation.",
                  "Equal amount/calorie homogeneous groups: the least selected group count bounds and achieves the objective.",
                  "Missing vitamin gives zero; three indispensable foods either fit the exact budget or cannot all be selected."]
    if len(cases) > 18 or len({c["label"] for c in cases}) != len(cases):
        raise ValueError("Fixture count/label contract violated")
    for case in cases:
        validate_input(task_id,case["input"])
    return {"cases":cases,"validation_evidence":{
        "public_examples_authority":"Expected outputs copied verbatim from supplied public statement examples; not reverse-engineered from private cases.",
        "custom_oracles":proofs,"deterministic_seed":20261004+TASK_IDS.index(task_id),
        "limits":"Large cases certify only their proved families; no general large-instance exact reference is claimed. Passing finite diagnostics does not establish correctness.",
        "private_cases_accessed":False,"case_count":len(cases),
    }}


def verify_cases(task,cases):
    if not isinstance(cases,list) or cases != build_cases(task)["cases"]:
        raise ValueError("Cases differ from canonical independently checked fixtures")
    return True
