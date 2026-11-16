import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report
from src.services.business import analyze
from src.services.reports import deliver
from src.services import calibration as calibration_service
from src.services.audit import record
logging.basicConfig(level=logging.INFO)


def _load_snapshot(db, job):
    """只认试验创建时的校时快照；方案之后的变化由失效检查处理。"""
    if not job.calibration_scheme_id:
        return None
    snapshot = job.calibration_snapshot or {}
    solution = snapshot.get('solution') or {}
    if not solution:
        return None
    return {
        'scheme_id': snapshot.get('scheme_id'),
        'name': snapshot.get('name', ''),
        'revision': snapshot.get('revision'),
        'reference': solution.get('reference'),
        'consistent': solution.get('consistent', True),
        'ranges': solution.get('ranges', {}),
        'deltas': solution.get('deltas', {}),
        'conflicts': solution.get('conflicts', []),
    }


def execute(job_id):
    with Session() as db:
        j = db.get(Job, job_id)
        if not j or j.status != 'queued':
            return
        if j.invalidated:
            # 依据已撤销：不得再计算，旧结果也不得晚回并恢复资格。
            j.status = 'failed'
            j.error = (j.invalidation_reason or '校时依据已撤销，试验失效。')[:990]
            j.finished_at = time.time()
            record(db, 'worker', 'job.skipped.invalidated', {'id': j.id})
            db.commit()
            return
        j.status = 'running'
        db.commit()
        try:
            d = db.get(Dataset, j.dataset_id)
            calibration = _load_snapshot(db, j)
            result = analyze(d.records, j.params, calibration)
            json.dumps(result, allow_nan=False)
            # 计算期间方案可能已被撤销或修订：晚回的结果不得恢复资格。
            if j.calibration_scheme_id:
                calibration_service.locked_scheme(db, j.calibration_scheme_id)
                db.refresh(j)
                valid, reason = calibration_service.scheme_is_current(db, j)
                if not valid:
                    j.status = 'completed'
                    j.result = result
                    j.finished_at = time.time()
                    j.invalidated = True
                    j.invalidated_at = j.finished_at
                    j.invalidation_reason = reason
                    j.approved = False
                    record(db, 'worker', 'job.completed.invalidated', {'id': j.id, 'reason': reason})
                    db.commit()
                    return
            j.result = result
            j.status = 'completed'
            j.finished_at = time.time()
            record(db, 'worker', 'job.completed', {'id': j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status = 'failed'; j.error = str(e)[:990]; j.finished_at = time.time()
            record(db, 'worker', 'job.failed', {'id': j.id, 'error': j.error})
        db.commit()


def tick():
    with Session() as db:
        queued = list(db.scalars(select(Job.id).where(Job.status == 'queued').limit(3)))
    for job_id in queued:
        execute(job_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled == True, Report.next_run <= time.time())):
            d = deliver(db, r)
            if d:
                record(db, 'worker', 'report.delivered', {'id': r.id, 'delivery': d.id})
        db.commit()


def recover():
    """中断后恢复：依据已撤销/修订的试验按失效处理，其余重新排队。"""
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status == 'running')):
            valid, reason = calibration_service.scheme_is_current(db, j)
            if not j.calibration_scheme_id or valid:
                j.status = 'queued'
                record(db, 'worker', 'job.recovered', {'id': j.id})
            else:
                j.status = 'failed'
                j.error = ('校时依据已失效，计算中断后不再重试：' + reason)[:990]
                j.invalidated = True
                j.invalidated_at = time.time()
                j.invalidation_reason = reason
                j.approved = False
                record(db, 'worker', 'job.recovered.invalidated', {'id': j.id, 'reason': reason})
        db.commit()


def main():
    r = Redis.from_url(REDIS_URL, socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    recover()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item = r.blpop('analysis:queue', timeout=1)
            if item:
                execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry'); time.sleep(2)


if __name__ == '__main__':
    main()
