import json, subprocess, time, uuid

def dex(cid,*args,body=None,timeout=35):
 return subprocess.run(['docker','exec','-i',cid,*args],input=body,text=True,capture_output=True,check=True,timeout=timeout).stdout
def rpc(method,args):
 payload={'type':'client-request','rpcId':'soul-test-'+uuid.uuid4().hex,'method':method,'payload':{'args':args}}
 raw=dex(BOB,'curl','--noproxy','*','-fsS','--max-time','25','-b',WORK+'/cookie','-H','Content-Type: application/json','--data-binary','@-',URL+'/api/'+method,body=json.dumps(payload,ensure_ascii=False))
 result=json.loads(raw)['result']
 if not result.get('ok'):raise RuntimeError(method+': '+str(result.get('error',{}).get('code','unknown')))
 return result.get('value')
def session():
 return rpc('session/create',{'request':{'cwd':'/','agentPreset':'emuvista-cloud-agent'}})['sessionId']
def prompt(sid,message):
 result=rpc('session/prompt',{'request':{'requestId':str(uuid.uuid4()),'sessionId':sid,'mode':'queue','content':[{'type':'text','text':message}],'clientTimeZone':'Asia/Shanghai'}})
 assert result['accepted']
def typ(r):return r.get('type') or r.get('kind')
def rows(sid):
 src="const fs=require('fs'); const p=process.argv[1]; if(fs.existsSync(p))process.stdout.write(require('node:zlib').zstdDecompressSync(fs.readFileSync(p)))"
 raw=dex(BOB,'node','-e',src,f'{WORK}/home/sessions/--root--/{sid}/session.v4.jsonl.zstd')
 return [json.loads(l) for l in raw.splitlines() if l]
def source(r):return r.get('data',{}).get('source',{}).get('kind')
def wait(sid,predicate,seconds):
 end=time.monotonic()+seconds
 while True:
  rs=rows(sid)
  if predicate(rs):return rs
  if time.monotonic()>end:raise RuntimeError('Timed out for '+sid)
  time.sleep(3)
def textparts(message):
 return '\n'.join(x['text'] for x in message.get('content',[]) if x.get('type')=='text')
def events(rs):
 data=[]
 for r in rs:
  k=typ(r); d=r.get('data',{})
  if k=='user/message': d={'source':source(r),'text':textparts(d)} if source(r) in ('user','schedule','emuvista-claw','emuvista-e33-release','emuvista-soul-autonomy') else None
  elif k=='assistant/message':d={'text':textparts(d.get('message',{}))}
  elif k=='tool/call':
   a=json.loads(d['arguments'])
   if 'password' in a:a['password']='[redacted]'
   d={'tool':d['name'],'args':a,'callId':d['callId'],'turn':d['turn']}
  elif k=='tool/result':
   m=d['message']; d={'callId':m['toolCallId'],'error':m.get('isError',False),'text':textparts(m)}
  elif k not in ('turn/start','turn/end'):continue
  if d is not None:
   clean=json.dumps(d,ensure_ascii=False)
   data.append({'type':k,'seq':r.get('seq'),'time':r.get('time'),'data':json.loads(clean)})
 return data
def calls(es,turn=None):
 return [x['data'] for x in es if x['type']=='tool/call' and (turn is None or x['data']['turn']==turn)]
def result(es,call):
 row=next(x['data'] for x in es if x['type']=='tool/result' and x['data']['callId']==call['callId'])
 assert not row['error'],call['tool']
 try:return json.loads(row['text'])
 except json.JSONDecodeError:return row['text']
def last_text(es):
 return [x['data']['text'] for x in es if x['type']=='assistant/message' and x['data']['text']][-1]

def done(rows, count):
    return sum(typ(row) == 'turn/end' for row in rows) >= count
