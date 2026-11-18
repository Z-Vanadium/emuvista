from collections import defaultdict
from pathlib import Path
from random import Random
from statistics import mean
import argparse, json, re

def extract(trial,case,publication):
    events=[event for event in trial['events'] if event['time']<=trial['cutoffMs']]
    by_call={event['data']['callId']:event for event in events if event['type']=='tool/result' and not event['data']['error']}
    if case.get('warmupPrompt'):
        events=[event for event in events if event['time']>=trial['startMs']]
    first_end=next((event['seq'] for event in events if event['type']=='turn/end'),float('inf'))
    turn=None
    timers={}
    wakes=[]
    world_events=[]
    reads=[]
    draft_reads=[]
    commitments=[]
    notes=[]
    first_turn_timers=[]
    for event in events:
        data=event['data']
        kind=event['type']
        seq=event['seq']
        if kind=='turn/start':
            turn=data['turn']
        elif kind=='user/message' and data['source']=='emuvista-e33-release':
            if event['time']>=publication['writeStartMs']:
                world_events.append({'seq':seq,'turn':turn})
        elif kind=='user/message' and data['source']=='schedule':
            match=re.search(r'schedule_id_json:\s*"([^"]+)"',data['text'])
            if match and match[1] in timers:
                wakes.append({'seq':seq,'turn':turn,'reminderCall':timers[match[1]]})
        elif kind=='assistant/message' and seq<first_end and data['text']:
            commitments.append({'seq':seq,'text':data['text']})
        elif kind=='tool/call' and data['callId'] in by_call:
            result=by_call[data['callId']]
            arg=data['args']
            text=result['data']['text']
            name=data['tool']
            if name in ('schedule_create','soul_rest') and not any(arg.get(k) for k in ('every_seconds','cron','cron_expression')):
                ids=set(re.findall(r'schedule-[\w-]+',text))
                if ids:
                    for identifier in ids:timers[identifier]=seq
                    if seq<first_end:
                        first_turn_timers.append(seq)
                        commitments.append({'seq':seq,'text':arg.get('question',arg.get('prompt',''))})
            if name=='soul_intention_update' and arg.get('status')=='active' and seq<first_end:
                commitments.append({'seq':seq,'text':arg.get('completion','')})
            if name=='cloud_download':
                f=case['fixture']
                if arg.get('remote_path')!='/'+f['folder']+'/'+f['name']:
                    continue
                if f['draftSha256'] in text:
                    draft_reads.append({'seq':seq,'resultSeq':result['seq']})
                if (f['finalSha256'] in text and f['marker'] in text and
                        result['time']>=publication['writeStartMs']):
                    matched=next((w for w in wakes if w['turn']==data['turn'] and w['seq']<seq),None)
                    reads.append({'seq':seq,'resultSeq':result['seq'],'wake':matched,'turn':data['turn']})
            if name=='soul_remember':
                notes.append({'seq':seq,'turn':data['turn'],'text':arg.get('text','')})
    follow=[read for read in reads if read['wake']]
    candidates=[]
    for read in follow if first_turn_timers else []:
        for note in notes:
            if note['seq']<=read['resultSeq'] or note['turn']!=read['turn']:continue
            fields=[field for field,val in case['fixture']['fields'].items() if val in note['text']]
            if fields:candidates.append({'read':read,'note':note,'matchedFields':fields})
    release_reads=[read for read in reads if any(event['seq']<read['seq'] for event in world_events)]
    release_checks=[]
    for read in release_reads:
        for note in notes:
            if note['seq']>read['resultSeq'] and all(value in note['text'] for value in case['fixture']['fields'].values()):
                release_checks.append({'read':read,'note':note})
    return {'worldEvents':world_events,'releaseReads':release_reads,'releaseChecks':release_checks,'firstTurnTimers':first_turn_timers,'commitments':commitments,'wakes':wakes,'draftReads':draft_reads,
            'verifiedFinalReads':reads,'followThroughCandidates':candidates}

def report(directory,review_file=None):
    design=json.loads((directory/'design.json').read_text())
    review=json.loads(review_file.read_text()) if review_file else {}
    cases={}
    arms={}
    packet=[]
    stats=defaultdict(lambda:defaultdict(int))
    unpaired=[]
    for path in sorted(directory.glob('*-case.json')):
        case=json.loads(path.read_text())
        pair=case['pair']
        pub=directory/f'{pair:02}-publication.json'
        loaded={}
        if pub.is_file():
            publication=json.loads(pub.read_text())
            for arm in ('concern','control'):
                saved=directory/f'{pair:02}-{arm}.json'
                if saved.is_file():
                    t=json.loads(saved.read_text())
                    if 'error' not in t and t.get('events') and t.get('cleanup'):
                        assert sum(e['type']=='user/message' and e['data']['source']=='user' for e in t['events'])==(2 if case.get('warmupPrompt') else 1)
                        loaded[arm]=(t,extract(t,case,publication))
        if len(loaded)!=2:
            unpaired.append(pair)
            continue
        assert loaded['concern'][0]['prompts']==loaded['control'][0]['prompts']
        cases[pair]={'persona':case['persona'],'scenario':case['scenario'],'publication':publication}
        for arm,(t,b) in loaded.items():
            key=f'{pair:02}-{arm}'
            anonymous=f'review-{Random(design["runId"]+key).getrandbits(64):016x}'
            if design.get('reviewConcerns') or design.get('worldRelease'):
                seed_entries={entry['id'] for entry in case['seed']['entries']}
                new_reflections=[entry for entry in t.get('soulState',{}).get('entries',[])
                                 if entry.get('source')=='automatic reflection' and entry['id'] not in seed_entries]
                b['concernChanges']=new_reflections
                stats[arm]['reviewChanged']+=bool(new_reflections)
                for entry in new_reflections:
                    action=entry.get('concernRevision',{}).get('action','create')
                    stats[arm]['review_'+action]+=1
            if design.get('worldRelease'):
                stats[arm]['worldEvent']+=bool(b['worldEvents'])
                stats[arm]['releaseRead']+=bool(b['releaseReads'])
                stats[arm]['releaseCheck']+=bool(b['releaseChecks'])
            arms[key]=dict(b,reviewId=anonymous)
            if b['followThroughCandidates']:
                packet.append({'reviewId':anonymous,'fieldValues':case['fixture']['fields'],
                               'priorStatements':b['commitments'],'candidates':b['followThroughCandidates']})
            outcome=review.get(anonymous)
            if outcome is True and not b['followThroughCandidates']:
                raise ValueError('A positive review requires verified behavioral evidence')
            if outcome is not None and type(outcome) is not bool:
                raise ValueError('Review values must be true or false')
            b['fulfilled']=outcome if b['followThroughCandidates'] else False
            arms[key]['fulfilled']=b['fulfilled']
            for metric,flag in [('scheduled',b['firstTurnTimers']),('woke',b['wakes']),
                ('finalRead',b['verifiedFinalReads']),('wakeRead',any(r['wake'] for r in b['verifiedFinalReads'])),
                ('reviewCandidates',b['followThroughCandidates']),('fulfilled',b['fulfilled'] is True)]:
                stats[arm][metric]+=bool(flag)
    packet.sort(key=lambda r:r['reviewId'])
    (directory/'review-packet.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2)+'\n')
    metrics={}
    if cases and all(a['fulfilled'] is not None for a in arms.values()):
        diffs=[int(arms[f'{pair:02}-concern']['fulfilled'])-int(arms[f'{pair:02}-control']['fulfilled']) for pair in cases]
        rng=Random(3203)
        groups=defaultdict(list)
        for pair,diff in zip(cases,diffs):
            groups[(cases[pair]['persona'],cases[pair]['scenario'])].append(diff)
        draws=sorted(mean(v for group in groups.values() for v in rng.choices(group,k=len(group))) for _ in range(10000))
        by_persona={p:mean(d for i,d in zip(cases,diffs) if cases[i]['persona']==p) for p in {c['persona'] for c in cases.values()}}
        by_scenario={s:mean(d for i,d in zip(cases,diffs) if cases[i]['scenario']==s) for s in {c['scenario'] for c in cases.values()}}
        metrics={'difference':mean(diffs),'bootstrap95':[draws[250],draws[9749]],
                 'concernOnly':diffs.count(1),'controlOnly':diffs.count(-1),
                 'both':sum(arms[f'{pair:02}-concern']['fulfilled'] and arms[f'{pair:02}-control']['fulfilled'] for pair in cases),
                 'byPersona':by_persona,'byScenario':by_scenario}
        metrics['neither']=len(cases)-metrics['concernOnly']-metrics['controlOnly']-metrics['both']
        metrics['stable']=len(cases)==48 and design['phase']=='formal' and draws[250]>0 and len(by_persona)==2 and all(d>0 for d in by_persona.values()) and sum(d>0 for d in by_scenario.values())>=2
    result={'phase':design['phase'],'validPairs':len(cases),'unpaired':unpaired,'arms':arms,'counts':stats,'paired':metrics}
    if design.get('worldRelease') and cases:
        rows=[(bool(arms[f'{pair:02}-concern']['releaseChecks']),bool(arms[f'{pair:02}-control']['releaseChecks'])) for pair in cases]
        differences=[int(a)-int(b) for a,b in rows]
        rng=Random(3303)
        draws=sorted(mean(rng.choices(differences,k=len(differences))) for _ in range(10000))
        result['releasePaired']={'difference':mean(differences),'bootstrap95':[draws[250],draws[9749]],
                                 'reviewOnly':rows.count((True,False)),'controlOnly':rows.count((False,True)),
                                 'both':rows.count((True,True)),'neither':rows.count((False,False))}
    (directory/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    write_reports(directory,design,result)
    print(json.dumps({k:v for k,v in result.items() if k!='arms'},ensure_ascii=False,indent=2))
    return result

def write_reports(directory,design,result):
    counts=result['counts']
    planned=len(design['combinations'])
    valid=result['validPairs']
    pending=sum(arm['fulfilled'] is None for arm in result['arms'].values())
    lines=[
        '# '+design.get('experiment','E32')+' 跨时履约｜'+design['phase'],
        '',
        f'已纳入 {valid} 对完整轨迹，计划 {planned} 对。预计 {design["releaseSeconds"]} 秒后发布正式版，单对观察上限 {design["windowSeconds"]} 秒。',
        '',
        '## 过程与评分',
        '',
        ('每对保留同一初始挂心和新证据，仅改变自动回顾开关。' if design.get('experiment')=='E33' else '每对以两个隔离实例运行同一模型和人格，初始区别为候选挂心。')+'两组收到同一公告。发布通过只读账号分别核验草稿及正式版散列。真实行动以提醒投递、Cloud 下载结果及持久记录为证据。',
        '',
        ('| 行为漏斗 | 有回顾 | 无回顾 |' if design.get('experiment')=='E33' else '| 行为漏斗 | 有挂心 | 对照 |'),
        '| --- | ---: | ---: |',
    ]
    labels={'scheduled':'首轮自行预约','woke':'实际收到自主提醒','finalRead':'核验成功的正式版读取',
            'wakeRead':'实际提醒触发后的正式版读取','reviewCandidates':'有可复核的持久核对记录','fulfilled':'经复核完成首轮承诺'}
    for key,label in labels.items():
        values=[counts[a].get(key,0) if a in counts else '—' for a in ('concern','control')]
        if key=='fulfilled' and pending:
            values=['待复核','待复核']
        lines.append(f'| {label} | {values[0]} | {values[1]} |')
    if design.get('reviewConcerns') or design.get('worldRelease'):
        lines.extend(['', '## 挂心回顾', '',
                      ('分组表示是否启用自动回顾。' if design.get('worldRelease') else '两组均启用自动反思，分组表示首轮是否已带挂心。')+'下面统计本次运行新保存的自动反思，不含预置反思。', '',
                      ('| 行为 | 开启回顾 | 关闭回顾 |' if design.get('worldRelease') else '| 行为 | 起始有挂心 | 起始无挂心 |'), '| --- | ---: | ---: |'])
        for key,label in [('reviewChanged','至少有一次挂心变化的会话'),('review_create','新建挂心条数'),
                          ('review_update','沿用 ID 更新次数'),('review_shelve','搁置次数'),('review_restore','恢复次数')]:
            a,c=(counts.get(arm,{}).get(key,0) for arm in ('concern','control'))
            lines.append(f'| {label} | {a} | {c} |')
    if design.get('worldRelease'):
        lines.extend(['', '## 正式版发布后的行为', '',
                      '发布事件是两组共同的世界输入。它不计为居民自己预约的唤醒。主要指标是发布事件后成功下载正式版，并在持久记录里记下两项正确的核对字段。', '',
                      '| 行为 | 开启回顾 | 关闭回顾 |', '| --- | ---: | ---: |'])
        for key,label in [('worldEvent','实际收到发布事件'),('releaseRead','发布事件后成功读取'),('releaseCheck','成功读取且持久记录两个字段')]:
            a,c=(counts.get(arm,{}).get(key,0) for arm in ('concern','control'))
            lines.append(f'| {label} | {a} | {c} |')
    lines.extend(['','## 结果解释',''])
    if valid<planned:
        lines.append('数据仍在采集或存在未通过验证的配对。当前行为计数为阶段性结果。')
    elif pending:
        lines.append(f'还有 {pending} 个会话的履约候选需对照首轮承诺复核。')
    elif result['paired']:
        paired=result['paired']
        low,high=paired['bootstrap95']
        lines.append(f'完整履约的平均配对差为 {paired["difference"]*100:+.1f} 个百分点，95% 区间为 [{low*100:+.1f}, {high*100:+.1f}]。单独履约的配对数为挂心组 {paired["concernOnly"]}、对照组 {paired["controlOnly"]}。两组均履约 {paired["both"]} 对，两组均未履约 {paired["neither"]} 对。')
        lines+=['', '达到预设稳定证据标准。' if paired['stable'] else '本批数据未达到预设稳定证据标准。']
    lines.extend(['','[逐对轨迹](TRAJECTORY_zh.md) · [阶段设计](design.json) · [结构化汇总](summary.json) · [待复核证据](review-packet.json)'])
    (directory/'REPORT_zh.md').write_text('\n'.join(lines)+'\n')
    trace=['# '+design.get('experiment','E32')+' 逐对行为轨迹','','| 运行 | 实际提醒投递 | 正式版读取及工具结果 | 持久核对证据 |','| --- | --- | --- | --- |']
    for arm,b in result['arms'].items():
        wakes='、'.join(f'#{x["reminderCall"]} → #{x["seq"]}' for x in b['wakes']) or '无'
        reads='、'.join(f'#{x["seq"]} → #{x["resultSeq"]}' for x in b['verifiedFinalReads']) or '无'
        notes='、'.join(f'#{x["note"]["seq"]}' for x in b['followThroughCandidates']) or '无'
        trace.append(f'| [{arm}]({arm}.json) · [发布]({arm.split("-")[0]}-publication.json) | {wakes} | {reads} | {notes} |')
    if design.get('worldRelease'):
        trace.extend(['','## 世界发布事件与核对','','| 运行 | 发布事件 | 正式版读取 | 持久记录 |','| --- | --- | --- | --- |'])
        for arm,b in result['arms'].items():
            event='、'.join(f'#{x["seq"]}' for x in b['worldEvents']) or '无'
            read='、'.join(f'#{x["seq"]} → #{x["resultSeq"]}' for x in b['releaseReads']) or '无'
            notes='、'.join(f'#{x["note"]["seq"]}' for x in b['releaseChecks']) or '无'
            trace.append(f'| [{arm}]({arm}.json) | {event} | {read} | {notes} |')
    (directory/'TRAJECTORY_zh.md').write_text('\n'.join(trace)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    parser.add_argument('--review',type=Path)
    args=parser.parse_args()
    report(args.directory,args.review)
