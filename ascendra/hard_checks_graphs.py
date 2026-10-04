"""Public graph stress checks; independent small checks and analytic large cases.

No private evaluator data is loaded. Differential checks are bounded evidence,
not a proof that a candidate passing these fixtures is generally correct.
"""
from collections import deque
from functools import lru_cache
from heapq import heappush, heappop
import random

TASK_IDS = ('abc394_e', 'abc394_g', 'abc395_e', 'abc394_f')


def _need(ok, message='Input violates public graph contract'):
    if not ok: raise ValueError(message)


def parse_input(task_id, text):
    _need(task_id in TASK_IDS and isinstance(text,str))
    tok=text.split();_need(bool(tok))
    if task_id == 'abc394_e':
        n=int(tok[0]);rows=tok[1:]
        _need(1<=n<=100 and len(rows)==n and all(len(s)==n and set(s)<=set('-abcdefghijklmnopqrstuvwxyz') for s in rows))
        return rows
    a=list(map(int,tok))
    if task_id == 'abc394_g':
        _need(len(a)>=4);h,w=a[:2];_need(1<=h<=500 and 1<=w<=500)
        size=h*w;_need(len(a)>2+size);floors=a[2:2+size];q=a[2+size]
        _need(all(1<=f<=10**6 for f in floors) and 1<=q<=200000 and len(a)==3+size+6*q)
        queries=[tuple(a[i:i+6]) for i in range(3+size,len(a),6)]
        for r,c,y,s,d,z in queries:
            _need(1<=r<=h and 1<=s<=h and 1<=c<=w and 1<=d<=w)
            _need(1<=y<=floors[(r-1)*w+c-1] and 1<=z<=floors[(s-1)*w+d-1] and (r,c,y)!=(s,d,z))
        return h,w,floors,queries
    n=a[0];_need(1<=n<=200000)
    if task_id == 'abc395_e':
        _need(len(a)>=3 and n>=2);m,x=a[1:3]
        _need(1<=m<=200000 and 1<=x<=10**9 and len(a)==3+2*m);pairs=list(zip(a[3::2],a[4::2]))
    else:
        _need(len(a)==1+2*(n-1));pairs=list(zip(a[1::2],a[2::2]));x=None
    parent=list(range(n));sizes=[1]*n
    def find(u):
        while parent[u]!=u:parent[u]=parent[parent[u]];u=parent[u]
        return u
    for u,v in pairs:
        _need(1<=u<=n and 1<=v<=n);ru,rv=find(u-1),find(v-1)
        if task_id=='abc394_f':_need(ru!=rv,'Tree contains a cycle or repeated edge')
        if ru!=rv:
            if sizes[ru]<sizes[rv]:ru,rv=rv,ru
            parent[rv]=ru;sizes[ru]+=sizes[rv]
    if task_id=='abc395_e':_need(find(0)==find(n-1),'Target not reachable even with reversal')
    return (n,pairs) if task_id=='abc394_f' else (n,x,pairs)


def _palindrome(rows):
    n=len(rows);dist=[[-1]*n for _ in range(n)];q=deque();inside=[[[] for _ in range(26)] for _ in range(n)];outside=[[[] for _ in range(26)] for _ in range(n)]
    for i in range(n):dist[i][i]=0;q.append((i,i))
    for i,row in enumerate(rows):
        for j,c in enumerate(row):
            if c!='-':
                code=ord(c)-97;inside[j][code].append(i);outside[i][code].append(j)
                if i!=j:dist[i][j]=1;q.append((i,j))
    missing=sum(d<0 for row in dist for d in row)
    while q and missing:
        u,v=q.popleft();value=dist[u][v]+2
        for letter in range(26):
            if not outside[v][letter]:continue
            for i in inside[u][letter]:
                row=dist[i]
                for j in outside[v][letter]:
                    if row[j]<0:row[j]=value;q.append((i,j));missing-=1
    return dist


def _palindrome_brute(rows):
    # Exhaustively construct every enclosure transition and relax to a fixed point.
    # This shares the palindrome-enclosure theorem with BFS, not its traversal.
    n=len(rows);inf=10**9;d=[[0 if i==j else (1 if rows[i][j]!='-' else inf) for j in range(n)] for i in range(n)]
    transitions=[(i,j,u,v) for i in range(n) for j in range(n) for u in range(n) for v in range(n) if rows[i][u]!='-' and rows[i][u]==rows[v][j]]
    while True:
        changed=False
        for i,j,u,v in transitions:
            if d[u][v]+2<d[i][j]:d[i][j]=d[u][v]+2;changed=True
        if not changed:break
    return [[-1 if x==inf else x for x in row] for row in d]


def _neighbors(i,h,w):
    if i>=w:yield i-w
    if i+w<h*w:yield i+w
    if i%w:yield i-1
    if i%w+1<w:yield i+1


def _building(data):
    h,w,floors,queries=data;answers=[]
    # Closed form certificate for the large public flat / vertical-wall families:
    # each component above the wall height is a connected rectangular region.
    high=max(floors);low=min(floors)
    flat=(low==high)
    wall=next((j for j in range(w) if floors[j]==low),-1)
    striped=(not flat and 0<wall<w-1 and all(floors[i*w+j]==(low if j==wall else high) for i in range(h) for j in range(w)))
    cache={}
    for r,c,y,s,d,z in queries:
        start=(r-1)*w+c-1;end=(s-1)*w+d-1
        if start==end or flat:answers.append(abs(y-z));continue
        if striped:
            cap=high if (c-1<wall and d-1<wall) or (c-1>wall and d-1>wall) else low
        else:
            _need(h*w<=2500,'General reference is limited to small grids; large cases require an analytic certificate')
            if start not in cache:
                best=[0]*(h*w);best[start]=floors[start];heap=[(-best[start],start)]
                while heap:
                    neg,u=heappop(heap);value=-neg
                    if value!=best[u]:continue
                    for v in _neighbors(u,h,w):
                        candidate=min(value,floors[v])
                        if candidate>best[v]:best[v]=candidate;heappush(heap,(-candidate,v))
                cache[start]=best
            cap=cache[start][end]
        answers.append(y+z-2*min(y,z,cap))
    return answers


def _building_brute(data):
    # Literal zero/one BFS over individual (building, floor) positions.
    h,w,floors,queries=data;result=[]
    for r,c,y,s,d,z in queries:
        start=((r-1)*w+c-1,y);goal=((s-1)*w+d-1,z);dist={start:0};q=deque([start])
        while q:
            u,f=q.popleft();value=dist[(u,f)]
            for v in _neighbors(u,h,w):
                if floors[v]>=f and value<dist.get((v,f),10**9):dist[(v,f)]=value;q.appendleft((v,f))
            for nf in (f-1,f+1):
                if 1<=nf<=floors[u] and value+1<dist.get((u,nf),10**9):dist[(u,nf)]=value+1;q.append((u,nf))
        result.append(dist[goal])
    return result


def _reversal(data):
    n,x,edges=data;out=[[] for _ in range(n)];inc=[[] for _ in range(n)]
    for u,v in edges:out[u-1].append(v-1);inc[v-1].append(u-1)
    inf=10**30;dist=[inf]*(2*n);dist[0]=0;heap=[(0,0)]
    while heap:
        cost,state=heappop(heap)
        if cost!=dist[state]:continue
        mode,u=divmod(state,n)
        if u==n-1:return cost
        other=(1-mode)*n+u
        if cost+x<dist[other]:dist[other]=cost+x;heappush(heap,(cost+x,other))
        for v in (inc[u] if mode else out[u]):
            target=mode*n+v
            if cost+1<dist[target]:dist[target]=cost+1;heappush(heap,(cost+1,target))
    raise ValueError('Unreachable target')


def _reversal_brute(data):
    n,x,edges=data;links=[]
    for u in range(n):links.extend(((u,n+u,x),(n+u,u,x)))
    for u,v in edges:links.extend(((u-1,v-1,1),(n+v-1,n+u-1,1)))
    d=[10**30]*(2*n);d[0]=0
    for _ in range(2*n-1):
        changed=False
        for u,v,cost in links:
            if d[u]+cost<d[v]:d[v]=d[u]+cost;changed=True
        if not changed:break
    return min(d[n-1],d[2*n-1])


def _alkane(data):
    n,edges=data;adj=[[] for _ in range(n)]
    for u,v in edges:adj[u-1].append(v-1);adj[v-1].append(u-1)
    parent=[-1]*n;order=[0];parent[0]=0
    for u in order:
        for v in adj[u]:
            if v!=parent[u]:parent[v]=u;order.append(v)
    down=[1]*n;answer=-1
    for u in reversed(order):
        children=sorted((down[v] for v in adj[u] if v!=parent[u]),reverse=True)
        if len(children)>=3:
            down[u]=1+sum(children[:3])
            if u!=0:answer=max(answer,down[u]+1)
        if len(children)>=4:answer=max(answer,1+sum(children[:4]))
    return answer


def _alkane_brute(data):
    n,edges=data;_need(n<=18,'Subset oracle only for small trees');answer=-1
    for mask in range(1,1<<n):
        size=mask.bit_count()
        if size<5 or size<=answer:continue
        degree=[0]*n;count=0
        for u,v in edges:
            if mask>>(u-1)&1 and mask>>(v-1)&1:degree[u-1]+=1;degree[v-1]+=1;count+=1
        if count==size-1 and any(d==4 for d in degree) and all(degree[u] in (1,4) for u in range(n) if mask>>u&1):answer=size
    return answer


def reference_output(task_id,text):
    data=parse_input(task_id,text)
    if task_id=='abc394_e':return '\n'.join(' '.join(map(str,row)) for row in _palindrome(data))+'\n'
    if task_id=='abc394_g':return ''.join(str(x)+'\n' for x in _building(data))
    if task_id=='abc395_e':return str(_reversal(data))+'\n'
    return str(_alkane(data))+'\n'


def _grid_input(h,w,floors,queries):
    return f'{h} {w}\n'+'\n'.join(' '.join(map(str,floors[i*w:(i+1)*w])) for i in range(h))+'\n'+str(len(queries))+'\n'+''.join(' '.join(map(str,q))+'\n' for q in queries)


def _tree_input(n,edges):return str(n)+'\n'+''.join(f'{u} {v}\n' for u,v in edges)


def _reverse_input(n,x,edges):return f'{n} {len(edges)} {x}\n'+''.join(f'{u} {v}\n' for u,v in edges)


def _small(task_id):
    rng=random.Random(20261004+TASK_IDS.index(task_id))
    for _ in range(24):
        n=rng.randint(2,7)
        if task_id=='abc394_e':
            n=rng.randint(1,5);yield str(n)+'\n'+'\n'.join(''.join(rng.choice('---abc') for _ in range(n)) for _ in range(n))+'\n'
        elif task_id=='abc394_g':
            h,w=rng.randint(1,3),rng.randint(1,3);floors=[rng.randint(2,6) for _ in range(h*w)];queries=[]
            for i in range(6):
                a,b=rng.randrange(h*w),rng.randrange(h*w);y,z=rng.randint(1,floors[a]),rng.randint(1,floors[b])
                if (a,y)==(b,z):z=1 if y!=1 else 2
                queries.append((a//w+1,a%w+1,y,b//w+1,b%w+1,z))
            yield _grid_input(h,w,floors,queries)
        elif task_id=='abc395_e':
            edges=[(i,i+1) if rng.randrange(2) else (i+1,i) for i in range(1,n)]
            edges += [(rng.randint(1,n),rng.randint(1,n)) for _ in range(n)]
            yield _reverse_input(n,rng.choice((1,3,10**9)),edges)
        else:
            n=rng.randint(1,11);yield _tree_input(n,[(i,rng.randrange(1,i)) for i in range(2,n+1)])


def _large(task_id):
    if task_id=='abc394_e':
        n=100
        yield 'maximum-single-letter-cycle',str(n)+'\n'+'\n'.join(''.join('a' if j==(i+1)%n else '-' for j in range(n)) for i in range(n))+'\n'
        yield 'maximum-dense-bipartite',str(n)+'\n'+'\n'.join(''.join('a' if (i<50)!=(j<50) else '-' for j in range(n)) for i in range(n))+'\n'
        yield 'minimum-empty','1\n-\n'
    elif task_id=='abc394_g':
        h=w=500
        queries=[(1,1,10**6,500,500,10**6),(1,1,1,500,500,10**6),(250,250,10**6,250,250,1)]
        yield 'maximum-uniform-grid',_grid_input(h,w,[10**6]*(h*w),queries)
        floors=[1 if j==250 else 10**6 for i in range(h) for j in range(w)]
        queries=[(1,1,10**6,500,500,10**6),(1,1,9,500,250,7),(1,251,1,500,500,10**6),(1,1,1,1,2,2)]
        yield 'maximum-grid-low-wall',_grid_input(h,w,floors,queries)
        queries=[(1,1,1+i%10**6,1,2,10**6-i%10**6) for i in range(200000)]
        yield 'maximum-query-count',_grid_input(1,2,[10**6,10**6],queries)
    elif task_id=='abc395_e':
        n=200000
        yield 'maximum-alternating-chain',_reverse_input(n,10**9,[(i+1,i) if i%2 else (i,i+1) for i in range(1,n)])
        yield 'maximum-forward-chain',_reverse_input(n,1,[(i,i+1) for i in range(1,n)])
        yield 'reverse-required','2 1 1000000000\n2 1\n'
    else:
        n=200000
        yield 'maximum-chain',_tree_input(n,[(i,i+1) for i in range(1,n)])
        yield 'maximum-star',_tree_input(n,[(1,i) for i in range(2,n+1)])
        k=60000;edges=[(i,i+1) for i in range(1,k)];next_node=k+1
        for i in range(1,k+1):
            for j in range(3 if i in (1,k) else 2):edges.append((i,next_node));next_node+=1
        yield 'large-alkane-comb',_tree_input(next_node-1,edges)
        yield 'minimum-single-node','1\n'


@lru_cache(None)
def _validate_oracles(task_id):
    checks=0
    for text in _small(task_id):
        data=parse_input(task_id,text)
        fast,brute={'abc394_e':(_palindrome,_palindrome_brute),'abc394_g':(_building,_building_brute),'abc395_e':(_reversal,_reversal_brute),'abc394_f':(_alkane,_alkane_brute)}[task_id]
        _need(fast(data)==brute(data),'Independent graph oracle disagreement');checks+=1
    # Validate the closed-form large-family claims on small analogous structures.
    if task_id=='abc394_g':
        for h,w in ((1,3),(2,3),(3,5)):
            floors=[1 if j==w//2 else 6 for i in range(h) for j in range(w)]
            queries=[(1,1,6,h,w,6),(1,1,1,h,1,2)]
            data=parse_input(task_id,_grid_input(h,w,floors,queries))
            _need(_building(data)==_building_brute(data),'Wall certificate mismatch');checks+=1
    return checks


def build_cases(task):
    _need(isinstance(task,dict) and task.get('task_id') in TASK_IDS,'Unsupported graph task')
    task_id=task['task_id'];checks=_validate_oracles(task_id);cases=[]
    for index,example in enumerate(task.get('examples',[])):
        expected=reference_output(task_id,example['input'])
        _need(expected.split()==example['output'].split(),'Public example / oracle mismatch')
        cases.append({'input':example['input'],'output':expected,'label':f'public-example-{index+1}'})
    fixtures=[(f'independent-small-{i+1}',text) for i,text in enumerate(list(_small(task_id))[:6])]+list(_large(task_id))
    for label,text in fixtures:cases.append({'input':text,'output':reference_output(task_id,text),'label':label})
    return {'cases':cases,'validation_evidence':{'independent_small_checks':checks,'source':'public statements and public examples only','input_domain_validation':True,'large_cases':'Full constraints with certified uniform/wall grid families, directed chains, palindrome cycles and trees',
        'independence':{'abc394_e':'Pair BFS versus exhaustive enclosure-transition fixed point; both share the palindrome-enclosure theorem.', 'abc394_g':'Widest path / certified grid formulas versus literal individual-floor 0/1 BFS.', 'abc395_e':'Dijkstra versus explicit transition Bellman-Ford; both share reversal-parity state representation.', 'abc394_f':'Tree dynamic programming versus exhaustive vertex-subset connectivity and degree checks.'}[task_id],
        'scope':'Bounded differential validation and structured stress coverage; not a general correctness proof.'}}


def verify_cases(task,cases):
    _need(isinstance(cases,list),'Cases must be a list')
    expected=build_cases(task)['cases']
    _need(cases==expected,'Graph cases differ from canonical public reconstruction')
    return True
