"""Durable, authority-bounded runtime migration transaction state."""
from __future__ import annotations

import json,re
from dataclasses import asdict,dataclass,replace
from datetime import datetime,timezone
from enum import Enum
from pathlib import Path
from typing import Mapping,Any

from .durable_io import atomic_write_json,canonical_json_bytes,sha256_bytes

_SAFE_ID=re.compile(r'[A-Za-z0-9._-]{1,160}\Z')
_SHA256=re.compile(r'[0-9a-f]{64}\Z')
_SHA40_64=re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')

class MigrationHandoffError(ValueError): pass

class MigrationPhase(str,Enum):
    PREPARED='PREPARED'
    PREDECESSOR_QUIESCED='PREDECESSOR_QUIESCED'
    RUNTIME_ACTIVATED='RUNTIME_ACTIVATED'
    SUCCESSOR_REGISTERED='SUCCESSOR_REGISTERED'
    SUCCESSOR_VERIFIED='SUCCESSOR_VERIFIED'
    PREDECESSOR_CLOSED='PREDECESSOR_CLOSED'
    ROLLED_BACK='ROLLED_BACK'
    BLOCKED='BLOCKED'

_FORWARD={
    MigrationPhase.PREPARED:MigrationPhase.PREDECESSOR_QUIESCED,
    MigrationPhase.PREDECESSOR_QUIESCED:MigrationPhase.RUNTIME_ACTIVATED,
    MigrationPhase.RUNTIME_ACTIVATED:MigrationPhase.SUCCESSOR_REGISTERED,
    MigrationPhase.SUCCESSOR_REGISTERED:MigrationPhase.SUCCESSOR_VERIFIED,
    MigrationPhase.SUCCESSOR_VERIFIED:MigrationPhase.PREDECESSOR_CLOSED,
}
_BINDING_FIELDS={
    'migration_id','project_id','predecessor_run_id','successor_run_id','current_gate','resume_gate',
    'approved_plan_sha256','approved_spec_sha256','authority_core_sha256','predecessor_state_sha256',
    'source_head','target_release_head','target_manifest_sha256','successor_job_spec_sha256',
}

@dataclass(frozen=True,slots=True)
class RuntimeMigrationTransaction:
    migration_id:str; project_id:str; predecessor_run_id:str; successor_run_id:str
    current_gate:str; resume_gate:str
    approved_plan_sha256:str; approved_spec_sha256:str; authority_core_sha256:str
    predecessor_state_sha256:str; source_head:str; target_release_head:str
    target_manifest_sha256:str; successor_job_spec_sha256:str
    phase:MigrationPhase; created_at:str; updated_at:str
    quiesced_state_sha256:str=''; block_reason:str=''; rollback_reason:str=''; transaction_sha256:str=''


def _now()->str: return datetime.now(timezone.utc).isoformat(timespec='seconds')

def _payload(tx:RuntimeMigrationTransaction,*,signed:bool=True)->dict[str,Any]:
    d=asdict(tx); d['phase']=tx.phase.value
    if not signed: d.pop('transaction_sha256',None)
    return d

def _sign(tx:RuntimeMigrationTransaction)->RuntimeMigrationTransaction:
    return replace(tx,transaction_sha256=sha256_bytes(canonical_json_bytes(_payload(tx,signed=False))))

def _validate(tx:RuntimeMigrationTransaction)->None:
    for name in ('migration_id','project_id','predecessor_run_id','successor_run_id','current_gate','resume_gate'):
        if not _SAFE_ID.fullmatch(str(getattr(tx,name))): raise MigrationHandoffError(f'unsafe {name}')
    for name in ('approved_plan_sha256','approved_spec_sha256','authority_core_sha256','predecessor_state_sha256','target_manifest_sha256','successor_job_spec_sha256'):
        if not _SHA256.fullmatch(str(getattr(tx,name))): raise MigrationHandoffError(f'invalid {name}')
    for name in ('source_head','target_release_head'):
        if not _SHA40_64.fullmatch(str(getattr(tx,name))): raise MigrationHandoffError(f'invalid {name}')
    if tx.quiesced_state_sha256 and not _SHA256.fullmatch(tx.quiesced_state_sha256): raise MigrationHandoffError('invalid quiesced_state_sha256')
    if tx.phase in {MigrationPhase.PREDECESSOR_QUIESCED,MigrationPhase.RUNTIME_ACTIVATED,MigrationPhase.SUCCESSOR_REGISTERED,MigrationPhase.SUCCESSOR_VERIFIED,MigrationPhase.PREDECESSOR_CLOSED} and not tx.quiesced_state_sha256:
        raise MigrationHandoffError('quiesced predecessor state binding missing')
    if tx.quiesced_state_sha256 and not _SHA256.fullmatch(tx.quiesced_state_sha256): raise MigrationHandoffError('invalid quiesced_state_sha256')
    if not tx.created_at or not tx.updated_at: raise MigrationHandoffError('transaction timestamps missing')
    expected=sha256_bytes(canonical_json_bytes(_payload(tx,signed=False)))
    if tx.transaction_sha256!=expected: raise MigrationHandoffError('transaction SHA mismatch')

class MigrationStore:
    def __init__(self,root:str|Path)->None:
        self.root=Path(root).absolute()
        if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
            raise MigrationHandoffError('unsafe migration store root')
        self.root.mkdir(parents=True,exist_ok=True)
        if self.root.is_symlink(): raise MigrationHandoffError('unsafe migration store root')

    def path(self,migration_id:str)->Path:
        if not _SAFE_ID.fullmatch(str(migration_id)): raise MigrationHandoffError('unsafe migration id')
        return self.root/f'{migration_id}.json'

    def create(self,spec:Mapping[str,Any])->RuntimeMigrationTransaction:
        if set(spec)!=_BINDING_FIELDS: raise MigrationHandoffError('migration specification fields mismatch')
        now=_now()
        tx=RuntimeMigrationTransaction(**{k:str(spec[k]) for k in _BINDING_FIELDS},phase=MigrationPhase.PREPARED,created_at=now,updated_at=now)
        tx=_sign(tx); _validate(tx)
        path=self.path(tx.migration_id)
        if path.exists(): raise MigrationHandoffError('migration transaction already exists')
        atomic_write_json(path,_payload(tx))
        return tx

    def load(self,migration_id:str)->RuntimeMigrationTransaction:
        path=self.path(migration_id)
        if path.is_symlink() or not path.is_file(): raise MigrationHandoffError('migration transaction missing or unsafe')
        try: raw=json.loads(path.read_text(encoding='utf-8'))
        except Exception as exc: raise MigrationHandoffError('migration transaction malformed') from exc
        expected=set(RuntimeMigrationTransaction.__dataclass_fields__)
        if not isinstance(raw,dict) or set(raw)!=expected: raise MigrationHandoffError('migration transaction fields mismatch')
        try: raw['phase']=MigrationPhase(str(raw['phase'])); tx=RuntimeMigrationTransaction(**raw)
        except Exception as exc: raise MigrationHandoffError('migration transaction values invalid') from exc
        _validate(tx); return tx

    def _save(self,tx:RuntimeMigrationTransaction)->RuntimeMigrationTransaction:
        tx=_sign(replace(tx,updated_at=_now())); _validate(tx); atomic_write_json(self.path(tx.migration_id),_payload(tx)); return tx

    def advance(self,migration_id:str,phase:MigrationPhase,*,updates:Mapping[str,Any]|None=None)->RuntimeMigrationTransaction:
        tx=self.load(migration_id); phase=MigrationPhase(phase)
        if _FORWARD.get(tx.phase)!=phase: raise MigrationHandoffError('illegal migration phase transition')
        changes=dict(updates or {})
        if any(k in _BINDING_FIELDS for k in changes): raise MigrationHandoffError('migration authority/identity binding is immutable')
        if changes:
            if phase != MigrationPhase.PREDECESSOR_QUIESCED or set(changes) != {'quiesced_state_sha256'}:
                raise MigrationHandoffError('unsupported migration transition update')
            qsha=str(changes['quiesced_state_sha256'])
            if tx.quiesced_state_sha256 or not _SHA256.fullmatch(qsha):
                raise MigrationHandoffError('invalid quiesced predecessor state binding')
            tx=replace(tx,quiesced_state_sha256=qsha)
        return self._save(replace(tx,phase=phase,block_reason='',rollback_reason=''))

    def block(self,migration_id:str,reason:str)->RuntimeMigrationTransaction:
        tx=self.load(migration_id)
        if tx.phase in {MigrationPhase.PREDECESSOR_CLOSED,MigrationPhase.ROLLED_BACK}: raise MigrationHandoffError('terminal migration cannot be blocked')
        if not str(reason).strip(): raise MigrationHandoffError('block reason required')
        return self._save(replace(tx,phase=MigrationPhase.BLOCKED,block_reason=str(reason).strip()))

    def rollback(self,migration_id:str,reason:str)->RuntimeMigrationTransaction:
        tx=self.load(migration_id)
        if tx.phase in {MigrationPhase.PREDECESSOR_CLOSED,MigrationPhase.ROLLED_BACK}: raise MigrationHandoffError('migration rollback is no longer legal')
        if not str(reason).strip(): raise MigrationHandoffError('rollback reason required')
        return self._save(replace(tx,phase=MigrationPhase.ROLLED_BACK,rollback_reason=str(reason).strip()))


def migration_store_root(harness_root: str | Path, project_id: str) -> Path:
    if not _SAFE_ID.fullmatch(str(project_id or '')):
        raise MigrationHandoffError('unsafe migration project id')
    return Path(harness_root).resolve() / '_workspace' / 'runtime-migrations' / str(project_id)


def discover_predecessor_transactions(harness_root: str | Path, project_id: str, run_id: str) -> tuple[RuntimeMigrationTransaction, ...]:
    root = migration_store_root(harness_root, project_id)
    if not root.exists():
        return ()
    if root.is_symlink() or not root.is_dir():
        raise MigrationHandoffError('unsafe migration store root')
    store = MigrationStore(root)
    found: list[RuntimeMigrationTransaction] = []
    for path in sorted(root.glob('*.json')):
        if path.is_symlink() or not path.is_file():
            raise MigrationHandoffError('unsafe migration transaction file')
        tx = store.load(path.stem)
        if tx.project_id == project_id and tx.predecessor_run_id == run_id:
            found.append(tx)
    return tuple(found)
