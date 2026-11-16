import time, os, csv, io, hashlib, json
from fastapi import HTTPException
from sqlalchemy import select
from src.models import Job, Report, Delivery, CalibrationScheme
from src.services.calibration import locked_scheme
from src.config.settings import ARTIFACT_DIR


def active_basis(db, job):
    """返回 (可用?, 说明)。已批准试验还须校时方案仍为已发布且修订一致。"""
    if not job:
        return False, '分析任务不存在'
    if getattr(job, 'invalidated', False):
        return False, job.invalidation_reason or '该试验的校时依据已撤销，结果失效。'
    scheme_id = getattr(job, 'calibration_scheme_id', None)
    if not scheme_id:
        return True, ''
    scheme = db.get(CalibrationScheme, scheme_id)
    if not scheme or scheme.status != 'published':
        return False, '该试验所依据的校时方案已撤销，结果失效。请重新计算后再批准或分发。'
    if getattr(job, 'calibration_revision', None) != scheme.revision:
        return False, f'该试验依据的校时方案已修订（依据修订 {job.calibration_revision}，当前 {scheme.revision}），结果失效，请重新计算。'
    return True, ''


def lock_scheme(db, job):
    """与撤销串行：若试验带校时方案，先锁该方案行，再读取其当前状态。"""
    scheme_id = getattr(job, 'calibration_scheme_id', None)
    if not scheme_id:
        return None
    scheme = locked_scheme(db, scheme_id)
    db.refresh(job)
    return scheme


def create(db, data):
    j = db.get(Job, data.job_id)
    if not j or j.status != 'completed':
        raise HTTPException(409, '请先选择已完成且获批准的分析结果')
    lock_scheme(db, j)
    ok, reason = active_basis(db, j)
    if not ok:
        raise HTTPException(409, '不能建立分发计划：' + reason)
    if not j.approved:
        raise HTTPException(409, '请先选择已完成且获批准的分析结果')
    r = Report(name=data.name, job_id=j.id, destination=data.destination, interval_seconds=data.interval_seconds, next_run=time.time() + data.delay_seconds, enabled=True)
    db.add(r); db.flush()
    return r


def _mark_delivery_revoked(delivery, note, when):
    if not delivery.basis_revoked:
        delivery.basis_revoked = True
        delivery.basis_revoked_at = when
        delivery.revocation_note = note


def deliver(db, report):
    """生成一份新归档。校时依据撤销/修订时拒绝新分发，并把已发归档标注依据撤销。"""
    # 与撤销共用方案行锁：两者对这个方案串行，避免漏拦截。
    job = db.get(Job, report.job_id)
    scheme_id = getattr(job, 'calibration_scheme_id', None) if job else None
    if job:
        lock_scheme(db, job)
    ok, reason = active_basis(db, job) if job else (False, '分析任务不存在')
    if not ok:
        when = time.time()
        note = '依据撤销：' + reason
        for delivery in db.scalars(select(Delivery).where(Delivery.report_id == report.id)):
            _mark_delivery_revoked(delivery, note, when)
        if not report.basis_revoked:
            report.basis_revoked = True
            report.basis_revoked_at = when
            report.revocation_note = note
        report.enabled = False
        return None
    out = io.StringIO()
    out.write('﻿')
    table = job.result.get('table', {})
    cols = table.get('columns', [])
    writer = csv.writer(out)
    def safe(v):
        if isinstance(v, (int, float)) and not isinstance(v, bool): return v
        text = str(v)
        return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r')) else text
    writer.writerow([safe(c['label']) for c in cols])
    for row in table.get('rows', []): writer.writerow([safe(row.get(c['key'], '')) for c in cols])
    data = out.getvalue().encode('utf-8')
    delivery = Delivery(
        report_id=report.id, created_at=time.time(), checksum=hashlib.sha256(data).hexdigest(),
        filename='', destination=report.destination,
        calibration_scheme_id=scheme_id,
        calibration_revision=getattr(job, 'calibration_revision', None),
    )
    db.add(delivery); db.flush()
    delivery.filename = f'report-{report.id}-delivery-{delivery.id}.csv'
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    with open(os.path.join(ARTIFACT_DIR, delivery.filename), 'wb') as f: f.write(data)
    with open(os.path.join(ARTIFACT_DIR, delivery.filename + '.json'), 'w') as f:
        json.dump({
            'job': job.name, 'params': job.params, 'result': job.result, 'checksum': delivery.checksum,
            'calibration': getattr(job, 'calibration_snapshot', None) or None,
        }, f, ensure_ascii=False, allow_nan=False)
    report.next_run = time.time() + report.interval_seconds
    return delivery
