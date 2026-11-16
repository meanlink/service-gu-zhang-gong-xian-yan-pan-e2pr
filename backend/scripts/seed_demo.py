import time, json
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import (
    User, Dataset, Job, Report, Delivery, Audit,
    CalibrationScheme, CalibrationCredential, CredentialRevocation,
)
from src.services.business import metadata, seed_records, analyze
from src.services import calibration as calibration_service
from src.services.reports import deliver
from src.utils.security import hash_password
from src.utils.serialization import checksum


DEMO_SCHEME = '第45周告警时钟校时方案'
DEMO_CREDENTIALS = [
    ('cache', 'api-gateway', 1.0, 3.0, '网关出口时间戳与缓存写入日志比对'),
    ('api-gateway', 'job-queue', 0.0, 2.0, '队列投递确认与网关访问日志同批比对'),
    ('job-queue', 'metrics-db', -2.0, 0.0, '数据库慢查询时间与队列消费确认比对'),
    ('cache', 'object-store', 3.0, 5.0, '对象存储请求时间与缓存回源日志比对'),
]


def _ensure_scheme(db, actor):
    scheme = db.scalar(select(CalibrationScheme).where(CalibrationScheme.name == DEMO_SCHEME))
    if scheme:
        return scheme
    scheme = CalibrationScheme(
        name=DEMO_SCHEME, reference_service='cache', note='按值班校时记录登记，误差为允许双向偏差。',
        status='published', revision=1, last_reconciled_revision=1,
        created_by=actor, created_at=time.time() - 7200,
        published_by=actor, published_at=time.time() - 7000,
    )
    db.add(scheme)
    db.flush()
    for source, target, lower, upper, note in DEMO_CREDENTIALS:
        db.add(CalibrationCredential(
            scheme_id=scheme.id, source_service=source, target_service=target,
            lower_min=lower, upper_min=upper, note=note, status='active',
            created_by=actor, created_at=time.time() - 7100,
        ))
    db.flush()
    db.add(Audit(actor=actor, action='calibration.scheme.seed', detail={'scheme': scheme.id}, at=time.time()))
    return scheme


def seed():
    migrate()
    with Session() as db:
        for role, name in [('admin', '林知 · 业务负责人'), ('analyst', '陈舟 · 分析员'), ('viewer', '周禾 · 观察员')]:
            email = role + '@demo.local'
            if not db.scalar(select(User).where(User.email == email)):
                db.add(User(email=email, name=name, role=role, password=hash_password('Demo123!')))
        db.flush()
        admin = db.scalar(select(User).where(User.role == 'admin'))
        scheme = _ensure_scheme(db, 'seed')
        m = metadata()
        d = db.scalar(select(Dataset).where(Dataset.name == m['dataset_name']))
        if not d:
            rows = seed_records()
            d = Dataset(name=m['dataset_name'], source=m['short'] + '-202611.csv', records=rows, checksum=checksum(rows), created_at=time.time())
            db.add(d)
            db.flush()
        if not db.scalar(select(Job).where(Job.name == '基线复核 · ' + m['name'])):
            params = {p['key']: p['default'] for p in m.get('parameters', [])}
            snapshot = calibration_service.snapshot_for_job(db, scheme)
            solution = snapshot['solution']
            calibration = {
                'scheme_id': snapshot['scheme_id'], 'name': snapshot['name'], 'revision': snapshot['revision'],
                'reference': solution['reference'], 'consistent': solution['consistent'],
                'ranges': solution['ranges'], 'deltas': solution['deltas'], 'conflicts': solution['conflicts'],
            }
            result = analyze(d.records, params, calibration)
            json.dumps(result, ensure_ascii=False, allow_nan=False)
            j = Job(
                name='基线复核 · ' + m['name'], dataset_id=d.id, params=params, status='completed', result=result,
                created_by=admin.id, created_at=time.time() - 3600, finished_at=time.time() - 3595, approved=True,
                calibration_scheme_id=scheme.id, calibration_revision=scheme.revision, calibration_snapshot=snapshot,
            )
            db.add(j)
            db.flush()
            r = Report(name='每日业务复核简报', job_id=j.id, destination='业务复核组 · 本地收件箱', interval_seconds=86400, next_run=time.time() + 86400, enabled=True)
            db.add(r)
            db.flush()
            deliver(db, r)
            db.add(Audit(actor='seed', action='demo.baseline', detail={'dataset': d.id, 'calibration': scheme.id}, at=time.time()))
        db.commit()
        counts = {
            model.__tablename__: db.scalar(select(func.count()).select_from(model))
            for model in [User, Dataset, Job, Report, Delivery, Audit, CalibrationScheme, CalibrationCredential, CredentialRevocation]
        }
        print(json.dumps(counts, ensure_ascii=False))
        return counts


if __name__ == '__main__':
    seed()
