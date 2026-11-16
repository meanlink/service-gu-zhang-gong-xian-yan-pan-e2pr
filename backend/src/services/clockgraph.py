"""服务间校时约束图：由有向凭据及间接组合求可行修正区间、冲突链与连通分量。

约定：修正后的读数 = 原始读数 + offset[service]。
凭据 source→target 断言 offset[target] - offset[source] 落在 [lower, upper]。
参考服务被锚定为 offset=0；只有服务之间的修正差参与判定，因此锚点选择不影响结论。
"""
from __future__ import annotations

import math

EPS = 1e-9
INF = math.inf


def _edges(credentials):
    """把每条凭据拆成两个有向不等式：o[to]-o[from] ≤ upper，o[from]-o[to] ≤ -lower。"""
    result = []
    for credential in credentials:
        source = str(credential['source'])
        target = str(credential['target'])
        lower = float(credential['lower'])
        upper = float(credential['upper'])
        base = {
            'credential_id': credential.get('id'),
            'source': source,
            'target': target,
            'lower': lower,
            'upper': upper,
        }
        result.append({**base, 'from': source, 'to': target, 'weight': upper, 'direction': 'forward'})
        result.append({**base, 'from': target, 'to': source, 'weight': -lower, 'direction': 'reverse'})
    return result


def _bellman_ford(nodes, edges, origin):
    dist = {name: INF for name in nodes}
    pred = {name: None for name in nodes}
    dist[origin] = 0.0
    for _ in range(len(nodes) - 1):
        changed = False
        for edge in edges:
            left, right = edge['from'], edge['to']
            if dist[left] == INF:
                continue
            through = dist[left] + edge['weight']
            if through < dist[right] - 1e-12:
                dist[right] = through
                pred[right] = left
                changed = True
        if not changed:
            break
    witnesses = {}
    for edge in edges:
        left, right = edge['from'], edge['to']
        if dist[left] == INF:
            continue
        if dist[left] + edge['weight'] < dist[right] - 1e-12:
            witnesses.setdefault(right, left)
    return dist, pred, witnesses


def _pick_edge(edge_pairs, left, right):
    candidates = [edge for edge in edge_pairs if edge['from'] == left and edge['to'] == right]
    if not candidates:
        return None
    return min(candidates, key=lambda edge: (edge['weight'], edge['credential_id'] or 0))


def _extract_cycle(nodes, edges, origin, witness):
    """在检测到负环的图上，从前驱链里截出一个简单环。"""
    pred = {name: None for name in nodes}
    dist = {name: INF for name in nodes}
    dist[origin] = 0.0
    for _ in range(len(nodes)):
        for edge in edges:
            left, right = edge['from'], edge['to']
            if dist[left] == INF:
                continue
            through = dist[left] + edge['weight']
            if through < dist[right] - 1e-12:
                dist[right] = through
                pred[right] = left
    node = witness
    for _ in range(len(nodes) + 1):
        if pred.get(node) is None:
            return None
        node = pred[node]
    cycle = [node]
    current = pred[node]
    for _ in range(len(nodes) + 1):
        if current is None:
            return None
        if current == node:
            break
        cycle.append(current)
        current = pred[current]
    else:
        return None
    cycle.reverse()
    return cycle


def _conflict_entry(cycle, edge_pairs):
    steps = []
    total = 0.0
    for position in range(len(cycle)):
        left = cycle[position]
        right = cycle[(position + 1) % len(cycle)]
        edge = _pick_edge(edge_pairs, left, right)
        if edge is None:
            return None
        total += edge['weight']
        if edge['direction'] == 'forward':
            relation = f"{left}→{right} ≤ {edge['weight']:.3f}"
        else:
            relation = f"{left}→{right} ≤ {edge['weight']:.3f}（凭据 {edge['source']}→{edge['target']} 反向）"
        steps.append({
            'from': left,
            'to': right,
            'credential_id': edge['credential_id'],
            'source': edge['source'],
            'target': edge['target'],
            'lower': round(edge['lower'], 6),
            'upper': round(edge['upper'], 6),
            'direction': edge['direction'],
            'weight': round(edge['weight'], 6),
            'relation': relation,
        })
    if total >= -EPS:
        return None
    chain = '；'.join(step['relation'] for step in steps)
    return {
        'services': cycle,
        'total_weight': round(total, 6),
        'steps': steps,
        'credential_ids': sorted({step['credential_id'] for step in steps if step['credential_id'] is not None}),
        'message': f"冲突链：{chain}；合计 {total:.3f} 分钟 < 0，不存在同时成立的校时。",
        '_key': frozenset(
            (step['credential_id'], step['direction'])
            for step in steps if step['credential_id'] is not None
        ),
    }


def _components(nodes, edges):
    parent = {name: name for name in nodes}

    def find(name):
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    for edge in edges:
        union(edge['from'], edge['to'])
    groups = {}
    for name in nodes:
        groups.setdefault(find(name), []).append(name)
    return sorted(groups.values())


def _all_pairs(nodes, edges):
    """无负环时用 Bellman-Ford 逐点求最短路径，d(u,v) 表示 o[v]-o[u] 的上界。"""
    table = {}
    for origin in nodes:
        dist, _, _ = _bellman_ford(nodes, edges, origin)
        table[origin] = dist
    return table


def solve(credentials, reference, services=()):
    """返回一致性、各服务相对参考服务的可行修正区间、两两修正差区间。"""
    reference = str(reference)
    credential_services = {str(item['source']) for item in credentials} | {str(item['target']) for item in credentials}
    nodes = sorted({reference, *credential_services, *[str(name) for name in services]})
    edge_pairs = _edges(credentials)
    conflicts = []
    seen = set()
    for origin in nodes:
        _, _, witnesses = _bellman_ford(nodes, edge_pairs, origin)
        for witness in witnesses:
            cycle = _extract_cycle(nodes, edge_pairs, origin, witness)
            if not cycle or len(cycle) < 2 or len(set(cycle)) != len(cycle):
                cycle = _extract_cycle(nodes, edge_pairs, witness, witness)
            if not cycle or len(cycle) < 2 or len(set(cycle)) != len(cycle):
                continue
            entry = _conflict_entry(cycle, edge_pairs)
            if not entry:
                continue
            key = entry.pop('_key')
            if key in seen:
                continue
            seen.add(key)
            conflicts.append(entry)
    consistent = not conflicts
    groups = _components(nodes, edge_pairs) if nodes else []
    ranges = {}
    deltas = {}
    unreachable = []
    table = _all_pairs(nodes, edge_pairs) if consistent and nodes else {}
    for name in nodes:
        if consistent and table.get(reference, {}).get(name, INF) < INF and table.get(name, {}).get(reference, INF) < INF:
            ranges[name] = {
                'lower': round(-table[name][reference], 6),
                'upper': round(table[reference][name], 6),
                'reachable': True,
            }
        else:
            ranges[name] = {'lower': None, 'upper': None, 'reachable': False}
            if name != reference:
                unreachable.append(name)
    if consistent:
        for left in nodes:
            row = {}
            for right in nodes:
                if left == right:
                    row[right] = {'lower': 0.0, 'upper': 0.0}
                elif table.get(right, {}).get(left, INF) < INF and table.get(left, {}).get(right, INF) < INF:
                    row[right] = {
                        'lower': round(-table[right][left], 6),
                        'upper': round(table[left][right], 6),
                    }
                else:
                    row[right] = {'lower': None, 'upper': None}
            deltas[left] = row
    return {
        'reference': reference,
        'services': nodes,
        'consistent': consistent,
        'conflicts': conflicts,
        'components': groups,
        'ranges': ranges,
        'deltas': deltas,
        'unreachable': unreachable,
    }


def disconnected_services(solution, required):
    """必选服务中无法与参考服务联通的部分，按连通分量分组返回。"""
    required = [str(name) for name in required]
    unreachable = [name for name in required if not solution['ranges'].get(name, {}).get('reachable')]
    if not unreachable:
        return []
    result = []
    assigned = set()
    for group in solution.get('components') or []:
        hits = [name for name in unreachable if name in group]
        if hits:
            result.append(sorted(hits))
            assigned.update(hits)
    remaining = sorted(name for name in unreachable if name not in assigned)
    if remaining:
        result.append(remaining)
    return result


def feasible_delta(solution, source, target):
    """两服务修正差的可行区间 lower ≤ o[target]-o[source] ≤ upper，可直接加到原始时滞上。"""
    if not solution['consistent']:
        return None
    row = solution.get('deltas', {}).get(str(source))
    if not row:
        return None
    item = row.get(str(target))
    if not item or item.get('lower') is None or item.get('upper') is None:
        return None
    return float(item['lower']), float(item['upper'])
