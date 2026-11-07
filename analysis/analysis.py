"""Locked common-query, count-matched biosignal split comparison.
Use npctl analyze in the authoring pipeline; the bundled runner supports reproduction.
No cached outcome or feature files are used.
"""
from np_pipeline import kit
from pathlib import Path
import datetime as dt
import hashlib
import importlib.metadata as metadata
import json
import sys
import time
import zipfile
import numpy as np
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import KNeighborsClassifier
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from threadpoolctl import threadpool_limits
from data_readers import edf_header, edf_events, edf_signals, load_arrays

cfg = kit.config()
raw = kit.data_dir()
ws = raw.parent.parent
start_time = time.monotonic()
threadpool_limits(limits=1)

# Reproduction must use the recorded environment and the unchanged toolkit copy.
environment_lock = json.loads((ws/'reproducibility/environment.lock.json').read_text())
if sys.version.split()[0] != environment_lock['python']:
    raise RuntimeError('Python version differs from the reproducibility environment')
for package, version in environment_lock['packages'].items():
    if metadata.version(package) != version:
        raise RuntimeError(f'Dependency version differs: {package}')
toolkit_digest = hashlib.sha256(Path(kit.__file__).read_bytes()).hexdigest()
vendored_toolkit = ws/'reproducibility/vendor/np_pipeline/kit.py'
if toolkit_digest != hashlib.sha256(vendored_toolkit.read_bytes()).hexdigest():
    raise RuntimeError('Imported toolkit differs from the pinned byte-preserved copy')


def number(name, value, fmt, desc):
    kit.number(name, value, fmt, desc)


def prefix(v):
    return np.concatenate([np.zeros((1, v.shape[1])), np.cumsum(v, axis=0)], axis=0)


def summary_features(x, starts, ends, emg=False):
    """Per-channel statistics, with nonfinite-window rejection independent of label."""
    x = np.asarray(x, float)
    if x.ndim == 1:
        x = x[:, None]
    valid = np.isfinite(x).all(axis=1)
    bad = np.concatenate([[0], np.cumsum(~valid)])
    good = (bad[ends] - bad[starts]) == 0
    x = np.where(np.isfinite(x), x, 0.)
    n = (ends - starts)[:, None]
    sx = prefix(x); sx2 = prefix(x*x)
    mean = (sx[ends] - sx[starts]) / n
    square = (sx2[ends] - sx2[starts]) / n
    std = np.sqrt(np.maximum(square - mean*mean, 0.))
    rms = np.sqrt(np.maximum(square, 0.))
    dx = prefix(np.abs(np.diff(x, axis=0)))
    successive = (dx[ends-1] - dx[starts]) / (n-1)
    if emg:
        ax = prefix(np.abs(x)); first = (ax[ends] - ax[starts]) / n
    else:
        first = mean
    return np.concatenate([first, rms, std, successive], axis=1), good


def label_segments(y):
    y = np.asarray(y).reshape(-1)
    edges = np.concatenate([[0], np.flatnonzero(y[1:] != y[:-1])+1, [len(y)]])
    return [(a, b, int(y[a])) for a, b in zip(edges[:-1], edges[1:])]


class Windows:
    def __init__(self, key):
        self.key = key
        self.parts = []
        self.dropped = 0
        self.files = set()

    def add(self, x, y, person, recording, file, begin, end, good):
        self.dropped += int((~good).sum())
        if good.any():
            self.files.add(file)
            self.parts.append(dict(x=x[good], y=np.asarray(y, int)[good],
                person=np.repeat(person, good.sum()), recording=np.repeat(recording, good.sum()),
                file=np.repeat(file, good.sum()), begin=np.asarray(begin)[good], end=np.asarray(end)[good]))

    def finish(self):
        if not self.parts:
            raise ValueError(f'No eligible windows: {self.key}')
        d = {k: np.concatenate([p[k] for p in self.parts]) for k in self.parts[0]}
        d['dropped'] = self.dropped; d['file_count'] = len(self.files)
        assert np.isfinite(d['x']).all()
        return d


def emg_data():
    w = Windows('emg')
    root = raw / 'emg/extracted/EMG_data_for_gestures-master'
    length = cfg['emg_window_seconds']; shift = length*(1-cfg['overlap_fraction'])
    for path in sorted(root.glob('*/*.txt')):
        with path.open() as stream:
            header = stream.readline().split()
            lines = stream.readlines()
        malformed = [i for i,line in enumerate(lines) if len(line.split()) != len(header)]
        if malformed:
            if malformed != [len(lines)-1] or len(lines[-1].split()) != len(header)-1:
                raise ValueError(f'Unexpected malformed EMG row: {path}')
            print('Excluded final unlabelled EMG row:',path.name,flush=True)
            lines = lines[:-1]
        d = np.loadtxt(lines)
        del lines
        t = d[:, 0]/cfg['timestamp_units_per_second']
        if not (np.diff(t) > 0).all():
            raise ValueError(f'Nonmonotone EMG timestamps: {path}')
        for a, b, label in label_segments(d[:, -1]):
            if not cfg['emg_label_min'] <= label <= cfg['emg_label_max']:
                continue
            begins = np.arange(t[a], t[b-1]-length+cfg['numeric_floor'], shift)
            ends = begins+length
            si = np.searchsorted(t, begins); ei = np.searchsorted(t, ends)
            ok = (ei <= b) & (ei-si > 1)
            si, ei, begins, ends = si[ok], ei[ok], begins[ok], ends[ok]
            if not len(si): continue
            feats, good = summary_features(d[:, 1:-1], si, ei, emg=True)
            w.add(feats, np.repeat(label, len(si)), path.parent.name,
                int(path.name.split('_')[0]), str(path.relative_to(raw)), begins, ends, good)
    return w.finish()


def wrist_windows(w, signals, rates, person, file, length, segments, offsets=None):
    offsets = offsets or {k: 0. for k in signals}
    lower = max(offsets.values())
    upper = min(offsets[k]+len(v)/rates[k] for k,v in signals.items())
    shift = length*(1-cfg['overlap_fraction'])
    for a, b, label in segments:
        a=max(a, lower); b=min(b, upper)
        begins=np.arange(a, b-length+cfg['numeric_floor'], shift)
        ends=begins+length
        if not len(begins): continue
        all_feats=[]; good=np.ones(len(begins),bool)
        for k in ('ACC', 'BVP', 'EDA', 'TEMP'):
            si=np.rint((begins-offsets[k])*rates[k]).astype(int)
            ei=np.rint((ends-offsets[k])*rates[k]).astype(int)
            assert (si >= 0).all() and (ei <= len(signals[k])).all()
            f,g=summary_features(signals[k],si,ei)
            all_feats.append(f); good &= g
        w.add(np.concatenate(all_feats,axis=1), np.repeat(label,len(begins)), person, 1,
              file, begins, ends, good)


def stress_data():
    w=Windows('stress')
    root=next((raw/'stress/extracted').glob('*'))/'Wearable_Dataset'
    labels={'STRESS': 1, 'AEROBIC': 2, 'ANAEROBIC': 3}
    rates={k: cfg[k.lower()+'_rate'] for k in ('ACC','BVP','EDA','TEMP')}
    for path in sorted(root.glob('*/*')):
        if not path.is_dir(): continue
        person=path.name.split('_')[0]
        if person in cfg['stress_exclude_subjects']: continue
        signals={}; dates={}
        for k in rates:
            p=path/(k+'.csv')
            with p.open() as f:
                dates[k]=dt.datetime.strptime(f.readline().strip().split(',')[0], '%Y-%m-%d %H:%M:%S')
                rate=float(f.readline().split(',')[0])
            if rate != rates[k]: raise ValueError(f'Unexpected rate: {p}')
            signals[k]=np.loadtxt(p,delimiter=',',skiprows=2,ndmin=2)
        origin=min(dates.values())
        offsets={k: (v-origin).total_seconds() for k,v in dates.items()}
        upper=max(offsets[k]+len(v)/rates[k] for k,v in signals.items())
        wrist_windows(w, signals, rates, person, str(path.relative_to(raw)),
                      cfg['stress_window_seconds'], [(0.,upper,labels[path.parent.name])],offsets)
    return w.finish()


def ppg_data():
    w=Windows('ppg')
    rates={k: cfg[k.lower()+'_rate'] for k in ('ACC','BVP','EDA','TEMP')}
    with zipfile.ZipFile(raw/'ppg/extracted/data.zip') as z:
        names=sorted(n for n in z.namelist() if n.endswith('.pkl'))
        for name in names:
            sid=int(Path(name).stem[1:])
            if sid in cfg['ppg_exclude_subjects']: continue
            with z.open(name) as stream: d=load_arrays(stream)
            segments=[(a/cfg['activity_rate'],b/cfg['activity_rate'],label)
                      for a,b,label in label_segments(d['activity'])
                      if cfg['ppg_label_min'] <= label <= cfg['ppg_label_max']]
            wrist_windows(w,d['signal']['wrist'],rates,f'S{sid}',name,
                          cfg['ppg_window_seconds'],segments)
            del d
    return w.finish()


def eeg_data():
    w=Windows('eeg')
    root=raw/'eeg/extracted/files'; rate=cfg['eeg_rate']
    length=int(round(cfg['eeg_window_seconds']*rate))
    step=int(round(length*(1-cfg['overlap_fraction'])))
    freq=np.fft.rfftfreq(length,1/rate)
    bands=[(cfg['theta_low_hz'],cfg['theta_high_hz']),
           (cfg['theta_high_hz'],cfg['alpha_high_hz']),
           (cfg['alpha_high_hz'],cfg['beta_high_hz'])]
    masks=[(freq >= a) & (freq < b) for a,b in bands]
    taper=np.hanning(length)[:,None]
    for path in sorted(root.glob('S*/S*R*.edf')):
        run=int(path.stem[-2:]); sid=int(path.parent.name[1:])
        if run not in cfg['eeg_runs'] or sid in cfg['eeg_exclude_subjects']: continue
        h=edf_header(path)
        channel_indices=[i for i,l in enumerate(h['labels']) if l!='EDF Annotations']
        if len(channel_indices)!=cfg['eeg_channels'] or not all(h['samples'][i]/h['duration']==rate for i in channel_indices):
            raise ValueError(f'Unexpected EEG header: {path}')
        trials=[e for e in edf_events(path,h) if e[2] in ('T1','T2')]
        if len(trials)!=cfg['eeg_trials_per_run'] or any(abs(e[1]-cfg['eeg_trial_seconds'])>cfg['eeg_trial_tolerance_seconds'] for e in trials):
            raise ValueError(f'Unexpected EEG trials: {path}')
        x=edf_signals(path,h)
        feats=[]; ys=[]; begins=[]; ends=[]; goods=[]
        for onset,duration,code in trials:
            a=int(round(onset*rate)); b=min(int(round((onset+duration)*rate)),len(x))
            for s in range(a,b-length+1,step):
                v=x[s:s+length]; good=np.isfinite(v).all()
                if good:
                    v=(v-v.mean(axis=0))*taper
                    power=np.abs(np.fft.rfft(v,axis=0))**2
                    f=np.concatenate([np.log(np.maximum(power[m].mean(axis=0),cfg['numeric_floor'])) for m in masks])
                else:
                    f=np.zeros(cfg['eeg_channels']*len(masks))
                feats.append(f); ys.append(int(code[1:])); begins.append(s/rate); ends.append((s+length)/rate);goods.append(good)
        w.add(np.array(feats),ys,path.parent.name,run,str(path.relative_to(raw)),begins,ends,np.array(goods))
    return w.finish()


def boot_interval(values, indices, alpha):
    means=np.asarray(values)[indices].mean(axis=1)
    return np.quantile(means,[alpha/2,1-alpha/2])


def shared_overlap(d, test, train):
    """Intervals are half-open; no sharing when the endpoints merely touch."""
    hit=[]
    for q in test:
        same=train[d['file'][train]==d['file'][q]]
        hit.append(bool(np.any((d['begin'][same] < d['end'][q]-cfg['numeric_floor']) &
                               (d['end'][same] > d['begin'][q]+cfg['numeric_floor']))))
    return np.mean(hit)


def evaluate(key, d, seed):
    persons=np.unique(d['person']); classes=np.unique(d['y'])
    group=key in ('emg','eeg')
    protocols=['Random','Recording','Person'] if group else ['Random','Person']
    query_run=cfg['emg_test_recording'] if key=='emg' else (max(cfg['eeg_runs']) if key=='eeg' else 1)
    rng=np.random.default_rng(seed.spawn(1)[0])
    scores={model:{p:[] for p in protocols} for model in ('Nn','Lda')}
    overlap=[]; majority=[]; query_counts=[]; train_counts=[]; audit=[]
    for person in persons:
        local=np.flatnonzero(d['person']==person)
        other=np.flatnonzero(d['person']!=person)
        qpool=local[d['recording'][local]==query_run]
        earlier=local[d['recording'][local]!=query_run]
        if not np.array_equal(np.unique(d['y'][local]),classes) or not np.array_equal(np.unique(d['y'][qpool]),classes):
            raise ValueError(f'Missing expected labels: {key}/{person}')
        rep_scores={m:{p:[] for p in protocols} for m in scores}
        po=[]; pm=[]; nq=[]; nt=[]
        for repeat in range(cfg['split_repeats']):
            test=[]
            for label in classes:
                eligible=qpool[d['y'][qpool]==label]
                n=max(cfg['min_test_per_class'],int(np.floor(len(eligible)*cfg['test_fraction'])))
                if n >= len(eligible): raise ValueError(f'Insufficient query windows: {key}/{person}')
                test.extend(rng.choice(eligible,n,replace=False))
            test=np.sort(test)
            pools={'Random':np.setdiff1d(local,test),'Person':other}
            if group: pools['Recording']=earlier
            trains={p:[] for p in protocols}
            for label in classes:
                candidates={p:pool[d['y'][pool]==label] for p,pool in pools.items()}
                n=min(cfg['max_train_per_class'],*(len(v) for v in candidates.values()))
                if n < 1: raise ValueError(f'Empty training class: {key}/{person}')
                for p in protocols: trains[p].extend(rng.choice(candidates[p],n,replace=False))
            trains={p:np.sort(v) for p,v in trains.items()}
            assert len({len(v) for v in trains.values()}) == 1
            for p,train in trains.items():
                assert not np.intersect1d(train,test).size
                if p=='Person': assert not np.any(d['person'][train]==person)
                if p=='Recording': assert not np.any(d['recording'][train]==query_run)
                if p!='Random': assert shared_overlap(d,test,train)==0
                scaler=StandardScaler().fit(d['x'][train])
                xx=scaler.transform(d['x'][train]); xt=scaler.transform(d['x'][test])
                models={'Nn':KNeighborsClassifier(n_neighbors=cfg['nearest_neighbors'],metric='euclidean',algorithm='brute',n_jobs=1),
                        'Lda':LinearDiscriminantAnalysis(solver='lsqr',shrinkage='auto')}
                for m,model in models.items():
                    pred=model.fit(xx,d['y'][train]).predict(xt)
                    rep_scores[m][p].append(float(np.mean(pred==d['y'][test])))
                    audit.append(dict(dataset=key,person=person,repeat=repeat,model=m,protocol=p,
                        query_indices=test.tolist(),train_indices=train.tolist(),true=d['y'][test].tolist(),pred=pred.tolist()))
            po.append(shared_overlap(d,test,trains['Random']))
            pm.append(max(np.mean(d['y'][test]==c) for c in classes))
            nq.append(len(test)); nt.append(len(trains['Random']))
        for m in scores:
            for p in protocols: scores[m][p].append(np.mean(rep_scores[m][p]))
        overlap.append(np.mean(po)); majority.append(np.mean(pm));query_counts.append(sum(nq));train_counts.extend(nt)
    (ws/'results'/f'{key}_predictions.json').write_text(json.dumps(audit))
    # The row index maps every prediction back to its raw-file, participant and window.
    metadata={k:d[k].tolist() for k in ('y','person','recording','file','begin','end')}
    (ws/'results'/f'{key}_windows.json').write_text(json.dumps(metadata))
    indices=np.random.default_rng(seed.spawn(1)[0]).integers(0,len(persons),size=(cfg['bootstrap_resamples'],len(persons)))
    number(key+'N',len(persons),'int',f'{key}: eligible participants')
    number(key+'Classes',len(classes),'int',f'{key}: eligible task classes')
    number(key+'Windows',len(d['y']),'int',f'{key}: eligible windows before query split')
    number(key+'Files',d['file_count'],'int',f'{key}: eligible raw recordings/files')
    number(key+'Dropped',d['dropped'],'int',f'{key}: windows rejected for nonfinite raw samples')
    number(key+'Features',d['x'].shape[1],'int',f'{key}: feature dimensions')
    number(key+'Queries',sum(query_counts),'int',f'{key}: query predictions per model/protocol summed over repeats; windows may recur across repeats')
    number(key+'TrainMin',min(train_counts),'int',f'{key}: smallest selected training-window count per participant/repeat/protocol')
    number(key+'TrainMax',max(train_counts),'int',f'{key}: largest selected training-window count per participant/repeat/protocol')
    number(key+'Chance',1/len(classes),'pct1',f'{key}: uniform random guess expected accuracy')
    number(key+'Majority',np.mean(majority),'pct1',f'{key}: participant-mean query-majority constant-class accuracy (descriptive, query-label oracle)')
    olo,ohi=boot_interval(overlap,indices,cfg['accuracy_interval_alpha'])
    for suffix,value in [('Overlap',np.mean(overlap)),('OverlapLo',olo),('OverlapHi',ohi)]:
        number(key+suffix,value,'pct1',f'{key}: descriptive query/raw-sample sharing proportion, nominal participant interval')
    out={'key':key,'persons':persons.tolist(),'classes':classes.tolist(),'scores':scores,'gaps':{},'overlap':overlap,
         'train_range':[int(min(train_counts)),int(max(train_counts))]}
    for m in scores:
        out['gaps'][m]={}
        for p in protocols:
            vals=scores[m][p]; lo,hi=boot_interval(vals,indices,cfg['accuracy_interval_alpha'])
            for suffix,value in [('Acc',np.mean(vals)),('Lo',lo),('Hi',hi)]:
                number(key+m+p+suffix,value,'pct1',f'{key}/{m}/{p}: participant-mean accuracy; nominal participant percentile interval')
        for p in protocols:
            if p=='Random':continue
            delta=np.array(scores[m]['Random'])-np.array(scores[m][p])
            alpha=cfg['family_alpha']/cfg['comparisons'] if m=='Nn' else cfg['accuracy_interval_alpha']
            lo,hi=boot_interval(delta,indices,alpha)
            margin=cfg['equivalence_margin']
            status=('supported' if lo>margin else 'not supported (equivalent)' if lo>-margin and hi<margin
                    else 'not supported (opposite)' if hi<-margin else 'inconclusive')
            out['gaps'][m][p]=dict(mean=float(delta.mean()),lo=float(lo),hi=float(hi),status=status,participant_gaps=delta.tolist())
            for suffix,value in [('Gap',delta.mean()),('GapLo',lo),('GapHi',hi)]:
                number(key+m+p+suffix,value,'pp1',f'{key}/{m}/{p}: random minus held-out accuracy, percentage points; '+
                      ('Bonferroni-adjusted' if m=='Nn' else 'nominal unadjusted sensitivity')+' participant interval')
    print(key,'participants',len(persons),'windows',len(d['y']),'gaps', {m:{p:{k:v for k,v in r.items() if k!='participant_gaps'} for p,r in gs.items()} for m,gs in out['gaps'].items()},flush=True)
    return out


seeds=np.random.SeedSequence(cfg['seed']).spawn(4)
outputs=[]
for (key,loader),seed in zip([('emg',emg_data),('stress',stress_data),('ppg',ppg_data),('eeg',eeg_data)],seeds):
    print('loading',key,flush=True)
    data=loader()
    outputs.append(evaluate(key,data,seed))
    del data

number('adjustedCoverage',1-cfg['family_alpha']/cfg['comparisons'],'pct2','Per-comparison nominal coverage after Bonferroni correction')
number('nominalCoverage',1-cfg['accuracy_interval_alpha'],'pct0','Nominal descriptive/sensitivity interval coverage')
number('familyCoverage',1-cfg['family_alpha'],'pct0','Target family coverage for six primary gaps')
number('marginPp',cfg['equivalence_margin'],'pp1','Prespecified practical equivalence margin in percentage points')
number('overlapPercent',cfg['overlap_fraction'],'pct0','Configured raw-window overlap percentage')
number('testPercent',cfg['test_fraction'],'pct0','Configured query fraction per class, before flooring')
number('supportedCount',sum(g['status']=='supported' for o in outputs for g in o['gaps']['Nn'].values()),'int','Primary hypotheses supported')
number('eegExcludedCount',len(cfg['eeg_exclude_subjects']),'int','EEG participants excluded by locked header/protocol rules')
number('stressExcludedCount',len(cfg['stress_exclude_subjects']),'int','Stress participants excluded by locked completeness/sensor rules')
number('ppgExcludedCount',len(cfg['ppg_exclude_subjects']),'int','PPG participants excluded for absent activity classes')

names={'emg':'EMG gestures','stress':'Stress/exercise sessions','ppg':'PPG-DaLiA activities','eeg':'EEG imagery'}
short={'emg':'EMG gestures','stress':'Wrist sessions','ppg':'Wrist activities','eeg':'EEG imagery'}
# Display choices are separate from the locked statistical configuration.
style=kit.style({'width_inches':cfg['figure_width_inches'],
                 'height_inches':cfg['figure_height_inches'],
                 'font_points':cfg['figure_font_points'],
                 'gap_min_pp':cfg['figure_gap_min_pp'],
                 'gap_max_pp':cfg['figure_gap_max_pp']})
# Three validated Okabe-Ito colours; the fourth task uses a neutral triangle.
colors={'emg':'#0072B2','stress':'#D55E00','ppg':'#009E73','eeg':kit.INK}
markers={'emg':'o','stress':'s','ppg':'D','eeg':'^'}
panel_titles={'emg':'Muscle signals\nGestures','stress':'Wrist signals\nSessions',
              'ppg':'Wrist signals\nActivities','eeg':'Scalp signals\nImagined movements'}
plt.rcParams.update({'font.size':style['font_points'],
                     'axes.titlesize':style['title_font_points'],
                     'axes.labelsize':style['font_points'],
                     'xtick.labelsize':style['font_points'],
                     'ytick.labelsize':style['font_points'],
                     'text.color':kit.INK,'axes.labelcolor':kit.INK,
                     'xtick.color':kit.INK,'ytick.color':kit.INK,
                     'axes.titlecolor':kit.INK,'axes.edgecolor':kit.RULE,
                     'pdf.fonttype':42})
fig,axs=plt.subplots(1,4,figsize=(style['width_inches'],style['height_inches']),sharex=True,sharey=True)
for ax,o in zip(axs,outputs):
    key=o['key']; gs=o['gaps']['Nn']
    ax.axvspan(-100*cfg['equivalence_margin'],100*cfg['equivalence_margin'],color=kit.BAND,zorder=0)
    ax.axvline(0,color=kit.RULE,lw=style['reference_line_width'])
    for protocol,y in [('Recording',1),('Person',0)]:
        if protocol not in gs:
            ax.text(style['missing_note_x'],y,'No repeat\nrecording',
                    transform=ax.get_yaxis_transform(),fontsize=style['note_font_points'],
                    ha='center',va='center',color=kit.MUTED)
            continue
        g=gs[protocol]; v=np.array([g['mean'],g['lo'],g['hi']])*100
        ax.errorbar(v[0],y,xerr=[[v[0]-v[1]],[v[2]-v[0]]],fmt=markers[key],color=colors[key],
                    capsize=style['cap_points'],ms=style['marker_points'],lw=style['interval_line_width'])
        # Every value is in the primary table; no direct label crowds the zero band.
    ax.set_title(panel_titles[key],pad=style['title_pad_points'])
    ax.set_yticks([0,1],['New person','Other recording'])
    ax.set_ylim(style['row_min'],style['row_max'])
    ax.set_xlim(style['gap_min_pp'],style['gap_max_pp'])
    ax.set_xticks(style['gap_ticks_pp'])
    ax.set_xlabel('Accuracy gap\n(percentage points)',labelpad=style['axis_label_pad_points'])
    ax.grid(axis='x',color=kit.RULE,alpha=style['grid_alpha'])
    ax.spines[['top','right']].set_visible(False)
fig.subplots_adjust(left=style['left'],right=style['right'],bottom=style['bottom'],
                    top=style['top'],wspace=style['panel_spacing'])
kit.figure(fig,'fig_central');plt.close(fig)


def macro(name):return '\\'+name


def table_environment(columns,header,rows):
    return '\\begin{tabular}{'+columns+'}\n\\toprule\n'+header+' \\\\\n\\midrule\n'+'\n'.join(r+' \\\\' for r in rows)+'\n\\bottomrule\n\\end{tabular}\n'

rows=[]
for o in outputs:
    k=o['key']
    rows.append(' & '.join([names[k],macro(k+'N'),macro(k+'Classes'),macro(k+'Windows'),macro(k+'Features'),macro(k+'Chance'),macro(k+'Majority')]))
kit.table('tab_data',table_environment('lrrrrrr','Task & People & Classes & Windows & Features & Guess (\\%) & Majority (\\%)',rows))
for model,table_name in [('Nn','tab_primary'),('Lda','tab_sensitivity')]:
    rows=[]
    for o in outputs:
        k=o['key']
        for p,g in o['gaps'][model].items():
            base=k+model+p
            vals=[short[k]+' / '+('recording' if p=='Recording' else 'person'),
                  macro(k+model+'RandomAcc'),macro(base+'Acc'),
                  macro(base+'Gap')+' ['+macro(base+'GapLo')+', '+macro(base+'GapHi')+']']
            if model=='Nn':vals.append(g['status'].capitalize())
            rows.append(' & '.join(vals))
    header='Task / test & Random (\\%) & Other (\\%) & Gap [interval]'
    if model=='Nn': header+=' & Status'
    kit.table(table_name,table_environment('lrrll' if model=='Nn' else 'lrrl',header,rows))
rows=[]
for o in outputs:
    k=o['key']
    rows.append(' & '.join([short[k],macro(k+'TrainMin')+'--'+macro(k+'TrainMax'),macro(k+'Queries'),
        macro(k+'Overlap')+' ['+macro(k+'OverlapLo')+', '+macro(k+'OverlapHi')+']',macro(k+'Dropped')]))
kit.table('tab_audit',table_environment('lrrlr','Task & Train windows & Query uses & Sharing (\\%) [interval] & Dropped',rows))
(ws/'results'/'comparisons.json').write_text(json.dumps(outputs,indent=1))

# Only generated outputs enter kit's file registry: npctl deletes them before a
# rerun. Source/dependency hashes belong in a generated sidecar, not that registry.
source_paths = [ws/'analysis/analysis.py', ws/'analysis/data_readers.py',
                ws/'analysis/config.json', ws/'analysis/figure_style.json',
                ws/'prereg.md', ws/'deviations.json',
                ws/'provenance.json']
source_paths += [p for p in (ws/'reproducibility').rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
source_hashes = {str(p.relative_to(ws)):hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(set(source_paths))}
repro_manifest = ws/'results/reproducibility_manifest.json'
repro_manifest.write_text(json.dumps({'sources':source_hashes,
    'toolkit_source_sha256':toolkit_digest,'environment':environment_lock},indent=1)+'\n')
stable_numbers = ws/'results/stable_numbers.json'
# The pinned toolkit's record is already populated exclusively by kit.number.
stable_numbers.write_text(json.dumps({'numbers':kit._numbers},sort_keys=True,indent=1)+'\n')
audit_paths = [ws/'results'/f'{key}_{kind}.json'
               for key in ('emg','stress','ppg','eeg') for kind in ('predictions','windows')]
audit_paths += [ws/'results/comparisons.json',repro_manifest,stable_numbers]
for path in audit_paths:
    kit._record(path)
kit.save()
(ws/'results/execution_metadata.json').write_text(json.dumps({
    'elapsed_seconds':time.monotonic()-start_time,
    'finished':dt.datetime.now(dt.timezone.utc).isoformat(),
    'scope':'execution metadata only, excluded from deterministic numeric exports'},indent=1)+'\n')
