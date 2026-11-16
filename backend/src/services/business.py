"""服务事件窗口Jaccard和最近后继的有向时滞关联。

选用校时方案时，凭据把各服务读数约束成“原始读数+修正量”。对每个先发生事件 A，
只在所有可行修正下都落入 (0, window] 的跟随才计为确定；部分可行修正下才落入的计为待定。
"""
from collections import defaultdict
import math
import numpy as np


def metadata():
    return {
        "name": "服务故障共现研判", "short": "incident-links",
        "tagline": "把同窗共现和先后跟随分开量化，定位值得复查的传播链。",
        "client": "桥石数服 · 7人可靠性小组 · 5个服务的告警复核事件",
        "workflow": "值班工程师翻阅多份告警时间线，手工判断缓存、网关与队列异常是否同时出现，并先用校时凭据对齐各服务时钟。",
        "pains": ["告警次数不同使原始共同次数不可比", "时钟不齐会颠倒故障先后", "同窗共现容易被误读成先后传播", "人工时间线无法复现实验窗口变化"],
        "upstream": "已去除重复通知的事件归档 service_events_week45.csv；时间以周一00:00起累计分钟表示，服务间时钟存在分钟级偏差",
        "downstream": "可靠性复盘会对高Jaccard与短时滞的服务对核查调用日志，并回查所用校时凭据",
        "entities": ["服务复核事件", "时窗关联试验", "可靠性复盘简报", "校时凭据与校时方案"],
        "dataset_name": "桥石五服务本周复核事件序列",
        "columns": [{"key": "event_id", "label": "复核事件ID", "type": "string"}, {"key": "service", "label": "服务名称", "type": "string"}, {"key": "occurred_min", "label": "周内累计分钟", "type": "number"}, {"key": "severity", "label": "事件等级(1~3)", "type": "number"}],
        "parameters": [{"key": "window_min", "label": "同窗及跟随窗口(分钟)", "type": "number", "default": 5, "min": 1, "max": 30}, {"key": "min_pairs", "label": "最少跟随事件数", "type": "number", "default": 3, "min": 2, "max": 20}],
        "workbench_title": "服务事件时窗复盘", "action_label": "计算共现与有向时滞", "unit": "个复核事件",
        "accent": "oklch(63% 0.12 155)", "style": "control-room-industrial",
        "seed_story": ["09:00 值班工程师导入 service_events_week45.csv", "09:10 确认事件已按event_id去重，时间原点均为周一00:00", "09:20 登记服务间校时凭据并发布校时方案", "09:21 后端由凭据及间接关系求各服务可行修正区间", "09:30 选择5分钟窗口、至少3次跟随，区分确定与待定跟随", "09:40 将窗口改为10分钟，查看链条是否扩张", "10:00 下载服务对明细，回查原始调用链与校时凭据", "17:00 管理员安排每周一09:00可靠性复盘简报"],
        "method": "固定窗口以累计分钟0为原点；Jaccard=共同占用窗/任一服务占用窗，按原始读数计算。对每个A事件，匹配窗口内严格晚于它的最早B事件；跟随率=匹配A事件数/A总事件数，输出中位时滞。每个A独立匹配，允许不同A共享B。选用校时方案时，凭据 source→target 断言 offset[target]-offset[source]∈[lower,upper]，参考服务锚定0；用差值约束的闭包求各服务相对参考服务的可行修正区间及两两修正差区间。只有对全部可行修正都成立的跟随计为确定，部分修正下成立的列为待定。",
        "limitations": ["窗口边界会影响Jaccard，必须比较多个窗口", "多个A可共享后继B，不表示一对一故障传播", "共现或先后关系均不足以证明因果", "校时凭据只覆盖已登记的服务对及其间接组合，断开的服务不能联合分析", "Jaccard按原始读数计算，不随校时修正变化"],
    }


# 各服务时钟相对真实时间的偏差（分钟，正值表示读数偏快）。原始事件保留这些读数，
# 校时凭据给出允许的修正区间，分析时才在窗口判定中应用。
CLOCK_ERRORS = {
    "cache": 2.0,
    "api-gateway": 0.0,
    "job-queue": -1.0,
    "metrics-db": 0.5,
    "object-store": -2.0,
}


def seed_records():
    rng = np.random.default_rng(1013)
    events = []
    def add(service, true_minute, severity):
        recorded = max(0.0, true_minute + CLOCK_ERRORS[service])
        events.append({"event_id": f"QS-{len(events)+1:04}", "service": service, "occurred_min": round(float(recorded), 2), "severity": int(severity)})
    for i in range(55):
        base = i * 60 + float(rng.uniform(4, 15))
        add("cache", base, 2)
        add("api-gateway", base + float(rng.uniform(1.5, 4.5)), 2)
        if i % 3 == 0:
            add("job-queue", base + float(rng.uniform(6, 11)), 1)
        if i % 4 == 0:
            add("metrics-db", base - float(rng.uniform(2, 4)), 3)
    for _ in range(45):
        add(str(rng.choice(["cache", "api-gateway", "job-queue", "metrics-db", "object-store"])), rng.uniform(0, 3300), rng.integers(1, 4))
    return sorted(events, key=lambda row: row["occurred_min"])


def _follow_window(lag, low, high, window):
    """返回该 B 事件在所有可行修正下落入 (0, window] 的修正量区间。"""
    start = max(low, math.nextafter(-lag, math.inf))
    end = min(high, window - lag)
    if start > end:
        return None
    return start, end


def _covers_interval(intervals, low, high):
    if not intervals:
        return False
    ordered = sorted(intervals)
    reach = low
    for start, end in ordered:
        if start > reach:
            return False
        if end > reach:
            reach = end
        if reach >= high:
            return True
    return reach >= high


def _classify_follows(times_a, ids_a, times_b, low, high, window):
    """对每个 A 事件判断跟随的确定性，返回事件级明细。

    每个候选 B 对应一段可行的修正差区间；这些区间的并集覆盖 [low, high] 时，
    无论凭据取哪种允许值，A 之后都存在窗口内的 B，该跟随计为确定。
    """
    details = []
    for instant, event_id in zip(times_a, ids_a):
        intervals = []
        candidates = []
        for other in times_b:
            lag = float(other - instant)
            span = _follow_window(lag, low, high, window)
            if span is None:
                continue
            intervals.append(span)
            candidates.append(lag)
        if not candidates:
            details.append(None)
            continue
        certain = _covers_interval(intervals, low, high)
        possible = []
        for lag in candidates:
            begin = max(lag + low, 0.0)
            finish = min(lag + high, float(window))
            if begin < finish or abs(begin - finish) <= 1e-12:
                possible.append((begin, finish))
        details.append({
            "event_id": event_id,
            "certain": certain,
            "lag_low": min(item[0] for item in possible),
            "lag_high": max(item[1] for item in possible),
            "candidates": candidates,
        })
    return details


def _nominal_lag(detail, low, high, window):
    """在可行修正差的中点取一个代表性时滞，用于中位数展示；区间上下限另行给出。"""
    delta = (low + high) / 2
    feasible = [lag + delta for lag in detail["candidates"] if 0 < lag + delta <= window]
    if feasible:
        return min(feasible)
    return (detail["lag_low"] + detail["lag_high"]) / 2


def _delta_for(calibration, source, target):
    """换算成“加到原始时滞上的修正量”区间。

    offset 表示各服务读数需要加上的修正量；修正后的时滞 = 原始时滞 + offset[target] - offset[source]。
    """
    if not calibration:
        return 0.0, 0.0
    row = (calibration.get("deltas") or {}).get(source) or {}
    item = row.get(target)
    if not item or item.get("lower") is None or item.get("upper") is None:
        raise ValueError(f"服务 {source} 与 {target} 之间没有可用的校时关系，不能联合分析。")
    return float(item["lower"]), float(item["upper"])


def _calibration_block(calibration):
    if not calibration:
        return None
    ranges = calibration.get("ranges") or {}
    return {
        "reference": calibration.get("reference"),
        "scheme_id": calibration.get("scheme_id"),
        "revision": calibration.get("revision"),
        "ranges": [
            {
                "service": name,
                "lower": (ranges.get(name) or {}).get("lower"),
                "upper": (ranges.get(name) or {}).get("upper"),
            }
            for name in sorted(ranges)
        ],
        "conflicts": calibration.get("conflicts") or [],
    }


def analyze(records, params, calibration=None):
    try:
        window = float(params.get("window_min", 5))
        raw_min = float(params.get("min_pairs", 3))
        minimum = int(raw_min)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("窗口与最少跟随次数须为有效数值。") from exc
    if not 1 <= window <= 30 or raw_min != minimum or not 2 <= minimum <= 20:
        raise ValueError("窗口须1~30分钟，最少跟随数须2~20的整数。")
    if calibration and not calibration.get("consistent", True):
        chains = [entry.get("message", "") for entry in calibration.get("conflicts") or []]
        raise ValueError("校时凭据相互矛盾，不能分析：" + " | ".join(chains))
    if len(records) < 30:
        raise ValueError("至少需要30个已去重事件。")
    grouped = defaultdict(list)
    identifiers = set()
    for row in records:
        try:
            service = str(row["service"]).strip()
            minute = float(row["occurred_min"])
            severity = float(row["severity"])
            event_id = str(row["event_id"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("事件ID、服务、累计分钟与等级须完整。") from exc
        if not service or not event_id or not np.isfinite(minute) or minute < 0 or severity not in (1, 2, 3):
            raise ValueError("事件ID与服务不能为空，时间须非负有限，等级须1~3。")
        if event_id in identifiers:
            raise ValueError("事件ID重复，请先去重，避免人为放大关联。")
        identifiers.add(event_id)
        grouped[service].append((minute, event_id))
    if not 2 <= len(grouped) <= 12:
        raise ValueError("一次试验须包含2~12个服务。")
    times = {key: np.sort(np.array([value for value, _ in rows], dtype=float)) for key, rows in grouped.items()}
    events_by_service = {
        key: [event_id for _, event_id in sorted(rows, key=lambda item: item[0])]
        for key, rows in grouped.items()
    }
    if calibration:
        ranges = calibration.get("ranges") or {}
        missing = sorted(set(grouped) - set(ranges.keys()))
        if missing:
            raise ValueError("以下服务没有校时依据：" + "、".join(missing))
        unreachable = sorted(name for name in grouped if not (ranges.get(name) or {}).get("reachable"))
        if unreachable:
            raise ValueError(
                "以下服务与参考服务之间没有可用的校时凭据链，拒绝联合分析："
                + "、".join(unreachable)
            )
    occupied = {key: set(np.floor(values / window).astype(int).tolist()) for key, values in times.items()}
    rows = []
    pending_details = []
    for a in sorted(times):
        for b in sorted(times):
            if a == b:
                continue
            low, high = _delta_for(calibration, a, b)
            details = _classify_follows(times[a], events_by_service[a], times[b], low, high, window)
            certain_lags = []
            pending_count = 0
            for detail in details:
                if detail is None:
                    continue
                if detail["certain"]:
                    certain_lags.append(_nominal_lag(detail, low, high, window))
                else:
                    pending_count += 1
                    if len(pending_details) < 200:
                        pending_details.append({
                            "source": a,
                            "target": b,
                            "source_event": detail["event_id"],
                            "lag_low": round(detail["lag_low"], 3),
                            "lag_high": round(detail["lag_high"], 3),
                        })
            certain_count = len(certain_lags)
            if certain_count + pending_count < minimum:
                continue
            union = len(occupied[a] | occupied[b])
            intersection = len(occupied[a] & occupied[b])
            rows.append({
                "source": a, "target": b, "source_events": len(times[a]),
                "certain_follow_count": certain_count,
                "pending_follow_count": pending_count,
                "follow_count": certain_count,
                "follow_pct": round(certain_count / len(times[a]) * 100, 2),
                "pending_pct": round(pending_count / len(times[a]) * 100, 2),
                "median_lag_min": round(float(np.median(certain_lags)), 3) if certain_lags else None,
                "lag_low_min": round(min(detail["lag_low"] for detail in details if detail and detail["certain"]), 3) if certain_count else None,
                "lag_high_min": round(max(detail["lag_high"] for detail in details if detail and detail["certain"]), 3) if certain_count else None,
                "certainty": "certain" if certain_count >= minimum else "pending",
                "jaccard": round(intersection / union, 4) if union else 0.0,
                "shared_windows": intersection,
            })
    rows.sort(key=lambda row: (-row["follow_pct"], -row["certain_follow_count"], -row["pending_follow_count"], row["source"], row["target"]))
    for rank, row in enumerate(rows, 1):
        row["link_id"] = f"L{rank:02}"
    top = rows[:8]
    certain_links = [row for row in rows if row["certainty"] == "certain"]
    pending_links = [row for row in rows if row["certainty"] == "pending"]
    calibration_block = _calibration_block(calibration)
    calibration_note = ""
    if calibration:
        calibration_note = (
            f"采用校时方案“{calibration.get('name', '')}”修订 {calibration.get('revision', '')}，"
            f"参考服务 {calibration.get('reference', '')}。"
        )
    findings = []
    if certain_links:
        lead = certain_links[0]
        findings.append(
            f"最强确定跟随方向为{lead['source']}→{lead['target']}："
            f"{lead['certain_follow_count']}次确定跟随（{lead['follow_pct']}%），"
            f"中位可行时滞{lead['median_lag_min']}分钟。"
        )
    elif pending_links:
        lead = pending_links[0]
        findings.append(
            f"没有任何服务对由确定跟随独立达到阈值；最接近的是{lead['source']}→{lead['target']}，"
            f"确定{lead['certain_follow_count']}次、待定{lead['pending_follow_count']}次，需补充凭据或复核误差范围。"
        )
    else:
        findings.append("当前窗口与最少次数下没有候选服务对，可核对时间范围后调整窗口。")
    if pending_links:
        findings.append(
            f"{len(pending_links)}条有向服务对仅靠待定跟随达到阈值：在部分可行校时下先后顺序会变化，未计入确定结论。"
        )
    findings.append("Jaccard衡量同窗重合，有向跟随率区分确定与待定，两者不可互相替代。")
    findings.append("每个源事件仅取最近后继；扩大窗口可能提高跟随率，也会引入偶然匹配。")
    summary = (
        f"{len(records)}个事件覆盖{len(times)}个服务；{window:g}分钟窗口下，"
        f"{len(rows)}条有向服务对达到{minimum}次跟随阈值：{len(certain_links)}条由确定跟随独立满足"
        f"（共{sum(row['certain_follow_count'] for row in certain_links)}次），"
        f"{len(pending_links)}条依赖待定跟随。"
    )
    if calibration_note:
        summary = calibration_note + summary
    return {
        "summary": summary,
        "metrics": [
            {"label": "复核事件", "value": len(records)},
            {"label": "服务数量", "value": len(times)},
            {"label": "确定有向关联", "value": len(certain_links)},
            {"label": "含待定关联", "value": len(pending_links)},
            {"label": "最高确定跟随率", "value": max([row["follow_pct"] for row in rows], default=0), "unit": "%"},
        ],
        "table": {"columns": [
            {"key": "link_id", "label": "服务对编号"},
            {"key": "source", "label": "先发生服务A"},
            {"key": "target", "label": "后继服务B"},
            {"key": "source_events", "label": "A事件数"},
            {"key": "certain_follow_count", "label": "确定跟随次数"},
            {"key": "pending_follow_count", "label": "待定跟随次数"},
            {"key": "follow_pct", "label": "确定跟随率(%)"},
            {"key": "pending_pct", "label": "待定占比(%)"},
            {"key": "median_lag_min", "label": "中位可行时滞(min)"},
            {"key": "lag_low_min", "label": "可行时滞下限(min)"},
            {"key": "lag_high_min", "label": "可行时滞上限(min)"},
            {"key": "certainty", "label": "判定"},
            {"key": "jaccard", "label": "同窗Jaccard(原始读数)"},
            {"key": "shared_windows", "label": "共同占用窗"},
        ], "rows": rows},
        "chart": {"type": "bar", "labels": [row["link_id"] for row in top], "series": (
            [
                {"name": "确定跟随率%（服务对编号见明细）", "values": [row["follow_pct"] for row in top]},
                {"name": "待定占比%（服务对编号见明细）", "values": [row["pending_pct"] for row in top]},
            ] if top else []
        )},
        "calibration": calibration_block,
        "pending_examples": pending_details[:12],
        "findings": findings,
        "method": metadata()["method"],
        "warnings": ["有向先后关系不是故障因果链，需回查调用与变更记录。"] + (["没有满足阈值的服务对。"] if not rows else [])
        + (["存在待定跟随：校时凭据不能唯一确定先后，需补充凭据或扩大误差范围核对。"] if pending_links else []),
    }
