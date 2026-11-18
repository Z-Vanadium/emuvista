from pathlib import Path
from collections import Counter
import json
import shutil
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'E32_soul_followthrough'))
from analyze import report

def read(path):
    return json.loads(path.read_text())

def merge(sources,destination):
    destination.mkdir(exist_ok=True)
    first,*retries=sources
    shutil.copyfile(first/'design.json',destination/'design.json')
    accepted={}
    for source in (first,*retries):
        failed=set(read(source/'status.json')['failedPairs'])
        for found in source.glob('*-case.json'):
            pair=read(found)['pair']
            if pair in failed or pair in accepted:
                continue
            accepted[pair]=source.name
            for artifact in source.glob(f'{pair:02}-*.json'):
                shutil.copyfile(artifact,destination/artifact.name)
    (destination/'pair-sources.json').write_text(json.dumps(accepted,indent=2)+'\n')
    review=destination/'review.json'
    return report(destination,review if review.exists() else None)

def describe(directory,summary):
    counts={arm:Counter() for arm in ('concern','control')}
    rows=['| 配对 | 开启回顾时对原挂心的变化 | 关闭回顾时的变化 |',
          '| --- | --- | --- |']
    names={'update':'更新','shelve':'搁置','restore':'恢复'}
    pairs=sorted({int(key.split('-')[0]) for key in summary['arms']})
    for pair in pairs:
        descriptions=[]
        for arm in counts:
            session=read(directory/f'{pair:02}-{arm}.json')
            case=read(directory/f'{pair:02}-case.json')
            seed=case['seed']
            first=seed['intentions'][0]
            state=session.get('afterWarmupState',session['soulState'])
            candidate=next(i for i in state['intentions'] if i['id']==first['id'])
            assert candidate['reflectionId']==first['reflectionId']
            cursor=state.get('lastAutoReflectionMemoryId')
            if 'afterWarmupState' in session:
                assert (cursor!=seed['lastAutoReflectionMemoryId'])==(arm=='concern')
            else:
                assert session['inputSources'].count('user')==1
                if arm=='control':assert cursor==seed['lastAutoReflectionMemoryId']
            initial_ids={entry['id'] for entry in seed['entries']}
            changes=[entry for entry in state['entries'] if entry['id'] not in initial_ids and entry.get('concernRevision')]
            assert all(entry['concernRevision']['intentionId']==first['id'] for entry in changes)
            counts[arm].update(e['concernRevision']['action'] for e in changes)
            if not changes:counts[arm]['unchanged']+=1
            event='；'.join(names[e['concernRevision']['action']]+'：'+e['text'].replace('|','／').replace('\n',' ') for e in changes) or '原样保留'
            descriptions.append(event)
        rows.append(f'| {pair:02} | {descriptions[0]} | {descriptions[1]} |')
    target=directory/'REVIEW_zh.md'
    target.write_text('# 回顾是否实际发生\n\n'+'\n'.join(rows)+'\n')
    print('warmup changes',dict(counts))
    return counts

if __name__=='__main__':
    runtime=HERE/'.runtime'
    target=runtime/('final-v1' if sys.argv[1]=='run-v1' else 'final-'+sys.argv[1].removeprefix('run-'))
    summary=merge([runtime/name for name in sys.argv[1:]],target)
    describe(target,summary)
