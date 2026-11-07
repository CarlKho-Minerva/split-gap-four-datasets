"""Build a LOCAL author-workspace archive, never upload or submit it.

This helper requires manuscript sources and their built PDF. It is not a
candidate-root reproduction command and is not the code/audit candidate builder
used by the revision workflow, which deliberately excludes the manuscript.
npctl package separately creates the author-review packet.
"""
import hashlib
import json
from pathlib import Path
import zipfile
from verify import verify

ROOT = Path(__file__).resolve().parent.parent
required_manuscript = ('paper/ms.tex', 'paper/ms.pdf', 'paper/refs.bib', 'paper/arxiv.sty')
missing = [name for name in required_manuscript if not (ROOT/name).is_file()]
if missing:
    raise SystemExit('Author-workspace operation only; not supported from a code/audit '
                     'candidate root. Reproduce with reproducibility/reproduce.sh instead. '
                     'Missing manuscript files: ' + ', '.join(missing))
verify(ROOT)
paths = set()
for folder in ('analysis', 'reproducibility', 'lit/records', 'paper/tables'):
    for p in (ROOT/folder).rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc':
            paths.add(p)
for p in (ROOT/'results').glob('*.json'):
    if p.name != 'execution_metadata.json':
        paths.add(p)
for name in ('topic.json','provenance.json','prereg.md','deviations.json',
             'paper/ms.tex','paper/ms.pdf','paper/numbers.tex','paper/refs.bib',
             'paper/arxiv.sty','paper/fig_central.pdf'):
    paths.add(ROOT/name)
# Original source documentation is attribution evidence, not analysed raw data.
for pattern in ('data/raw/emg/**/README.txt','data/raw/stress/**/README.txt',
                'data/raw/stress/**/data_constraints.txt','data/raw/stress/**/LICENSE.txt',
                'data/raw/eeg/README.*','data/raw/ppg/extracted/readme.*'):
    paths.update(p for p in ROOT.glob(pattern) if p.is_file())
files = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(paths)}
version = hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
release = ROOT/'release'; release.mkdir(exist_ok=True)
archive = release/f'code-audit-{version[:12]}.zip'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for name in files:
        info = zipfile.ZipInfo(name, date_time=(1980,1,1,0,0,0))
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info,(ROOT/name).read_bytes())
    info=zipfile.ZipInfo('RELEASE_MANIFEST.json',date_time=(1980,1,1,0,0,0))
    info.compress_type=zipfile.ZIP_DEFLATED
    z.writestr(info,json.dumps({'version':version,'files':files},indent=1)+'\n')
record = {'status':'local author-workspace archive, not publicly posted or author-approved',
          'version':version,'archive':str(archive.relative_to(ROOT)),
          'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
          'files':files}
(release/'candidate.json').write_text(json.dumps(record,indent=1)+'\n')
print('Local author-workspace archive:',archive)
print('No upload or submission was performed.')
