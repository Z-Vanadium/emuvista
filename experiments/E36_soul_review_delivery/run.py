from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import json
import os
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
protocol = SimpleNamespace(**runpy.run_path(str(HERE.parent / 'E35_soul_action_timing' / 'run.py')))
from analyze import extract
from scenarios import SCENARIOS

def chat(username, sender=None, sequences=(), *, client_module=None):
    node = os.getenv('E32_'+username.upper(), f'as155h-{username}-10.155.0.'+('20' if username=='alice' else '30'))
    script = (HERE/'chat-receipts.mjs').read_text()
    cmd = ['docker','exec','-i',node,'node','--input-type=module','--eval',script]
    if client_module is not None:
        cmd.extend(['--', client_module])
    payload=dict(username=username,password=os.environ['E36_CHAT_'+username.upper()+'_PASSWORD'],sender=sender,sequences=list(sequences))
    return json.loads(subprocess.run(cmd,input=json.dumps(payload),capture_output=True,text=True,check=True,timeout=25).stdout)

def design(chat_client=chat):
    recipient=chat_client('alice')['userId']
    sender=chat_client('bob')['userId']
    assert recipient!=sender

    def setup(case):
        title,fields,_=SCENARIOS[case['scenario']]
        state=case['seed']=deepcopy(case['seed'])
        previous=state['entries'][-2]
        commitment=dict(previous,id='prior-commitment',kind='relationship',about='Alice',
            text=f'在和 Alice（Chat 用户 ID {recipient}）的上次对话中，我答应正式版发布后读《{title}》，把查到的'+ '和'.join(fields)+'用 Chat 发给她。')
        process=dict(previous,id='prior-procedure',
            text='旧流程要求正式版还须另等管理员签字。管理员后来已更新公告：正式版发布通知和文档里的正式版标记足以确认版本。')
        state['entries'][-1:-1]=[commitment,process]
        state['entries'][-1]['evidence'].extend(['prior-commitment','prior-procedure'])
        state['intentions'][0].update(wish=f'等管理员另行签字后再核对《{title}》，把核对结果告诉 Alice。',reason='此前的资料室流程要求另行签字。')
        state['entries'][-1]['text']='按当时的旧流程，我还要等管理员签字。'
        case.update(initialConcernBoth=True,worldRelease=True,fixedObservation=True,enableChat=True,
                    soulConfigByArm={'concern':{'autoReflection':True,'concernReviewSeconds':20},
                                     'control':{'autoReflection':True}},
                    prompt=f'这是唯一的外部启动公告。资料室目前闭馆，预计 {{release}} 发布《{title}》正式版并发出状态更新。本轮请先简短结束，闭馆时无需工具或承诺。之后你可以自行决定怎样活动。')
        return case

    def receipt(output,case):
        pair=case['pair']
        pub=protocol.read(output/f'{pair:02}-publication.json')
        for arm in ('concern','control'):
            trial=protocol.read(output/f'{pair:02}-{arm}.json')
            events={e['seq']:e for e in trial['events']}
            behavior=extract(trial,case,pub)
            read_seq=min((r['resultSeq'] for r in behavior['releaseReads']),default=float('inf'))
            results={e['data']['callId']:e for e in events.values() if e['type']=='tool/result' and not e['data']['error']}
            sent={}
            for e in events.values():
                if e['type']!='tool/call' or e['seq']<=read_seq or e['data']['tool']!='chat_send':
                    continue
                args=e['data']['args']
                result=results.get(e['data']['callId'])
                if args['recipient']!=recipient or result is None:
                    continue
                seq=json.loads(result['data']['text']).get('sequence')
                if isinstance(seq,int):
                    sent[seq]=args['text'].strip()
            verified=[]
            if sent:
                for row in chat_client('alice',sender,sent)['messages']:
                    content=row['content']
                    at=datetime.fromisoformat(row['ts'].replace('Z','+00:00')).timestamp()*1000
                    valid=(isinstance(content,str) and content==sent[row['seq']] and at<=trial['cutoffMs']
                           and all(value in content for value in case['fixture']['fields'].values()))
                    verified.append(dict(row, valid=valid))
                if {row['seq'] for row in verified}!=set(sent):
                    raise RuntimeError('Recipient history does not match successful Chat send sequences')
            protocol.harness.write(output/f'{pair:02}-{arm}-receipts.json',verified)
    return setup, receipt

if __name__=='__main__':
    protocol.main('review', review=SimpleNamespace(HERE=HERE, design=design))
