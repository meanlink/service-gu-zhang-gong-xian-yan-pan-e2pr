"""校时方案：草稿登记、发布选用、凭据撤销与依赖材料失效。

一致性由 clockgraph 计算；撤销带修订号与唯一登记表，确保并发重试只生效一次。
"""
from __future__ import annotations

import math
import time

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from src.models import (
    CalibrationScheme,
    CalibrationCredential,
    CredentialRevocation,
    Delivery,
    Job,
    Report,
)
from src.services import audit as audit_service
from src.services import clockgraph

MAX_SPAN = 10080.0  # 一周（分钟），防止明显单位错误


def _now():
    return time.time()


def locked_scheme(db, scheme_id):
    """带行锁并强制从数据库重新读取，避免并发撤销/发布时用到旧修订号。"""
    if scheme_id is None:
        return None
    return db.scalar(
        select(CalibrationScheme)
        .where(CalibrationScheme.id == scheme_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _solution_for(db, scheme):
    credentials = list(db.scalars(
        select(CalibrationCredential)
        .where(CalibrationCredential.scheme_id == scheme.id, CalibrationCredential.status == 'active')
        .order_by(CalibrationCredential.id)
    ))
    payload = [
        {
            'id': credential.id,
            'source': credential.source_service,
            'target': credential.target_service,
            'lower': credential.lower_min,
            'upper': credential.upper_min,
        }
        for credential in credentials
    ]
    return clockgraph.solve(payload, scheme.reference_service)


def solution_for(db, scheme):
    """供路由回查的公开入口，返回一致性与可行区间、冲突链。"""
    return _public_solution(_solution_for(db, scheme))


def _public_solution(solution):
    return {
        'reference': solution['reference'],
        'consistent': solution['consistent'],
        'services': solution['services'],
        'components': solution['components'],
        'ranges': solution['ranges'],
        'deltas': solution['deltas'],
        'conflicts': solution['conflicts'],
        'unreachable': solution['unreachable'],
    }


def scheme_dict(db, scheme, detail=False):
    solution = _solution_for(db, scheme)
    base = {
        'id': scheme.id,
        'name': scheme.name,
        'reference_service': scheme.reference_service,
        'note': scheme.note,
        'status': scheme.status,
        'revision': scheme.revision,
        'revocation_note': scheme.revocation_note,
        'created_by': scheme.created_by,
        'created_at': scheme.created_at,
        'published_by': scheme.published_by,
        'published_at': scheme.published_at,
        'consistent': solution['consistent'],
        'conflict_count': len(solution['conflicts']),
        'service_count': len([
            name for name in solution['services'] if solution['ranges'].get(name, {}).get('reachable')
        ]),
        'selected_jobs': db.scalar(
            select(func.count()).select_from(Job).where(Job.calibration_scheme_id == scheme.id)
        ) or 0,
    }
    if not detail:
        return base
    credentials = list(db.scalars(
        select(CalibrationCredential)
        .where(CalibrationCredential.scheme_id == scheme.id)
        .order_by(CalibrationCredential.id)
    ))
    impacted_jobs = list(db.scalars(select(Job).where(Job.calibration_scheme_id == scheme.id).order_by(Job.id.desc())))
    job_ids = [job.id for job in impacted_jobs]
    impacted_reports = list(db.scalars(select(Report).where(Report.job_id.in_(job_ids)).order_by(Report.id.desc()))) if job_ids else []
    report_ids = [report.id for report in impacted_reports]
    impacted_deliveries = list(db.scalars(select(Delivery).where(Delivery.report_id.in_(report_ids)).order_by(Delivery.id.desc()))) if report_ids else []
    base.update({
        'credentials': [credential_dict(item) for item in credentials],
        'solution': _public_solution(solution),
        'affected': {
            'jobs': [affected_job(job) for job in impacted_jobs],
            'reports': [affected_report(report) for report in impacted_reports],
            'deliveries': [affected_delivery(delivery) for delivery in impacted_deliveries],
        },
    })
    return base


def credential_dict(credential):
    return {
        'id': credential.id,
        'scheme_id': credential.scheme_id,
        'source_service': credential.source_service,
        'target_service': credential.target_service,
        'lower_min': credential.lower_min,
        'upper_min': credential.upper_min,
        'note': credential.note,
        'status': credential.status,
        'created_by': credential.created_by,
        'created_at': credential.created_at,
        'revoked_by': credential.revoked_by,
        'revoked_at': credential.revoked_at,
    }


def affected_job(job):
    return {
        'id': job.id,
        'name': job.name,
        'status': job.status,
        'approved': job.approved,
        'invalidated': job.invalidated,
        'invalidation_reason': job.invalidation_reason,
        'invalidated_at': job.invalidated_at,
        'calibration_revision': job.calibration_revision,
    }


def affected_report(report):
    return {
        'id': report.id,
        'name': report.name,
        'job_id': report.job_id,
        'enabled': report.enabled,
        'basis_revoked': report.basis_revoked,
        'basis_revoked_at': report.basis_revoked_at,
        'revocation_note': report.revocation_note,
    }


def affected_delivery(delivery):
    return {
        'id': delivery.id,
        'report_id': delivery.report_id,
        'filename': delivery.filename,
        'created_at': delivery.created_at,
        'calibration_revision': delivery.calibration_revision,
        'basis_revoked': delivery.basis_revoked,
        'basis_revoked_at': delivery.basis_revoked_at,
        'revocation_note': delivery.revocation_note,
    }


def create_scheme(db, data, actor):
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '方案名称去除空格后至少需要两个字符')
    reference = data.reference_service.strip()
    if not reference:
        raise HTTPException(422, '请填写参考服务')
    if db.scalar(select(CalibrationScheme).where(CalibrationScheme.name == name)):
        raise HTTPException(409, '该校时方案名已存在，请修改名称')
    scheme = CalibrationScheme(
        name=name,
        reference_service=reference,
        note=(data.note or '').strip(),
        status='draft',
        revision=0,
        last_reconciled_revision=0,
        created_by=actor,
        created_at=_now(),
    )
    db.add(scheme)
    db.flush()
    audit_service.record(db, actor, 'calibration.scheme.create', {'id': scheme.id, 'reference': reference})
    return scheme


def add_credential(db, scheme, data, actor):
    scheme = locked_scheme(db, scheme.id)
    if scheme.status == 'revoked':
        raise HTTPException(409, '方案已撤销，不能继续登记凭据')
    for value, label in ((data.lower_min, '下限'), (data.upper_min, '上限')):
        if not math.isfinite(value):
            raise HTTPException(422, f'{label}必须为有限数值')
        if abs(value) > MAX_SPAN:
            raise HTTPException(422, f'{label}超出一周范围，请核对单位是否为分钟')
    lower = float(data.lower_min)
    upper = float(data.upper_min)
    if lower > upper:
        raise HTTPException(422, '允许误差下限不能大于上限')
    source = data.source_service.strip()
    target = data.target_service.strip()
    if not source or not target:
        raise HTTPException(422, '凭据的源服务与目标服务不能为空')
    if source == target:
        raise HTTPException(422, '凭据源服务与目标服务不能相同')
    duplicate = db.scalar(select(CalibrationCredential).where(
        CalibrationCredential.scheme_id == scheme.id,
        CalibrationCredential.source_service == source,
        CalibrationCredential.target_service == target,
        CalibrationCredential.status == 'active',
    ))
    if duplicate:
        raise HTTPException(409, '该服务对已有有效凭据；如需更改请先撤销原凭据，再登记新凭据（保留撤销记录）')
    credential = CalibrationCredential(
        scheme_id=scheme.id,
        source_service=source,
        target_service=target,
        lower_min=lower,
        upper_min=upper,
        note=(data.note or '').strip(),
        status='active',
        created_by=actor,
        created_at=_now(),
    )
    db.add(credential)
    db.flush()
    if scheme.status == 'published':
        # 已发布方案的凭据集合变化即视为依据变化：提升修订号并失效依赖材料。
        scheme.revision += 1
        invalidation = (
            f'校时方案“{scheme.name}”新增凭据 #{credential.id}'
            f'（{source}→{target}），修订至 {scheme.revision}'
        )
        _mark_material_invalid(db, scheme, scheme.revision, invalidation, actor)
    audit_service.record(db, actor, 'calibration.credential.create', {
        'scheme': scheme.id, 'credential': credential.id, 'source': source, 'target': target,
        'lower': lower, 'upper': upper, 'revision': scheme.revision,
    })
    return credential


def publish(db, scheme, actor):
    if scheme.status == 'revoked':
        raise HTTPException(409, '方案已撤销，不能重新发布')
    if scheme.status == 'published':
        return scheme
    solution = _solution_for(db, scheme)
    active = db.scalar(select(func.count()).select_from(CalibrationCredential).where(
        CalibrationCredential.scheme_id == scheme.id, CalibrationCredential.status == 'active'
    )) or 0
    if not active:
        raise HTTPException(422, '方案至少需要一条有效凭据才能发布')
    if not solution['consistent']:
        chains = [entry['message'] for entry in solution['conflicts']]
        raise HTTPException(422, '凭据相互矛盾，不能发布：' + ' | '.join(chains))
    reachable = [name for name in solution['services'] if solution['ranges'].get(name, {}).get('reachable')]
    if len(reachable) < 2:
        raise HTTPException(422, '方案需要至少覆盖两个服务才可发布')
    scheme.status = 'published'
    scheme.published_by = actor
    scheme.published_at = _now()
    scheme.revision += 1
    scheme.last_reconciled_revision = scheme.revision
    audit_service.record(db, actor, 'calibration.scheme.publish', {'id': scheme.id, 'revision': scheme.revision})
    return scheme


def _mark_material_invalid(db, scheme, revision, reason, actor):
    """把方案当前修订之前的依赖试验与材料标记失效；调用方负责提交。"""
    jobs = list(db.scalars(select(Job).where(Job.calibration_scheme_id == scheme.id)))
    now = _now()
    invalidated_jobs = []
    for job in jobs:
        if job.invalidated:
            continue
        if job.calibration_revision is not None and job.calibration_revision > revision:
            continue
        job.invalidated = True
        job.invalidated_at = now
        job.invalidation_reason = reason
        if job.approved:
            job.approved = False
        invalidated_jobs.append(job)
    if invalidated_jobs:
        job_ids = [job.id for job in invalidated_jobs]
        reports = list(db.scalars(select(Report).where(Report.job_id.in_(job_ids))))
        for report in reports:
            if not report.basis_revoked:
                report.basis_revoked = True
                report.basis_revoked_at = now
                report.revocation_note = reason
            report.enabled = False
        report_ids = [report.id for report in reports]
        if report_ids:
            for delivery in db.scalars(select(Delivery).where(Delivery.report_id.in_(report_ids))):
                delivery.basis_revoked = True
                delivery.basis_revoked_at = now
                delivery.revocation_note = reason
    audit_service.record(db, actor, 'calibration.materials.invalidate', {
        'scheme': scheme.id,
        'revision': revision,
        'jobs': [job.id for job in invalidated_jobs],
        'reason': reason,
    })
    return invalidated_jobs


def revoke_credential(db, scheme, credential_id, reason, actor):
    """撤销凭据：锁定方案行、提升修订号并失效依赖材料；重复撤销返回已存在记录。"""
    scheme = locked_scheme(db, scheme.id)
    credential = db.get(CalibrationCredential, credential_id)
    if not credential or credential.scheme_id != scheme.id:
        raise HTTPException(404, '凭据不存在')
    existing = db.scalar(select(CredentialRevocation).where(CredentialRevocation.credential_id == credential.id))
    if credential.status == 'revoked' or existing:
        return credential, False
    now = _now()
    reason = (reason or '').strip() or '凭据撤销'
    credential.status = 'revoked'
    credential.revoked_by = actor
    credential.revoked_at = now
    scheme.revision += 1
    registration = CredentialRevocation(
        credential_id=credential.id,
        scheme_id=scheme.id,
        reason=reason,
        requested_by=actor,
        at=now,
        revision=scheme.revision,
    )
    db.add(registration)
    try:
        db.flush()
    except IntegrityError:
        # 并发重试：另一事务已登记撤销，本事务整体回退并返回既存结果，不重复登记。
        db.rollback()
        credential = db.get(CalibrationCredential, credential_id)
        return credential, False
    invalidation = (
        f'校时凭据 #{credential.id}（{credential.source_service}→{credential.target_service}）'
        f'已撤销，方案“{scheme.name}”修订至 {scheme.revision}：{reason}'
    )
    _mark_material_invalid(db, scheme, scheme.revision, invalidation, actor)
    audit_service.record(db, actor, 'calibration.credential.revoke', {
        'scheme': scheme.id, 'credential': credential.id, 'revision': scheme.revision, 'reason': reason,
    })
    return credential, True


def revoke_scheme(db, scheme, reason, actor):
    scheme = locked_scheme(db, scheme.id)
    if scheme.status == 'revoked':
        return scheme
    now = _now()
    reason = (reason or '').strip() or '方案撤销'
    scheme.status = 'revoked'
    scheme.revocation_note = reason
    scheme.revision += 1
    for credential in db.scalars(select(CalibrationCredential).where(CalibrationCredential.scheme_id == scheme.id)):
        if credential.status != 'revoked':
            credential.status = 'revoked'
            credential.revoked_by = actor
            credential.revoked_at = now
    invalidation = f'校时方案“{scheme.name}”已撤销（修订 {scheme.revision}）：{reason}'
    _mark_material_invalid(db, scheme, scheme.revision, invalidation, actor)
    audit_service.record(db, actor, 'calibration.scheme.revoke', {
        'scheme': scheme.id, 'revision': scheme.revision, 'reason': reason,
    })
    return scheme


def validate_for_dataset(db, scheme, services):
    """试验选用前的检查：方案已发布、凭据一致、数据集内全部服务与参考联通。"""
    if scheme is None:
        raise HTTPException(404, '校时方案不存在')
    if scheme.status == 'revoked':
        raise HTTPException(409, '校时方案已撤销，不能用于新的分析试验')
    if scheme.status != 'published':
        raise HTTPException(409, '校时方案尚未发布，不能用于分析试验')
    solution = _solution_for(db, scheme)
    leaf = _public_solution(solution)
    if not solution['consistent']:
        raise HTTPException(422, '校时方案凭据相互矛盾，不能联合分析：' + ' | '.join(
            entry['message'] for entry in solution['conflicts']
        ))
    disconnected = clockgraph.disconnected_services(solution, services)
    if disconnected:
        detail = '；'.join('、'.join(group) for group in disconnected)
        raise HTTPException(422, f'服务 {detail} 与参考服务“{scheme.reference_service}”之间没有可用的校时凭据链，拒绝联合分析。请补充凭据或分开分析。')
    return leaf


def snapshot_for_job(db, scheme):
    solution = _solution_for(db, scheme)
    credentials = list(db.scalars(
        select(CalibrationCredential)
        .where(CalibrationCredential.scheme_id == scheme.id, CalibrationCredential.status == 'active')
        .order_by(CalibrationCredential.id)
    ))
    return {
        'scheme_id': scheme.id,
        'name': scheme.name,
        'revision': scheme.revision,
        'reference': scheme.reference_service,
        'solution': _public_solution(solution),
        'credentials': [credential_dict(item) for item in credentials],
        'captured_at': _now(),
    }


def scheme_is_current(db, job):
    """判断试验快照的校时依据是否仍然有效（撤销或修订变更都视为失效）。"""
    if not job.calibration_scheme_id:
        return True, ''
    scheme = db.get(CalibrationScheme, job.calibration_scheme_id)
    if not scheme or scheme.status != 'published':
        return False, '校时方案已撤销，不能继续沿用该计算依据。'
    if job.calibration_revision != scheme.revision:
        return False, f'校时方案已修订（试验依据修订 {job.calibration_revision}，当前 {scheme.revision}），请重新计算。'
    return True, ''


def scheme_is_current(db, job):
    """判断试验快照的校时依据是否仍然有效（撤销或修订变更都视为失效）。"""
    if not job.calibration_scheme_id:
        return True, ''
    scheme = db.get(CalibrationScheme, job.calibration_scheme_id)
    if not scheme or scheme.status != 'published':
        return False, '校时方案已撤销，不能继续沿用该计算依据。'
    if job.calibration_revision != scheme.revision:
        return False, f'校时方案已修订（试验依据修订 {job.calibration_revision}，当前 {scheme.revision}），请重新计算。'
    return True, ''
