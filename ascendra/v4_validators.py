"""Public, deterministic pilot checks. No evaluator-private data is read here.

Each optimized oracle is checked against a structurally different exhaustive or
literal reference on small inputs. This establishes bounded validation evidence,
not a proof of arbitrary program correctness. Unsupported tasks fail closed.
"""
from collections import Counter
from functools import lru_cache
from itertools import combinations, product
from math import isqrt
import hashlib
import json
import random

VERSION = 'ascendra-public-validators-v1'
SUPPORTED_TASKS = ('abc397_b', 'abc388_c', 'abc388_e', 'abc390_c', 'abc391_d',
                   'abc394_d', 'abc397_c', 'abc392_c', 'abc395_c', 'abc398_b',
                   'abc398_c', 'abc400_c')


# Hand-derived truth fixtures supplement the randomized differential checks.
_TRUTH = {
    'abc397_b': ('oi\n', '2\n'),
    'abc388_c': ('4\n1 1 2 2\n', '4\n'),
    'abc388_e': ('4\n1 1 2 2\n', '2\n'),
    'abc390_c': ('1 3\n#.#\n', 'No\n'),
    'abc391_d': ('1 1\n1 2\n2\n1 1\n2 1\n', 'Yes\nNo\n'),
    'abc394_d': ('([)]\n', 'No\n'),
    'abc397_c': ('4\n1 2 1 2\n', '4\n'),
    'abc392_c': ('3\n2 3 1\n2 1 3\n', '3 1 2\n'),
    'abc395_c': ('3\n1 2 1\n', '3\n'),
    'abc398_b': ('1 1 1 1 1 1 1\n', 'No\n'),
    'abc398_c': ('4\n9 2 1 9\n', '2\n'),
    'abc400_c': ('20\n', '5\n'),
}


def _require(ok, message='Input outside public constraints'):
    if not ok:
        raise ValueError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True).encode()).hexdigest()


def _parse(task_id, text):
    _require(task_id in SUPPORTED_TASKS, 'Unsupported public validator: ' + str(task_id))
    _require(isinstance(text, str) and bool(text.strip()))
    words = text.split()
    if task_id in ('abc397_b', 'abc394_d'):
        _require(len(words) == 1)
        value = words[0]
        chars, upper = ('io', 100) if task_id == 'abc397_b' else ('()[]<>', 200000)
        _require(1 <= len(value) <= upper and set(value) <= set(chars))
        return value
    if task_id == 'abc390_c':
        _require(len(words) >= 3)
        h, w = map(int, words[:2]); grid = words[2:]
        _require(1 <= h <= 1000 and 1 <= w <= 1000 and len(grid) == h)
        _require(all(len(row) == w and set(row) <= set('#.?') for row in grid))
        _require(any('#' in row for row in grid), 'Public contract requires a black cell')
        return grid
    try:
        a = [int(word) for word in words]
    except ValueError as exc:
        raise ValueError('Expected integer tokens') from exc
    if task_id == 'abc400_c':
        _require(len(a) == 1 and 1 <= a[0] <= 10**18)
        return a[0]
    if task_id == 'abc398_b':
        _require(len(a) == 7 and all(1 <= x <= 13 for x in a))
        return a
    n = a[0]
    if task_id == 'abc391_d':
        _require(len(a) >= 3 and 1 <= n <= 200000)
        w = a[1]; _require(1 <= w <= n and len(a) >= 3 + 2*n)
        blocks = list(zip(a[2:2+2*n:2], a[3:2+2*n:2]))
        _require(len(set(blocks)) == n and all(1 <= x <= w and 1 <= y <= 10**9 for x,y in blocks))
        q = a[2+2*n]; _require(1 <= q <= 200000 and len(a) == 3+2*n+2*q)
        queries = list(zip(a[3+2*n::2], a[4+2*n::2]))
        _require(all(1 <= t <= 10**9 and 1 <= i <= n for t,i in queries))
        return w, blocks, queries
    if task_id == 'abc392_c':
        _require(2 <= n <= 300000 and len(a) == 1+2*n)
        p, q = a[1:n+1], a[n+1:]
        _require(set(p) == set(range(1,n+1)) and set(q) == set(range(1,n+1)))
        return p, q
    low, high, value_high = {
        'abc388_c': (2,500000,10**9), 'abc388_e': (2,500000,10**9),
        'abc397_c': (2,300000,n), 'abc395_c': (1,200000,10**6),
        'abc398_c': (1,300000,10**9),
    }[task_id]
    _require(low <= n <= high and len(a) == n+1)
    a = a[1:]; _require(all(1 <= x <= value_high for x in a))
    if task_id in ('abc388_c', 'abc388_e'):
        _require(all(x <= y for x,y in zip(a,a[1:])), 'Mochi must be sorted')
    return a


def _fast(task_id, a):
    if task_id == 'abc397_b':
        position = 0
        for char in a:
            if char != 'io'[position % 2]: position += 1
            position += 1
        return position + position % 2 - len(a)
    if task_id == 'abc388_c':
        j = count = 0
        for x in a:
            while j < len(a) and 2*a[j] <= x: j += 1
            count += j
        return count
    if task_id == 'abc388_e':
        i, j = 0, len(a)//2
        while i < len(a)//2 and j < len(a):
            if 2*a[i] <= a[j]: i += 1
            j += 1
        return i
    if task_id == 'abc390_c':
        cells = [(i,j) for i,row in enumerate(a) for j,c in enumerate(row) if c == '#']
        lo_i, hi_i = min(i for i,j in cells), max(i for i,j in cells)
        lo_j, hi_j = min(j for i,j in cells), max(j for i,j in cells)
        return all('.' not in a[i][lo_j:hi_j+1] for i in range(lo_i,hi_i+1))
    if task_id == 'abc391_d':
        w, blocks, queries = a
        columns = [[] for _ in range(w)]
        for i,(x,y) in enumerate(blocks): columns[x-1].append((y,i))
        for col in columns: col.sort()
        disappears = [10**100] * len(blocks)
        for rank in range(min(map(len,columns))):
            at = max(col[rank][0] for col in columns)
            for col in columns: disappears[col[rank][1]] = at
        return [t < disappears[i-1] for t,i in queries]
    if task_id == 'abc394_d':
        stack = []; mates = {')':'(', ']':'[', '>':'<'}
        for c in a:
            if c in '([<': stack.append(c)
            elif not stack or stack.pop() != mates[c]: return False
        return not stack
    if task_id == 'abc397_c':
        right, left = Counter(a), set(); answer = 0
        for x in a[:-1]:
            left.add(x); right[x] -= 1
            if right[x] == 0: del right[x]
            answer = max(answer, len(left)+len(right))
        return answer
    if task_id == 'abc392_c':
        p,q = a; answer = [0]*len(p)
        for i,bib in enumerate(q): answer[bib-1] = q[p[i]-1]
        return answer
    if task_id == 'abc395_c':
        previous = {}; best = len(a)+1
        for i,x in enumerate(a):
            if x in previous: best = min(best, i-previous[x]+1)
            previous[x] = i
        return -1 if best == len(a)+1 else best
    if task_id == 'abc398_b':
        c = Counter(a)
        return any(x != y and c[x] >= 3 and c[y] >= 2 for x in c for y in c)
    if task_id == 'abc398_c':
        counts = Counter(a); eligible = [(x,i+1) for i,x in enumerate(a) if counts[x] == 1]
        return max(eligible)[1] if eligible else -1
    if task_id == 'abc400_c':
        # Unique form 2**a * odd_b**2. Factor every power of two out of b.
        total = 0; power = 2
        while power <= a:
            total += (isqrt(a//power)+1)//2
            power *= 2
        return total
    raise ValueError('Unsupported oracle')


def _brute(task_id, a):
    if task_id == 'abc397_b':
        for pairs in range(len(a)+1):
            it = iter('io'*pairs)
            if all(any(c == x for c in it) for x in a): return 2*pairs-len(a)
    if task_id == 'abc388_c':
        return sum(2*a[i] <= a[j] for i in range(len(a)) for j in range(i+1,len(a)))
    if task_id == 'abc388_e':
        @lru_cache(None)
        def search(mask):
            if not mask: return 0
            i = (mask & -mask).bit_length()-1; rest = mask ^ (1<<i)
            answer = search(rest)
            for j in range(i+1,len(a)):
                if rest & (1<<j) and 2*a[i] <= a[j]: answer = max(answer,1+search(rest^(1<<j)))
            return answer
        return search((1<<len(a))-1)
    if task_id == 'abc390_c':
        h,w = len(a),len(a[0])
        return any(all(c == '?' or (c == '#') == (top <= i <= bottom and left <= j <= right)
                       for i,row in enumerate(a) for j,c in enumerate(row))
                   for top in range(h) for bottom in range(top,h)
                   for left in range(w) for right in range(left,w))
    if task_id == 'abc391_d':
        w, blocks, queries = a
        current = {i+1:xy for i,xy in enumerate(blocks)}; snapshots = {}
        for t in range(1,max(t for t,i in queries)+1):
            bottom = [i for i,(x,y) in current.items() if y == 1]
            if len(bottom) == w:
                for i in bottom: del current[i]
            occupied = set(current.values())
            for i in sorted(current,key=lambda i:current[i][1]):
                x,y = current[i]
                if y > 1 and (x,y-1) not in occupied:
                    occupied.remove((x,y)); occupied.add((x,y-1)); current[i]=(x,y-1)
            snapshots[t] = set(current)
        return [i in snapshots[t] for t,i in queries]
    if task_id == 'abc394_d':
        @lru_cache(None)
        def erase(s):
            return not s or any(erase(s[:i]+s[i+2:]) for i in range(len(s)-1) if s[i:i+2] in ('()','[]','<>'))
        return erase(a)
    if task_id == 'abc397_c':
        return max(len(set(a[:i]))+len(set(a[i:])) for i in range(1,len(a)))
    if task_id == 'abc392_c':
        p,q = a
        return [q[p[q.index(bib)]-1] for bib in range(1,len(p)+1)]
    if task_id == 'abc395_c':
        lengths = [j-i for i in range(len(a)) for j in range(i+1,len(a)+1) if len(set(a[i:j])) < j-i]
        return min(lengths) if lengths else -1
    if task_id == 'abc398_b':
        return any(sorted(Counter(hand).values()) == [2,3] for hand in combinations(a,5))
    if task_id == 'abc398_c':
        unique = [(x,i+1) for i,x in enumerate(a) if sum(y == x for y in a) == 1]
        return max(unique)[1] if unique else -1
    if task_id == 'abc400_c':
        values = set(); power = 2
        while power <= a:
            for b in range(1,isqrt(a//power)+1): values.add(power*b*b)
            power *= 2
        return len(values)
    raise ValueError('Unsupported brute oracle')


def _render(task_id, result):
    if isinstance(result,bool): return ('Yes' if result else 'No')+'\n'
    if task_id == 'abc391_d': return ''.join(('Yes' if b else 'No')+'\n' for b in result)
    if isinstance(result,list): return ' '.join(map(str,result))+'\n'
    return str(result)+'\n'


def oracle_output(task_id, text):
    """Validate the complete public input domain before computing an answer."""
    return _render(task_id,_fast(task_id,_parse(task_id,text)))


def _sequence(a): return str(len(a))+'\n'+' '.join(map(str,a))+'\n'


def _small_inputs(task_id):
    rng = random.Random(20261004 + SUPPORTED_TASKS.index(task_id))
    for index in range(64):
        n = rng.randint(2,9)
        if task_id == 'abc397_b': yield ''.join(rng.choice('io') for _ in range(n))+'\n'
        elif task_id in ('abc388_c','abc388_e'): yield _sequence(sorted(rng.randint(1,20) for _ in range(n)))
        elif task_id == 'abc390_c':
            h,w = rng.randint(1,3),rng.randint(1,3)
            cells = [rng.choice('.?#') for _ in range(h*w)]; cells[rng.randrange(h*w)]='#'
            yield f'{h} {w}\n'+'\n'.join(''.join(cells[i*w:(i+1)*w]) for i in range(h))+'\n'
        elif task_id == 'abc391_d':
            w = rng.randint(1,min(3,n))
            blocks = rng.sample(list(product(range(1,w+1),range(1,7))),n if n <= w*6 else w*6)
            queries = list(product(range(1,9),range(1,len(blocks)+1)))
            yield f'{len(blocks)} {w}\n'+''.join(f'{x} {y}\n' for x,y in blocks)+str(len(queries))+'\n'+''.join(f'{t} {i}\n' for t,i in queries)
        elif task_id == 'abc394_d':
            yield (rng.choice(('()', '[]','<>'))*(n//2) if index%3 == 0 else ''.join(rng.choice('()[]<>') for _ in range(n)))+'\n'
        elif task_id == 'abc392_c':
            p=list(range(1,n+1));q=p.copy();rng.shuffle(p);rng.shuffle(q)
            yield _sequence(p)+' '.join(map(str,q))+'\n'
        elif task_id == 'abc398_b': yield ' '.join(str(rng.randint(1,5)) for _ in range(7))+'\n'
        elif task_id == 'abc400_c': yield str(rng.randint(1,5000))+'\n'
        elif task_id in ('abc397_c','abc395_c','abc398_c'): yield _sequence([rng.randint(1,n) for _ in range(n)])


def _boundaries(task_id):
    if task_id == 'abc397_b': return [('minimum-i','i\n'),('minimum-o','o\n'),('maximum-i','i'*100+'\n'),('maximum-o','o'*100+'\n')]
    if task_id in ('abc388_c','abc388_e'):
        return [('exact-half',_sequence([1,2])),('equal-max',_sequence([10**9]*2)),('maximum-half-split',_sequence([1]*250000+[2]*250000))]
    if task_id == 'abc390_c':
        grid=['#'*1000 for _ in range(1000)];grid[500]='#'*500+'.'+'#'*499
        return [('minimum','1 1\n#\n'),('unknown-inside','1 3\n#?#\n'),('maximum-hole','1000 1000\n'+'\n'.join(grid)+'\n')]
    if task_id == 'abc391_d':
        return [('minimum','1 1\n1 1\n2\n1 1\n1000000000 1\n'),('empty-column','2 2\n1 1\n1 1000000000\n2\n1 1\n1000000000 2\n'),('maximum-height','1 1\n1 1000000000\n2\n999999999 1\n1000000000 1\n'),('maximum-blocks','200000 1\n'+''.join(f'1 {i}\n' for i in range(1,200001))+'3\n1 1\n199999 200000\n200000 200000\n')]
    if task_id == 'abc394_d': return [('minimum','(\n'),('crossed','([)]\n'),('maximum-nested','('*100000+')'*100000+'\n')]
    if task_id == 'abc397_c': return [('minimum',_sequence([1,1])),('maximum-unique',_sequence(list(range(1,300001)))),('duplicates',_sequence([1,2,1,2]))]
    if task_id == 'abc392_c':
        return [('minimum-swap','2\n2 1\n2 1\n'),('maximum-identity',_sequence(list(range(1,300001)))+' '.join(map(str,range(300000,0,-1)))+'\n')]
    if task_id == 'abc395_c': return [('minimum',_sequence([10**6])),('adjacent',_sequence([1,1])),('maximum-last-repeat',_sequence(list(range(1,200000))+[1]))]
    if task_id == 'abc398_b': return [('all-same','13 13 13 13 13 13 13\n'),('four-three','1 1 1 1 13 13 13\n'),('distinct','1 2 3 4 5 6 13\n')]
    if task_id == 'abc398_c': return [('minimum',_sequence([10**9])),('maximum-all-duplicate',_sequence([10**9]*300000)),('largest-is-duplicate',_sequence([10**9,2,1,10**9]))]
    if task_id == 'abc400_c': return [(f'boundary-{n}',str(n)+'\n') for n in (1,2,3,4,7,8,18,10**18-1,10**18)]
    raise ValueError('Unsupported task')


@lru_cache(None)
def _self_check(task_id):
    truth_input, truth_output = _TRUTH[task_id]
    _require(oracle_output(task_id,truth_input) == truth_output, 'Hand-derived fixture disagreement')
    _require(_render(task_id,_brute(task_id,_parse(task_id,truth_input))) == truth_output, 'Reference fixture disagreement')
    inputs=list(_small_inputs(task_id))
    for text in inputs:
        parsed=_parse(task_id,text)
        _require(_fast(task_id,parsed) == _brute(task_id,parsed), 'Independent oracle disagreement: '+task_id)
    return len(inputs)


def build_bundle(task):
    """Build a reproducible bundle using only supplied public task information."""
    _require(isinstance(task,dict), 'Task must be a public dictionary')
    task_id=task.get('task_id');_require(task_id in SUPPORTED_TASKS,'Unsupported public validator: '+str(task_id))
    _require(isinstance(task.get('statement'),str) and bool(task['statement'].strip()),'Missing public statement')
    count=_self_check(task_id);cases=[]
    for i,example in enumerate(task.get('examples',[])):
        _require(isinstance(example,dict) and isinstance(example.get('input'),str) and isinstance(example.get('output'),str),'Malformed public example')
        expected=oracle_output(task_id,example['input'])
        _require(expected.split() == example['output'].split(),'Public example disagrees with independent oracle')
        cases.append({'input':example['input'],'output':expected,'label':f'public-example-{i+1}'})
    fixtures=[(f'independent-small-{i+1}',text) for i,text in enumerate(list(_small_inputs(task_id))[:16])]+_boundaries(task_id)
    for label,text in fixtures:
        cases.append({'input':text,'output':oracle_output(task_id,text),'label':label})
    bundle={'version':VERSION,'task_id':task_id,'statement_sha256':hashlib.sha256(task['statement'].encode()).hexdigest(),
            'validated':True,'cases':cases,'validation_evidence':{
                'source':'public statement and public examples only',
                'independent_small_cases':count,'reference':'exhaustive enumeration or literal simulation',
                'boundary_inputs_checked':True,'hand_derived_truth_fixture':True,
                'scope':'Bounded oracle cross-check; no guarantee that passing candidates are correct.',
                'coverage_limitations':[],
                'required_output_limit_bytes':4194304}}
    bundle['bundle_sha256']=_digest(bundle)
    verify_bundle(bundle,task_id)
    return bundle


def verify_bundle(bundle,task_id=None):
    """Fail closed on altered hashes, task identity, domains, or expected outputs."""
    _require(isinstance(bundle,dict),'Bundle must be a dictionary')
    _require(bundle.get('version') == VERSION and bundle.get('validated') is True,'Unvalidated bundle')
    identity=bundle.get('task_id');_require(identity in SUPPORTED_TASKS,'Unsupported bundle task')
    _require(task_id is None or identity == task_id,'Bundle belongs to another task')
    digest=bundle.get('bundle_sha256');_require(isinstance(digest,str),'Missing bundle digest')
    _require(digest == _digest({k:v for k,v in bundle.items() if k != 'bundle_sha256'}),'Modified bundle')
    statement_hash=bundle.get('statement_sha256');_require(isinstance(statement_hash,str) and len(statement_hash)==64 and set(statement_hash) <= set('0123456789abcdef'),'Missing statement hash')
    evidence=bundle.get('validation_evidence',{})
    _require(isinstance(evidence,dict),'Invalid validation evidence')
    _require(evidence.get('independent_small_cases') == _self_check(identity),'Missing independent validation')
    cases=bundle.get('cases');_require(isinstance(cases,list) and len(cases)>=17,'Insufficient check cases')
    labels=set()
    required = dict([(f'independent-small-{i+1}',text) for i,text in enumerate(list(_small_inputs(identity))[:16])] + _boundaries(identity))
    for case in cases:
        _require(isinstance(case,dict) and isinstance(case.get('input'),str) and isinstance(case.get('output'),str),'Invalid case')
        label=case.get('label');_require(isinstance(label,str) and label not in labels,'Invalid or duplicate case label');labels.add(label)
        if label in required:
            _require(case['input'] == required[label], 'Changed registered fixture input')
        else:
            _require(label.startswith('public-example-'), 'Unknown fixture label')
        expected=oracle_output(identity,case['input'])
        _require(case['output'] == expected,'Invalid expected output')
    _require(set(required) <= labels, 'Missing registered fixtures')
    return True
