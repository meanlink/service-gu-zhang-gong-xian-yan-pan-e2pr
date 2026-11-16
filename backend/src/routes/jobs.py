from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Job, CalibrationScheme
from src.schemas.job import JobInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import jobs
from src.services import calibration as calibration_service
from src.services.audit import record
from src.utils.serialization import job_dict, job_detail_dict
router = APIRouter(prefix='/jobs')


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    return [job_dict(j) for j in db.scalars(select(Job).order_by(Job.id.desc()).limit(100))]


@router.post('', status_code=201)
def create(data: JobInput, db=Depends(get_db), u=Depends(can_write)):
    j = jobs.create(db, data, u)
    record(db, u.email, 'job.create', {
        'id': j.id, 'params': j.params,
        'calibration_scheme_id': j.calibration_scheme_id, 'calibration_revision': j.calibration_revision,
    })
    db.commit()
    jobs.enqueue(j.id)
    return job_dict(j)


@router.get('/{id}')
def detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    j = db.get(Job, id)
    if not j:
        raise HTTPException(404, '分析任务不存在')
    return job_detail_dict(j)


@router.post('/{id}/approve')
def approve(id: int, db=Depends(get_db), u=Depends(admin_only)):
    j = db.get(Job, id)
    if not j:
        raise HTTPException(404, '分析任务不存在')
    if j.calibration_scheme_id:
        # 与撤销串行：先锁方案行，再读取其当前状态与修订。
        scheme = calibration_service.locked_scheme(db, j.calibration_scheme_id)
        db.refresh(j)
        if not scheme or scheme.status != 'published':
            raise HTTPException(409, '该试验所依据的校时方案已撤销，拒绝批准。请重新计算。')
        if j.calibration_revision != scheme.revision:
            raise HTTPException(409, '该试验所依据的校时方案已修订，结果失效，拒绝批准。请重新计算。')
    if j.invalidated:
        raise HTTPException(409, '该试验的校时依据已撤销或修订，结果失效，拒绝批准。')
    if j.status != 'completed':
        raise HTTPException(409, '仅已完成结果可以批准')
    j.approved = True
    record(db, u.email, 'job.approve', {'id': id, 'calibration_revision': j.calibration_revision})
    db.commit()
    return job_dict(j)
