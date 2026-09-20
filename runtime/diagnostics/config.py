"""Safe configuration for the authority-free diagnostic intelligence plane."""
from __future__ import annotations
import json,os,stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
class DiagnosticConfigError(ValueError): pass
_VALID_MODES=frozenset({'OFF','SHADOW','ADVISORY'})
def _positive(value,name):
 try: n=int(value)
 except Exception as exc: raise DiagnosticConfigError(f'{name} must be an integer') from exc
 if n<=0: raise DiagnosticConfigError(f'{name} must be positive')
 return n
@dataclass(frozen=True,slots=True)
class DiagnosticConfig:
 enabled:bool=False; mode:str='OFF'; max_result_bytes:int=262144; max_context_chars:int=12000; graphify_cli:str=''; codegraph_binary:str=''
 @classmethod
 def load(cls,path:str|Path):
  p=Path(path).expanduser()
  if not p.is_absolute() or p.is_symlink() or not p.is_file(): raise DiagnosticConfigError('diagnostic config must be absolute regular non-symlink file')
  st=p.stat()
  if st.st_uid!=os.getuid() or st.st_mode & (stat.S_IWGRP|stat.S_IWOTH): raise DiagnosticConfigError('diagnostic config ownership/permissions are unsafe')
  try: d=json.loads(p.read_text())
  except Exception as exc: raise DiagnosticConfigError('diagnostic config is malformed') from exc
  mode=str(d.get('mode','OFF')).upper()
  if mode not in _VALID_MODES: raise DiagnosticConfigError('unsupported diagnostic mode')
  g=Path(str(d.get('graphify_cli',''))).expanduser(); c=Path(str(d.get('codegraph_binary',''))).expanduser()
  if mode in {'SHADOW','ADVISORY'}:
   for x in (g,c):
    if not x.is_absolute() or x.is_symlink() or not x.is_file() or not os.access(x,os.X_OK): raise DiagnosticConfigError('diagnostic binary path is invalid')
  return cls(bool(d.get('enabled',False)),mode,_positive(d.get('max_result_bytes',262144),'max_result_bytes'),_positive(d.get('max_context_chars',12000),'max_context_chars'),str(g),str(c))
 @classmethod
 def from_env(cls,env:Mapping[str,str]|None=None):
  e=dict(os.environ if env is None else env); raw=str(e.get('GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED','false')).lower()
  enabled=raw in {'true','1','yes','on'}
  if raw not in {'true','false','1','0','yes','no','on','off'}: raise DiagnosticConfigError('GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED is invalid')
  if not enabled: return cls()
  config=str(e.get('GCH_DIAGNOSTIC_CONFIG',''))
  if config: return cls.load(config)
  mode=str(e.get('GCH_DIAGNOSTIC_INTELLIGENCE_MODE','OFF')).upper()
  if mode not in _VALID_MODES: raise DiagnosticConfigError('unsupported diagnostic mode')
  if mode=='OFF': return cls()
  return cls(True,mode,_positive(e.get('GCH_DIAGNOSTIC_MAX_RESULT_BYTES',262144),'GCH_DIAGNOSTIC_MAX_RESULT_BYTES'),_positive(e.get('GCH_DIAGNOSTIC_MAX_CONTEXT_CHARS',12000),'GCH_DIAGNOSTIC_MAX_CONTEXT_CHARS'))
