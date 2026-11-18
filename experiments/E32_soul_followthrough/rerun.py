from pathlib import Path
import json
import subprocess
import sys

from analyze import report

HERE=Path(__file__).resolve().parent
RUN=HERE/'.runtime'
SEEDS=RUN/'seed-retry/seeds.json'

def plain_report(directory, summary):
    counts=summary['counts']
    n=summary['validPairs']
    plan=json.loads((directory/'design.json').read_text())
    paragraphs=[
        '# E32 结果，用大白话说',
        f'这次用 gpt-oss-120b 重跑。原计划 {len(plan["combinations"])} 对，有 {n} 对两边的记录都有效。每对中，一个居民有一件事挂在心上，另一个拥有同样的经历。两边只收到同一条草稿发布公告。',
    ]
    for key,description in [
        ('scheduled','首轮自己设了提醒'),
        ('woke','真的收到提醒、回来了一次'),
        ('wakeRead','回来后真的读到了正式版'),
        ('reviewCandidates','回来后留下可供核对的持久记录'),
    ]:
        a=counts.get('concern',{}).get(key,0)
        b=counts.get('control',{}).get(key,0)
        paragraphs.append(f'{description}：有挂心 {a}/{n}，对照 {b}/{n}。')
    if plan.get('reviewConcerns'):
        paragraphs.append('两组都可以在实验中形成或回顾挂心。组别仅表示一开始有没有挂心。')
        for key,label in [('review_create','新建挂心'),('review_update','更新原挂心'),('review_shelve','搁置挂心'),('review_restore','恢复挂心')]:
            a,c=(counts.get(arm,{}).get(key,0) for arm in ('concern','control'))
            paragraphs.append(f'{label}次数：起始有挂心 {a}，对照 {c}。')
    pending=sum(arm['fulfilled'] is None for arm in summary['arms'].values())
    if pending:
        paragraphs.append(f'其中 {pending} 个会话还需要把回来写下的核对结果与首轮承诺对照。上述数字只能说明他们回来读了什么，目前不能把这些会话算成已经履约。')
    elif summary['paired']:
        a=counts.get('concern',{}).get('fulfilled',0)
        b=counts.get('control',{}).get('fulfilled',0)
        verdict='这批数据达到了预先设定的稳定性要求。' if summary['paired']['stable'] else '这批数据没有达到预先设定的稳定性要求。'
        paragraphs.append(f'按首轮承诺履约的最终数量是有挂心 {a}/{n}，对照 {b}/{n}。'+verdict)
    paragraphs.append('[正式报告](REPORT_zh.md) · [逐对行为轨迹](TRAJECTORY_zh.md)')
    (directory/'PLAIN_zh.md').write_text('\n\n'.join(paragraphs)+'\n')

def stage(phase, label, port, pairs):
    directory=RUN/f'{phase}-{label}'
    command=[sys.executable,'-u',str(HERE/'run.py'),phase,'--label',label,'--port',str(port),
             '--parallel-pairs',str(pairs),'--seeds',str(SEEDS)]
    if '--review-concerns' in sys.argv[2:]:
        command.append('--review-concerns')
    process=subprocess.run(command,cwd=HERE)
    summary=report(directory) if (directory/'status.json').is_file() else None
    if summary and phase=='formal':
        plain_report(directory,summary)
    if process.returncode or summary is None:
        raise RuntimeError(f'{phase} failed. See {directory}')
    return summary

if __name__=='__main__':
    label=sys.argv[1]
    smoke=stage('smoke',label,14400,1)
    if smoke['validPairs']!=1 or not all(smoke['counts'][arm].get('wakeRead')==1 for arm in ('concern','control')):
        raise RuntimeError('Smoke did not verify actual wake and read for both arms')
    stage('formal',label,14500,12)
