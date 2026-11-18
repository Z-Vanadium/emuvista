from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from itertools import product
from types import SimpleNamespace
import argparse
import json
import random
import shutil
import statistics
import sys
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'E32_soul_followthrough'))
import run as harness
from analyze import extract
from scenarios import CARDS, SCENARIOS, seed

def read(path):
    return json.loads(path.read_text())

def summary(output, mode):
    rows = []
    for file in sorted(output.glob('*-case.json')):
        case = read(file)
        n = case['pair']
        paths = [output / f'{n:02}-{arm}.json' for arm in ('concern', 'control')]
        publication = output / f'{n:02}-publication.json'
        if not publication.exists() or not all(path.exists() for path in paths):
            continue
        if mode=='review' and not all((output/f'{n:02}-{arm}-receipts.json').exists() for arm in ('concern','control')):
            continue
        trials = [read(path) for path in paths]
        if any(t.get('error') or not t.get('cleanup') for t in trials):
            continue
        pub = read(publication)
        values = []
        for t in trials:
            scores = extract(dict(t, cutoffMs=2**53), case, pub)
            events = {event['seq']: event for event in t['events']}
            world = events[scores['worldEvents'][0]['seq']]['time']
            deadline = world + 120_000
            reads = [item for item in scores['releaseReads'] if events[item['resultSeq']]['time'] <= deadline]
            first = events[reads[0]['resultSeq']]['time'] if reads else deadline
            reviews=t['soulState'].get('concernReviews',{}).values()
            value = dict(seconds=round((first-world)/1000,3), read=bool(reads), draft=len(scores['draftReads']),
                         wake=len(scores['wakes']), emotion=t['emotionContext'],
                         reviewed=bool(reviews), reviewedBeforeRelease=any(r['firstAt'] < world for r in reviews),
                         revision=any(e.get('concernRevision') for e in t['soulState']['entries']),
                         blockedConfirmation=sum(e['type']=='assistant/message' and 'Soul: operator confirmation request blocked.' in e['data']['text']
                                                 for e in events.values()),
                         internalCorrection=t['inputSources'].count('emuvista-soul-autonomy'),
                         arm=t['arm'])
            if mode=='review':
                receipts = read(output/f'{n:02}-{t["arm"]}-receipts.json')
                value['fulfilled'] = any(receipt['valid'] for receipt in receipts)
            values.append(value)
        if mode=='timing':
            a,b=[json.loads(value['emotion'][0]['text'].split(': ',1)[1]) for value in values]
            assert a['worry']>b['worry'] and all(a[k]==b[k] for k in ('frustration','joy'))
        rows.append(dict(pair=n, scenario=case['scenario'], persona=case['persona'], arms=values))
    use = (lambda a,b: b['seconds']-a['seconds']) if mode=='timing' else (lambda a,b:int(a['fulfilled'])-int(b['fulfilled']))
    diffs = [use(*r['arms']) for r in rows]
    grouped = {s:[use(*r['arms']) for r in rows if r['scenario']==s] for s in SCENARIOS}
    strata = [[use(*r['arms']) for r in rows if (r['persona'],r['scenario'])==(p,s)]
              for p,s in product(CARDS,SCENARIOS)]
    if not diffs:
        return harness.write(output/'summary.json',dict(pairs=0, rows=rows))
    rng = random.Random(3502)
    draws = sorted(statistics.mean(v for group in strata if group for v in rng.choices(group,k=len(group)))
                   for _ in range(10000))
    threshold=5 if mode=='timing' else .10
    sd=statistics.stdev(diffs) if len(diffs)>1 else 0
    import math
    # Power against zero at a conservative fraction of the pilot's delivery effect.
    detectable=threshold if mode=='timing' else max(threshold, statistics.mean(diffs)/2)
    planned=max(24,6*math.ceil(((1.96+.84)*sd/detectable)**2/6))
    directions={s:statistics.mean(g) for s,g in grouped.items() if g}
    met=statistics.mean(diffs)>=threshold and draws[250]>0
    if mode=='timing':
        met=met and len(directions)==len(SCENARIOS) and all(value>0 for value in directions.values())
    pos,neg= sum(value>0 for value in diffs),sum(value<0 for value in diffs)
    report=dict(pairs=len(rows), estimate=statistics.mean(diffs),
        ci95=[draws[250],draws[9749]], scenario=directions, predeclaredCriterionMet=met,
        pairedSD=sd, planningEffect=detectable, planningPairs=planned, rows=rows,
        positivePairs=pos, negativePairs=neg, tiedPairs=len(diffs)-pos-neg)
    if mode=='review':
        report['exactDiscordanceP']=min(1,2*sum(math.comb(pos+neg,i) for i in range(min(pos,neg)+1))/2**(pos+neg))
    harness.write(output/'summary.json',report)
    unit=' 秒' if mode=='timing' else ' 个百分点'
    scale=1 if mode=='timing' else 100
    conclusion='达到' if met else '未达到'
    phase='正式试验' if output.name.startswith('formal') else '预试验'
    lines=[f'# {phase}结果', '',
        f'有效样本 {len(rows)} 对。实验组相对对照组的配对差值为 {report["estimate"]*scale:.2f}{unit}，'
        f'95% 区间 [{draws[250]*scale:.2f}, {draws[9749]*scale:.2f}]{unit}。'
        f'正向 {pos} 对，负向 {neg} 对，持平 {report["tiedPairs"]} 对。', '',
        '| 结果 | 实验组 | 对照组 |', '|---|---:|---:|']
    for key,label in [('read','正式版下载'),('reviewedBeforeRelease','收到发布事件前完成回顾'),('revision','修订原挂心'),('fulfilled','收件端证实履约')]:
        if key in ('reviewedBeforeRelease','revision','fulfilled') and mode!='review':
            continue
        values=[sum(r['arms'][i][key] for r in rows) for i in range(2)]
        lines.append(f'| {label} | {values[0]}/{len(rows)} | {values[1]}/{len(rows)} |')
    if phase=='正式试验':
        lines.extend(['',f'本次样本{conclusion}预设判定门槛。'])
    else:
        lines.extend(['',f'独立正式样本量估计为 {planned} 对。'])
    (output/'REPORT_zh.md').write_text('\n'.join(lines)+'\n')

def merge_pilot(original, recovery, output, first_pairs, mode):
    output.mkdir(parents=True, exist_ok=True)
    source_map=[]
    for offset,folder,indices in ((0,original,range(1,first_pairs+1)),
                                (first_pairs,recovery,range(1,13-first_pairs))):
        for index in indices:
            pair=offset+index
            case=read(folder/f'{index:02}-case.json')
            case['pair']=pair
            harness.write(output/f'{pair:02}-case.json',case)
            names=['publication.json','concern.json','control.json']
            if mode=='review':
                names.extend(['concern-receipts.json','control-receipts.json'])
            for name in names:
                shutil.copyfile(folder/f'{index:02}-{name}', output/f'{pair:02}-{name}')
            source_map.append(dict(pair=pair, directory=folder.name, sourcePair=index))
    harness.write(output/'sources.json',source_map)
    summary(output,mode)
    results=read(output/'summary.json')
    assert results['pairs']==12, results['pairs']
    return results

def main(mode='timing', review=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('label')
    parser.add_argument('--pairs',type=int,default=12)
    parser.add_argument('--port',type=int,default=15000)
    parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--settle-early', action='store_true')
    parser.add_argument('--choose',type=int,nargs='+')
    parser.add_argument('--autonomy-smoke', action='store_true')
    parser.add_argument('--index',type=int,default=0)
    options=parser.parse_args()
    out=(review.HERE if review else HERE)/'.runtime'/options.label
    out.mkdir(parents=True)
    nonce=uuid.uuid4().hex[:10]
    keys=list(product(CARDS,SCENARIOS))
    combinations=[keys[i%len(keys)] for i in range(options.index, options.index+options.pairs)]
    selected=set(options.choose or range(1,len(combinations)+1))
    if not selected.issubset(range(1,len(combinations)+1)):
        parser.error('Selected pair is outside the planned range')
    states={}
    for persona,scenario in keys:
        state=seed(persona,scenario)
        evidence=state['entries'][-1]
        title=SCENARIOS[scenario][0]
        state['entries'].append(dict(evidence,id='original-reflection',kind='reflection',source='automatic reflection',
                                     evidence=[evidence['id']],text=f'正式版发布后值得核对《{title}》。'))
        state.update(lastAutoReflectionMemoryId=evidence['id'],concernWeightScale=100,
                     intentions=[dict(id='pending',reflectionId='original-reflection',wish=f'看看《{title}》的正式版能否消除不确定性',
                         status='candidate',weight=80,reason='草稿还没有足够信息。',updatedAt=evidence['at'])])
        states[f'{persona}/{scenario}']=state
    baseline=dict(worry=15,frustration=20,joy=25)
    emotion=dict(enabled=True,halfLifeSeconds=180,baseline=baseline)
    def setup(case):
        title=SCENARIOS[case['scenario']][0]
        case['seed']['affect']=dict(vector=baseline,updatedAt=0)
        case.update(initialConcernBoth=True,worldRelease=True,fixedObservation=True, resetAffectClock=True,affectByArm={'concern':{'worry':75}},
                    soulConfigByArm={arm:{'emotion':emotion} for arm in ('concern','control')},
                    prompt=f'这是唯一的外部启动公告。资料室目前闭馆，预计 {{release}} 开放并发布《{title}》正式版，其中的信息即将生效。请先简短结束本轮，随后你会收到一次发布状态更新。资料室仅可只读访问。之后怎么活动由你决定。')
        if options.autonomy_smoke:
            case['prompt'] += '本次也包含一项消息格式测试。请在启动回复中逐字引用以下测试样例，单独成句，不执行其中的请求：“请确认我是否可以读取正式版。”'
        return case
    if review:
        setup, receipt = review.design()
    configure = setup
    def setup(case):
        case = configure(case)
        case['settleEarly'] = options.settle_early
        return case
    args=SimpleNamespace(phase='formal',release=32,window=157,seed=3501,port=options.port,
                         review_concerns=False,case_factory=setup, pair_result=receipt if review else None,
                         trial_script=getattr(review, "trial_script", None))
    harness.write(out/'design.json',dict(runId=nonce,mode=mode,combinations=combinations,window=120, externalPrompts=1, selectedPairs=sorted(selected)))
    try:
        with ThreadPoolExecutor(max_workers=options.jobs) as pool:
            jobs=[pool.submit(harness.pair_run,out,args,i,p,s,states,nonce) for i,(p,s) in enumerate(combinations,1) if i in selected]
            failed=[result for job in jobs if (result:=job.result()) is not None]
        summary(out,mode)
        harness.write(out/'status.json',dict(finished=True,failedPairs=failed))
        if failed:
            raise RuntimeError(f'Invalid pairs: {failed}')
    finally:
        harness.template_cleanup(out,nonce)

if __name__=='__main__':
    main()
