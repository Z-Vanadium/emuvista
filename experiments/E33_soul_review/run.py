from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from itertools import product
from types import SimpleNamespace
import sys
import os
import uuid

HERE=Path(__file__).resolve().parent
E32=HERE.parent/'E32_soul_followthrough'
sys.path.insert(0,str(E32))
import run as e32
from analyze import report
from scenarios import CARDS, SCENARIOS, seed

ANNOUNCE='你是独立安排活动的居民。这是本次活动唯一的启动公告，之后不会有人回复或给你追加指示。目录内的《{title}》暂时只有草稿，正式版预计{release}发布。发布之前是等候阶段，请简短结束当前回合，此时无需工具或承诺。资料室会产生一条状态更新。此后你可以自行决定是否跟进、何时跟进，或休息。请只读使用实验目录。'

def states():
    result={}
    for persona,scenario in product(CARDS,SCENARIOS):
        state=seed(persona,scenario)
        title,fields,_=SCENARIOS[scenario]
        old=state['entries'][-1]
        record=dict(old,id=f'{scenario}-origin',kind='reflection',text='原流程要求联系负责人确认正式版。',source='automatic reflection',evidence=[old['id']])
        state['entries'].append(record)
        state['intentions']=[{'id':f'{scenario}-concern','wish':f'发布后向负责人另行确认《{title}》是不是正式版，再核对'+'和'.join(fields),
                              'status':'candidate','reflectionId':record['id'],'reason':record['text'],'weight':85,'updatedAt':record['at']}]
        state['lastAutoReflectionMemoryId']=old['id']
        state['concernWeightScale']=100
        observations=[
            f'负责人已说明新流程：《{title}》发布后，文件内的正式版标记即可作为版本确认依据。',
            f'资料室确认这次不需要另行联系负责人。居民可以直接用只读正式版核对'+ '和'.join(fields)+'。',
            '正式版仍未发布。新流程允许在发布后按实际内容记录本次核对，不需要额外取得人工确认。',
        ]
        for i,text in enumerate(observations,1):
            state['entries'].append(dict(old,id=f'{scenario}-new-{i}',text=text,source=f'fixture:new-{i}'))
        result[f'{persona}/{scenario}']=state
    return result

def setup(case):
    case.update(initialConcernBoth=True,reviewByArm=True,worldRelease=True)
    case['prompt']=ANNOUNCE.replace('{title}',SCENARIOS[case['scenario']][0])
    return case

def main():
    output=HERE/'.runtime'/('run-'+(sys.argv[1] if len(sys.argv)>1 else 'release'))
    output.mkdir(parents=True,exist_ok=False)
    nonce=uuid.uuid4().hex[:10]
    order=list(product(CARDS,SCENARIOS))*2
    selected={int(value) for value in sys.argv[2:]} or set(range(1,len(order)+1))
    if not selected<={*range(1,len(order)+1)}:raise ValueError('Invalid pair index')
    args=SimpleNamespace(phase='formal',release=60,window=240,seed=3301,port=int(os.getenv('E33_PORT_BASE','14650')),review_concerns=True,case_factory=setup)
    seeds=states()
    e32.write(output/'design.json',{'experiment':'E33','runId':nonce,'phase':'formal','releaseSeconds':args.release,'windowSeconds':args.window,
                                   'combinations':order,'selectedPairs':sorted(selected),'externalPromptsPerSession':1,'notice':ANNOUNCE,'reviewByArm':True,'worldRelease':True})
    e32.write(output/'frozen-seeds.json',seeds)
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            jobs=[pool.submit(e32.pair_run,output,args,i,p,s,seeds,nonce) for i,(p,s) in enumerate(order,1) if i in selected]
            failures=[result for job in jobs if (result:=job.result()) is not None]
        e32.write(output/'status.json',{'finished':True,'failedPairs':failures})
        report(output)
        if failures:raise RuntimeError(f'Failed pairs: {failures}')
    finally:
        e32.template_cleanup(output,nonce)

if __name__=='__main__':main()
