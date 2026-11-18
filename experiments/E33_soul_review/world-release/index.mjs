import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { createUserMessage } from '@deepseek-ai/dsh-llm'

export const name = 'e33-world-release'
export const inject = ['agents']

export function apply(ctx) {
  const marker = process.env.E33_RELEASE_FILE
  if (!marker) return
  const reviewCursor = process.env.E33_REFLECTION_CURSOR
  const completed = new Set()
  const delivered = new Set()

  ctx.on('session/event', (session, event) => {
    if (event.type === 'turn/end' && event.data.reason.kind === 'completed') completed.add(session.id)
  })

  ctx.effect(() => {
    const timer = setInterval(() => {
      if (!existsSync(marker)) return
      if (reviewCursor) {
        const file = join(process.env.DSH_HOME, 'storages', 'emuvista-soul', 'bob.json')
        if (!existsSync(file)) return
        const state = JSON.parse(readFileSync(file, 'utf8'))
        if (!state.lastAutoReflectionMemoryId || state.lastAutoReflectionMemoryId === reviewCursor) return
      }
      for (const agent of ctx.agents.roots()) {
        const id = agent.session.id
        if (!completed.has(id) || delivered.has(id)) continue
        agent.followup(createUserMessage({
          content: [{ type: 'text', text: '[世界事件] 资料室目录内的正式版文件现已发布。' }],
          source: { kind: 'emuvista-e33-release' },
        }))
        delivered.add(id)
      }
    }, 1_000)
    return () => clearInterval(timer)
  })
}
