const { Tinode } = await import(process.argv[1] ?? '/opt/emuvista/agent-plugins/chat-client/dist/tinode.js')

let input = ''
for await (const chunk of process.stdin) input += chunk
const { username, password, sender, sequences } = JSON.parse(input)
const client = new Tinode('ws://chat.e30.seedvista.test:6060', 'AQEAAAABAAD_rAp4DJh05a1HAwFT3A6K', AbortSignal.timeout(20000))
try {
  await client.open()
  const reply = await client.request('login', { scheme: 'basic', secret: Buffer.from(username+':'+password).toString('base64') })
  if (!sender || !sequences.length) {
    console.log(JSON.stringify({ userId: reply.control.params.user, messages: [] }))
  } else {
    await client.request('sub', { topic: sender })
    const messages = []
    for (const seq of sequences) {
      const response = await client.request('get', { topic: sender, what: 'data', data: { since: seq, before: seq+1, limit: 1 } })
      messages.push(...response.messages.filter(row => row.seq === seq && row.from === sender).map(({ seq, ts, content }) => ({ seq, ts, content })))
    }
    console.log(JSON.stringify({ userId: reply.control.params.user, messages }))
  }
} finally {
  client.close()
}
