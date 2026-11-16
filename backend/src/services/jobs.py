import time
from fastapi import HTTPException
from redis import Redis
from src.config.settings import REDIS_URL
from src.models import Dataset, Job, CalibrationScheme
from src.services.business import metadata
from src.services import calibration as calibration_service


def _dataset_services(dataset):
    services = {str(row.get('service', '')).strip() for row in dataset.records if str(row.get('service', '')).strip()}
    return sorted(services)


def create(db, data, user):
    dataset = db.get(Dataset, data.dataset_id)
    if not dataset:
        raise HTTPException(404, '数据批次不存在')
    allowed = {p['key']: p for p in metadata().get('parameters', [])}
    if set(data.params) - set(allowed):
        raise HTTPException(422, '包含未知分析参数')
    params = {k: p['default'] for k, p in allowed.items()}
    params.update(data.params)
    for key, p in allowed.items():
        v = params[key]
        if p['type'] == 'number':
            try:
                v = float(v)
                if not (p.get('min', -1e9) <= v <= p.get('max', 1e9)):
                    raise ValueError()
                params[key] = v
            except (ValueError, TypeError):
                raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options', [])]:
            raise HTTPException(422, f'{p["label"]} 不是有效选项')
    snapshot = {}
    revision = None
    if data.calibration_scheme_id is not None:
        scheme = db.get(CalibrationScheme, data.calibration_scheme_id)
        calibration_service.validate_for_dataset(db, scheme, _dataset_services(dataset))
        snapshot = calibration_service.snapshot_for_job(db, scheme)
        revision = scheme.revision
    job = Job(
        name=data.name, dataset_id=data.dataset_id, params=params, created_by=user.id,
        created_at=time.time(), status='queued',
        calibration_scheme_id=(snapshot.get('scheme_id') if snapshot else None),
        calibration_revision=revision,
        calibration_snapshot=snapshot,
    )
    db.add(job)
    db.flush()
    return job


def enqueue(job_id):
    try:
        r = Redis.from_url(REDIS_URL); r.rpush('analysis:queue', job_id); r.close()
    except Exception:
        pass  # SQL queued status is the durable fallback
