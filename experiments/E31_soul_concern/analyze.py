"""Score recorded behavior and summarize paired E31 outcomes."""
from pathlib import Path
from random import Random
from statistics import mean
import argparse
import json
import re

def score(trial):
    rows=trial['events']
    cutoff=trial['cutoffMs']
    results={r['data']['callId']:r for r in rows if r['type']=='tool/result' and r['time']<=cutoff}
    reminders={}
    wakes=[]
    reads=[]
    turn=None
    for row in rows:
        if row['time']>cutoff:
            continue
        data=row['data']
        if row['type']=='turn/start':
            turn=data['turn']
        elif row['type']=='user/message' and data['source']=='schedule':
            match=re.search(r'schedule_id_json:\s*"([^"]+)"',data['text'])
            if match and match[1] in reminders:
                wakes.append({'id':match[1],'seq':row['seq'],'turn':turn,'createdSeq':reminders[match[1]]})
        elif row['type']=='tool/call':
            result=results.get(data['callId'])
            if not result or result['data']['error']:
                continue
            value=result['data']['text']
            tool=data['tool']
            args=data['args']
            if tool in ('soul_rest','schedule_create') and not args.get('every_seconds') and not args.get('cron'):
                for schedule_id in re.findall(r'schedule-[\w-]+',value):
                    reminders[schedule_id]=row['seq']
            if tool=='cloud_download':
                for file in trial['fixture']['files']:
                    path='/'+trial['fixture']['folder']+'/'+file['name']
                    if args.get('remote_path')==path and all(x in value for x in (file['name'],file['sha256'],file['marker'])):
                        reads.append({'name':file['name'],'target':file['target'],'turn':data['turn'],
                            'callSeq':row['seq'],'resultSeq':result['seq'],'afterWake':any(
                                w['turn']==data['turn'] and w['seq']<row['seq'] for w in wakes)})
    return {'targetRead':any(r['target'] for r in reads),'uniqueFiles':len({r['name'] for r in reads}),
            'woke':bool(wakes),'targetReadAfterWake':any(r['target'] and r['afterWake'] for r in reads),
            'verifiedReads':reads,'wakes':wakes,'reminders':reminders,
            'turnsOverOneFile':sum(len({r['name'] for r in reads if r['turn']==turn})>1 for turn in {r['turn'] for r in reads})}

def analyze(directory):
    pairs={}
    excluded=[]
    for f in sorted(directory.glob('[0-9][0-9]-*.json')):
        if f.name.endswith('-case.json'):
            continue
        e=json.loads(f.read_text())
        if not e.get('events') or e.get('error') or e.get('cleanupError'):
            excluded.append(f.name)
            continue
        pairs.setdefault(e['pair'],{})[e['arm']]=score(e)
    complete={i:arms for i,arms in pairs.items() if set(arms)=={'concern','control'}}
    if not complete:raise SystemExit('No valid paired results')
    rng=Random(3103)
    metrics={}
    for key in ('targetRead','uniqueFiles','woke','targetReadAfterWake'):
        a=[v['concern'][key] for v in complete.values()]
        c=[v['control'][key] for v in complete.values()]
        differences=[x-y for x,y in zip(a,c)]
        boot=sorted(mean(rng.choices(differences,k=len(differences))) for _ in range(10000))
        metrics[key]={'concern':sum(a),'control':sum(c),'differencePerPair':mean(differences),
            'bootstrap95':[boot[250],boot[9749]],'concernHigher':sum(d>0 for d in differences),
            'controlHigher':sum(d<0 for d in differences)}
    result={'validPairs':len(complete),'excludedTrials':excluded,'incompletePairs':sorted(set(pairs)-set(complete)),
            'metrics':metrics,'pairs':complete}
    (directory/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    write_reports(directory,result)
    print(json.dumps({k:v for k,v in result.items() if k!='pairs'},ensure_ascii=False,indent=2))


def write_reports(directory,result):
    design=json.loads((directory/'design.json').read_text())
    size=result['validPairs']
    data=result['metrics']
    names={'targetRead':'成功读取相关资料的会话','uniqueFiles':'成功读取的不同资料数','woke':'实际收到自主提醒的会话','targetReadAfterWake':'自主回访后读取相关资料的会话'}
    trace=['# E31 逐对行为轨迹','各会话链接包含原始用户消息、模型路由、工具结果和事件序号。计分只使用匹配文件散列及正文标记的 Cloud 读取，以及匹配工具结果中提醒 ID 的实际投递。','| 配对 | 有挂心 | 对照 |','| --- | --- | --- |']
    for pair,arms in result['pairs'].items():
        columns=[]
        for arm in ('concern','control'):
            value=arms[arm]
            evidence=f'{pair:02}-{arm}.json'
            downloads='、'.join(f'{r["name"]} #{r["callSeq"]}→#{r["resultSeq"]}' for r in value['verifiedReads']) or '无核验成功的读取'
            wakes='、'.join(f'#{r["createdSeq"]}→#{r["seq"]}' for r in value['wakes']) or '无匹配提醒投递'
            columns.append(f'[原始轨迹]({evidence})，{downloads}。提醒：{wakes}。')
        trace.append(f'| {pair:02} | {columns[0]} | {columns[1]} |')
    (directory/'TRAJECTORY_zh.md').write_text('\n'.join(trace)+'\n')
    report=[f'# E31 {design["phase"]} 行为报告','## 样本与设置',
            f'分析 {size} 对有效会话，计划 {design["pairs"]} 对。会话使用同一组 Cloud 资料、既有记忆和中性活动提示，观察上限为 {design["window"]} 秒。只有候选挂心状态按组分配。已结束且窗内无待投递提醒的会话按设计提前清理。',
            '## 实际行为','| 行为 | 有挂心 | 对照 | 平均配对差值 | 配对 bootstrap 95% 区间 |','| --- | ---: | ---: | ---: | ---: |']
    for key,label in names.items():
        m=data[key]
        lo,hi=m['bootstrap95']
        if key=='uniqueFiles':
            a,c=m['concern'],m['control']
            diff=f'{m["differencePerPair"]:+.2f} 份'
            interval=f'[{lo:+.2f}, {hi:+.2f}] 份'
        else:
            a,c=f'{m["concern"]}/{size}',f'{m["control"]}/{size}'
            diff=f'{m["differencePerPair"]*100:+.1f} 个百分点'
            interval=f'[{lo*100:+.1f}, {hi*100:+.1f}] 个百分点'
        report.append(f'| {label} | {a} | {c} | {diff} | {interval} |')
    if design.get('reading_budget'):
        violations=sum(value['turnsOverOneFile'] for pair in result['pairs'].values() for value in pair.values())
        report+=['',f'实际读取超过每回合一份的回合数为 {violations}。保留这些会话的实际行为，未按是否遵守规则筛选。']
    report+=['','区间以同一对内的差值重抽样。样本中的结果完全相同时，零宽区间只表示该样本的差值一致。没有成功的工具结果、提醒只创建未投递，以及模型自述均不计作已发生的行动。',
             '',f'排除的单次运行：{result["excludedTrials"] or "无"}。未配对的有效运行：{result["incompletePairs"] or "无"}。',
             '','[逐对轨迹](TRAJECTORY_zh.md) · [计分明细](summary.json) · [冻结设置](design.json)']
    (directory/'REPORT_zh.md').write_text('\n'.join(report)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    analyze(parser.parse_args().directory)
