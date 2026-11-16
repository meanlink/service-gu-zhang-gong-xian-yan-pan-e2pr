from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import CalibrationScheme, CredentialRevocation
from src.schemas.calibration import (
    CalibrationSchemeInput, CalibrationCredentialInput, CredentialRevocationInput,
    SchemeRevocationInput,
)
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import calibration as service
from src.services import clockgraph
router = APIRouter(prefix='/calibrations')


def _load(db, scheme_id, lock=False):
    if lock:
        scheme = service.locked_scheme(db, scheme_id)
    else:
        scheme = db.scalar(select(CalibrationScheme).where(CalibrationScheme.id == scheme_id))
    if not scheme:
        raise HTTPException(404, '校时方案不存在')
    return scheme


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    return [service.scheme_dict(db, scheme) for scheme in db.scalars(
        select(CalibrationScheme).order_by(CalibrationScheme.id.desc())
    )]


@router.post('', status_code=201)
def create(data: CalibrationSchemeInput, db=Depends(get_db), u=Depends(can_write)):
    scheme = service.create_scheme(db, data, u.email)
    db.commit()
    return service.scheme_dict(db, scheme, detail=True)


@router.get('/{scheme_id}')
def detail(scheme_id: int, db=Depends(get_db), u=Depends(current_user)):
    return service.scheme_dict(db, _load(db, scheme_id), detail=True)


@router.post('/{scheme_id}/credentials', status_code=201)
def add_credential(scheme_id: int, data: CalibrationCredentialInput, db=Depends(get_db), u=Depends(can_write)):
    scheme = _load(db, scheme_id, lock=True)
    credential = service.add_credential(db, scheme, data, u.email)
    db.commit()
    return service.credential_dict(credential)


@router.get('/{scheme_id}/range')
def range_query(scheme_id: int, source: str, target: str, db=Depends(get_db), u=Depends(current_user)):
    scheme = _load(db, scheme_id)
    solution = service.solution_for(db, scheme)
    if not solution['consistent']:
        raise HTTPException(409, '校时凭据相互矛盾，无法求可行时间范围：' + ' | '.join(
            entry['message'] for entry in solution['conflicts']
        ))
    low, high = clockgraph.feasible_delta(solution, source, target) or (None, None)
    if low is None:
        raise HTTPException(422, f'服务 {source} 与 {target} 之间没有可用校时链，拒绝联合分析')
    return {
        'scheme_id': scheme.id, 'revision': scheme.revision,
        'source': source, 'target': target,
        'lower_min': low, 'upper_min': high,
        'ranges': solution['ranges'],
        'conflicts': [],
    }


@router.post('/{scheme_id}/publish')
def publish(scheme_id: int, db=Depends(get_db), u=Depends(admin_only)):
    scheme = _load(db, scheme_id, lock=True)
    service.publish(db, scheme, u.email)
    db.commit()
    return service.scheme_dict(db, scheme, detail=True)


@router.post('/{scheme_id}/credentials/{credential_id}/revoke')
def revoke_credential(scheme_id: int, credential_id: int, data: CredentialRevocationInput,
                      db=Depends(get_db), u=Depends(admin_only)):
    scheme = _load(db, scheme_id)
    credential, created = service.revoke_credential(db, scheme, credential_id, data.reason, u.email)
    if created:
        db.commit()
    else:
        db.rollback()
    return {'revoked': True, 'newly_registered': created, 'credential': service.credential_dict(credential)}


@router.post('/{scheme_id}/revoke')
def revoke_scheme(scheme_id: int, data: SchemeRevocationInput, db=Depends(get_db), u=Depends(admin_only)):
    scheme = _load(db, scheme_id)
    service.revoke_scheme(db, scheme, data.reason, u.email)
    db.commit()
    return service.scheme_dict(db, scheme, detail=True)


@router.get('/{scheme_id}/affected')
def affected(scheme_id: int, db=Depends(get_db), u=Depends(current_user)):
    scheme = _load(db, scheme_id)
    payload = service.scheme_dict(db, scheme, detail=True)
    revocations = list(db.scalars(
        select(CredentialRevocation).where(CredentialRevocation.scheme_id == scheme.id).order_by(CredentialRevocation.id)
    ))
    return {
        **payload['affected'],
        'revocations': [
            {'id': item.id, 'credential_id': item.credential_id, 'reason': item.reason,
             'requested_by': item.requested_by, 'at': item.at, 'revision': item.revision}
            for item in revocations
        ],
    }


@router.get('/{scheme_id}/conflicts')
def conflicts(scheme_id: int, db=Depends(get_db), u=Depends(current_user)):
    scheme = _load(db, scheme_id)
    solution = service.solution_for(db, scheme)
    return {
        'scheme_id': scheme.id, 'revision': scheme.revision,
        'consistent': solution['consistent'],
        'conflicts': solution['conflicts'],
        'components': solution['components'],
        'unreachable': solution['unreachable'],
    }
