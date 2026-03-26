<script setup>
import { ref, nextTick } from 'vue'
import MarkdownIt from "markdown-it"
import hljs from "highlight.js"
import "highlight.js/styles/github.css"

const md = new MarkdownIt({
  highlight: function (str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(str, { language: lang }).value
          }</code></pre>`
      } catch { }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(str)}</code></pre>`
  }
})

const input = ref("")
const messages = ref([])
const chatBox = ref(null)
const loading = ref(false)

// 页号与已收集的页级回答
const selectedPage = ref("")
const pageAnswers = ref([])

async function sendMessage() {
  if (!input.value) return

  // 如果指定了页号，则把请求路由到 askPage(), 避免误点 Send 触发整体 /chat
  if (selectedPage.value) {
    await askPage()
    return
  }

  messages.value.push({ role: "user", content: input.value })

  const aiMessage = { role: "assistant", content: "", sources: [] }
  messages.value.push(aiMessage)

  loading.value = true

  try {
    const res = await fetch("http://127.0.0.1:8000/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: input.value })
    })

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let firstChunk = true

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const text = decoder.decode(value)
      if (firstChunk && text.startsWith("[SOURCES]")) {
        const srcStr = text.replace("[SOURCES] ", "").trim()
        aiMessage.sources = srcStr ? srcStr.split("|") : []
        firstChunk = false
        continue
      }
      aiMessage.content += text
      messages.value = [...messages.value]
    }

  } catch (err) {
    console.error("🔥 sendMessage error:", err)
    aiMessage.content += "\n\n[出现错误]"
  } finally {
    loading.value = false
    input.value = ""
  }
}

async function uploadFile(e) {
  const file = e.target.files[0]
  if (!file) return
  const formData = new FormData()
  formData.append("file", file)
  await fetch("http://127.0.0.1:8000/upload", { method: "POST", body: formData })
  alert("✅ PDF 上传成功，可以开始问问题了！")
}

function scrollBottom() {
  if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight
}

function enterSend(e) {
  if (e.key === "Enter") sendMessage()
}

// 对指定页提问并收集页级回答
async function askPage() {
  if (!input.value) {
    alert('请输入问题后再点击 Ask Page')
    return
  }

  const question = input.value
  messages.value.push({ role: 'user', content: `[页 ${selectedPage.value || '全部'}] ${question}` })

  loading.value = true
  let answer = ''
  let sources = []

  try {
    const res = await fetch("http://127.0.0.1:8000/chat_page", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, page: selectedPage.value })
    })

    if (!res.body) throw new Error('No response body')

    const reader = res.body.getReader()
    const dec = new TextDecoder()
    let first = true

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const text = dec.decode(value)
      if (first && text.startsWith('[SOURCES]')) {
        sources = text.replace('[SOURCES] ', '').trim().split('|').filter(Boolean)
        first = false
        continue
      }
      answer += text
    }

    pageAnswers.value.push({ page: selectedPage.value, source: sources.join(','), answer })
    messages.value.push({ role: 'assistant', content: answer, sources })
    scrollBottom()

  } catch (err) {
    console.error('askPage error', err)
    messages.value.push({ role: 'assistant', content: '\n\n[出现错误: ' + err.message + ']' })
  } finally {
    loading.value = false
    input.value = ''
  }
}

// 将收集到的页级回答发送到后端整合
async function integratePages() {
  if (!pageAnswers.value.length) {
    alert('请先收集至少一页的回答（Ask Page）')
    return
  }

  messages.value.push({ role: 'user', content: input.value || '[整合回答请求]' })
  const aiMessage = { role: 'assistant', content: '', sources: [] }
  messages.value.push(aiMessage)
  loading.value = true
  try {
    const res = await fetch("http://127.0.0.1:8000/chat_integrate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: input.value, page_answers: pageAnswers.value })
    })

    if (!res.body) throw new Error('No response body')

    const reader = res.body.getReader()
    const dec = new TextDecoder()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      aiMessage.content += dec.decode(value)
      messages.value = [...messages.value]
    }

    pageAnswers.value = []
    input.value = ''

  } catch (err) {
    console.error('integratePages error', err)
    aiMessage.content += '\n\n[出现错误: ' + err.message + ']'
  } finally {
    loading.value = false
  }
}
</script>

<template>

  <div class="container">

    <h1>🤖 AI Chat + PDF 助手</h1>

    <!-- 上传 PDF -->
    <div class="upload">
      <input type="file" @change="uploadFile" />
    </div>

    <!-- 页号输入与页级操作 -->
    <div class="page-controls">
      <input v-model="selectedPage" placeholder="Page (leave empty for auto)" />
      <button @click="askPage" :disabled="loading">Ask Page</button>
      <button @click="integratePages" :disabled="loading">Integrate Pages</button>
      <div v-if="pageAnswers.length" class="collected">
        <p><b>Collected page answers:</b></p>
        <ul>
          <li v-for="(p, idx) in pageAnswers" :key="idx">页: {{ p.page || '全部' }} — 来源: {{ p.source }}</li>
        </ul>
      </div>
    </div>

    <!-- 聊天区域 -->
    <div class="chat" ref="chatBox">

      <div v-for="(m, index) in messages" :key="index" class="message" :class="m.role">

        <!-- AI -->
        <div v-if="m.role === 'assistant'">
          <span v-html="md.render(m.content)"></span>
          <span v-if="loading" class="cursor">▌</span>
        </div>

        <!-- 用户 -->
        <div v-if="m.role === 'user'">
          {{ m.content }}
        </div>
        <div v-if="m.sources">
          <p><b>来源：</b></p>
          <ul>
            <li v-for="s in m.sources">{{ s }}</li>
          </ul>
        </div>

      </div>

    </div>

    <!-- 输入框 -->
    <div class="inputBox">

      <input v-model="input" @keydown="enterSend" placeholder="Ask something..." />

      <button @click="sendMessage" :disabled="loading">
        {{ loading ? "Thinking..." : "Send" }}
      </button>

    </div>

  </div>

</template>