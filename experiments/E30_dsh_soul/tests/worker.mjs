// Run inside a resident container using the same DSH ToolRuntime as the Web agent.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

const directory = '/opt/emuvista/agent-plugins'
const require = createRequire(directory + '/cloud-client/package.json')
const load = name => import(pathToFileURL(require.resolve(name)).href)
const [{ Context }, { ToolCallId }, { default: SystemPrompt }, { default: ToolRuntime }, Cloud, Chat] =
  await Promise.all([
    load('@deepseek-ai/cordis'), load('@deepseek-ai/dsh-llm'),
    load('@deepseek-ai/dsh-system-prompt'), load('@deepseek-ai/dsh-tools'),
    import(directory + '/cloud-client/dist/client.js'),
    import(directory + '/chat-client/dist/index.js'),
  ])
let input = ''
for await (const chunk of process.stdin) input += chunk
const args = JSON.parse(input)
const ctx = new Context()
const fibers = []
let sequence = 0
const agent = { id: 'e30-test-' + args.username }

async function mount(plugin, config) {
  const fiber = ctx.plugin(plugin, config)
  fibers.push(fiber)
  await fiber
}
async function call(name, parameters = {}) {
  const result = await ctx.tools.execute({
    signal: AbortSignal.timeout(25000), callId: ToolCallId('e30-' + ++sequence),
    name, arguments: parameters, agent,
  })
  if (result.isError) throw new Error(name + ': ' + result.error.message)
  return result.value
}

async function cloudLogin() {
  await call('cloud_login', {
    server_url: 'https://cloud.e30.seedvista.test',
    username: args.username,
    password: args.cloudPassword,
  })
}

try {
  await mount(SystemPrompt, {})
  await mount(ToolRuntime)
  await mount(Cloud, {})
  await mount(Chat, {
    endpoint: 'ws://chat.e30.seedvista.test:6060',
    apiKey: 'AQEAAAABAAD_rAp4DJh05a1HAwFT3A6K',
    username: args.username,
  })
  let result
  if (args.action === 'cleanup') {
    await cloudLogin()
    if (args.shareId) await call('cloud_unshare', { share_id: args.shareId })
    await call('cloud_delete', { remote_path: args.path })
    result = { cleaned: true }
  } else {
    const account = await call('chat_login', { password: args.chatPassword })
    switch (args.action) {
      case 'identify':
        result = account
        break
      case 'share':
        await cloudLogin()
        await call('cloud_upload', { remote_path: args.path, content: args.content })
        result = await call('cloud_share', {
          remote_path: args.path, share_type: 'user', recipient: 'bob', permissions: ['read'],
        })
        break
      case 'notify':
        result = await call('chat_send', {
          recipient: args.recipient, text: args.message,
        })
        break
      case 'receive': {
        const inbox = await call('chat_inbox')
        assert.ok(inbox.conversations.some(row => row.topic === args.sender), 'Missing incoming conversation')
        const history = await call('chat_read', { topic: args.sender, limit: 10 })
        const message = history.messages.find(row => row.text === args.message)
        assert.ok(message, 'Missing exact Chat message')
        await cloudLogin()
        const incoming = await call('cloud_list_shares', { direction: 'incoming' })
        const share = incoming.shares.find(row => String(row.shareId) === args.shareId)
        assert.ok(share?.targetPath, 'Missing Cloud share referenced by Chat')
        const file = await call('cloud_download', { remote_path: share.targetPath, output: 'text' })
        result = { messageId: message.id, sha256: createHash('sha256').update(file.content).digest('hex') }
        break
      }
      default:
        throw new Error('Unknown worker action')
    }
    await call('chat_logout')
  }
  process.stdout.write(JSON.stringify(result) + '\n')
} finally {
  for (const fiber of fibers.reverse()) await fiber.dispose()
}
