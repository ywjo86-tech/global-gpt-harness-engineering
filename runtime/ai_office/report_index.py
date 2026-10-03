from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ReportIndexV1:
    report_type: str; target: str; date: str; status: str; purpose: str
    read_when: tuple[str, ...]; summary: tuple[str, ...]
    raw_sections: tuple[str, ...] = ("REPORT_META","PURPOSE","READ_WHEN","SUMMARY")

def _sections(markdown):
    result={}; current=None
    for line in markdown.splitlines():
        if line.startswith("## "): current=line[3:].strip(); result[current]=[]
        elif current is not None: result[current].append(line)
    return result

def extract_report_index(markdown: str) -> ReportIndexV1:
    sections=_sections(markdown); required=("REPORT_META","PURPOSE","READ_WHEN","SUMMARY")
    if any(name not in sections for name in required): raise ValueError("report index sections missing")
    meta={line.split(":",1)[0].strip():line.split(":",1)[1].strip() for line in sections["REPORT_META"] if ":" in line}
    values=lambda name: tuple(line[2:].strip() for line in sections[name] if line.startswith("- ") and line[2:].strip())
    purpose="\n".join(line for line in sections["PURPOSE"] if line).strip()
    read_when=tuple(line.strip() for line in sections["READ_WHEN"] if line.strip())
    return ReportIndexV1(meta.get("report_type",""),meta.get("target",""),meta.get("date",""),meta.get("status",""),purpose,read_when,values("SUMMARY"))

def is_report_relevant(index: ReportIndexV1, target: str, intent: str) -> bool:
    if index.target.casefold()!=target.strip().casefold(): return False
    haystack=" ".join((index.report_type,index.purpose,*index.read_when,*index.summary)).casefold()
    return all(token in haystack for token in intent.casefold().split())
