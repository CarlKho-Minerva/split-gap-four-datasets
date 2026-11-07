"""Data parsing only, shared by pre-lock structural inspection and analysis."""
import io
import pickle
from pathlib import Path
import numpy as np

class ArrayUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        allowed = {
            ('numpy.core.multiarray', '_reconstruct'): np.core.multiarray._reconstruct,
            ('numpy.core.multiarray', 'scalar'): np.core.multiarray.scalar,
            ('numpy', 'ndarray'): np.ndarray,
            ('numpy', 'dtype'): np.dtype,
        }
        if (module, name) not in allowed:
            raise pickle.UnpicklingError(f'Forbidden global: {module}.{name}')
        return allowed[(module, name)]

def load_arrays(stream):
    return ArrayUnpickler(stream, encoding='latin1').load()

def edf_header(path):
    with open(path, 'rb') as f:
        h = f.read(256)
        ns = int(h[252:256]); nh = int(h[184:192]); nr = int(h[236:244]); dur = float(h[244:252])
        sh = f.read(ns * 256)
    widths = [16, 80, 8, 8, 8, 8, 8, 80, 8, 32]
    blocks = []; off = 0
    for width in widths:
        blocks.append([sh[off+i*width:off+(i+1)*width].decode('ascii').strip() for i in range(ns)])
        off += width * ns
    return dict(ns=ns, nh=nh, nr=nr, duration=dur, labels=blocks[0],
                pmin=np.array(blocks[3],float), pmax=np.array(blocks[4],float),
                dmin=np.array(blocks[5],float), dmax=np.array(blocks[6],float),
                samples=np.array(blocks[8],int))

def edf_events(path, h=None):
    h = h or edf_header(path)
    ai = h['labels'].index('EDF Annotations'); stride=int(h['samples'].sum())*2
    offset=int(h['samples'][:ai].sum())*2; size=int(h['samples'][ai])*2
    events=[]
    with open(path,'rb') as f:
        for r in range(h['nr']):
            f.seek(h['nh'] + r*stride + offset)
            for tal in f.read(size).split(b'\x00'):
                if b'\x14' not in tal: continue
                time, *annotations = tal.split(b'\x14')
                td=time.split(b'\x15')
                for a in annotations:
                    if a in (b'T0', b'T1', b'T2'):
                        events.append((float(td[0]), float(td[1]) if len(td)>1 else 0., a.decode()))
    return events

def edf_signals(path,h=None):
    h=h or edf_header(path); sizes=h['samples']; stride=int(sizes.sum())
    raw=np.fromfile(path,dtype='<i2',offset=h['nh']).reshape(h['nr'],stride)
    cols=[]; off=0
    for i,n in enumerate(sizes):
        if h['labels'][i] != 'EDF Annotations':
            v=raw[:,off:off+n].reshape(-1).astype(float)
            v=(v-h['dmin'][i])*(h['pmax'][i]-h['pmin'][i])/(h['dmax'][i]-h['dmin'][i])+h['pmin'][i]
            cols.append(v)
        off+=n
    return np.column_stack(cols)
