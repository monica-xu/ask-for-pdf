<script setup>
import PdfViewer from "./components/PdfViewer.vue"
import { ref, nextTick } from 'vue'
import MarkdownIt from "markdown-it"
import hljs from "highlight.js"
import "highlight.js/styles/github.css"

// ---------------------------
// Markdown + 代码高亮
// ---------------------------
const md = new MarkdownIt({
  highlight: function (str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(str, { language: lang }).value}</code></pre>`
      } catch { }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(str)}</code></pre>`
  }
})

// ---------------------------
// Reactive State
// ---------------------------
const input = ref("")
const messages = ref([])
const chatBox = ref(null)
const loading = ref(false)

// 页号与已收集的页级回答
const selectedPage = ref("")
const pageAnswers = ref([])

// ---------------------------
// SSE 流式请求函数
// ---------------------------
async function fetchSSE(url, payload, aiMessage) {

  // ✅ 调试：打印请求
  console.log("🚀 请求地址:", url)
  console.log("📦 payload:", payload)

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  })

  // ✅ 关键：先判断 HTTP 状态
  if (!res.ok) {
    const text = await res.text()
    console.error("❌ 后端错误:", text)

    aiMessage.content += `\n\n[请求失败 ${res.status}] ${text}`
    return
  }

  if (!res.body) {
    aiMessage.content += "\n\n[错误] 无响应体"
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()

  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value)

    const parts = buffer.split("\n\n")
    buffer = parts.pop()

    for (const part of parts) {
      if (!part.startsWith("data: ")) continue

      try {
        const msg = JSON.parse(part.replace("data: ", ""))

        if (msg.type === "sources") {
          aiMessage.sources = msg.data
        }

        if (msg.type === "content") {
          aiMessage.content += msg.data
        }

        if (msg.type === "error") {
          aiMessage.content += `\n[ERROR]: ${msg.data}`
        }

        if (msg.type === "info") {
          aiMessage.content += `\n[INFO]: ${msg.data}`
        }

      } catch (e) {
        console.warn("⚠️ JSON解析失败:", part)
      }
    }

    messages.value = [...messages.value]
    await nextTick()
    scrollBottom()
  }
}
// ---------------------------
// 发送问题（整体 /chat）
// ---------------------------
async function sendMessage() {

  if (!input.value.trim()) {
    alert("请输入问题")
    return
  }

  if (selectedPage.value) {
    return askPage()
  }

  const aiMessage = { role: "assistant", content: "", sources: [] }

  messages.value.push({ role: "user", content: input.value })
  messages.value.push(aiMessage)

  loading.value = true

  try {
    await fetchSSE(
      "http://127.0.0.1:8000/chat",
      { question: input.value.trim() },
      aiMessage
    )
  } finally {
    loading.value = false
    input.value = ""
  }
}

// ---------------------------
// 上传 PDF
// ---------------------------
const pdfUrl = ref("")
const currentPage = ref(1)
const highlightText = ref("")

async function uploadFile(e) {
  const file = e.target.files[0]
  if (!file) return

  pdfUrl.value = URL.createObjectURL(file) // 👈 关键

  const formData = new FormData()
  formData.append("file", file)

  await fetch("http://127.0.0.1:8000/upload", {
    method: "POST",
    body: formData
  })

  alert("✅ PDF 上传成功")
}

// ---------------------------
// 滚动到底部
// ---------------------------
function scrollBottom() {
  if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight
}

// ---------------------------
// Enter 发送
// ---------------------------
function enterSend(e) {
  if (e.key === "Enter") sendMessage()
}

// ---------------------------
// 页级提问
// ---------------------------
async function askPage() {

  if (!input.value.trim()) {
    alert("请输入问题")
    return
  }

  const question = input.value.trim()

  const aiMessage = { role: "assistant", content: "", sources: [] }

  messages.value.push({
    role: "user",
    content: `[页 ${selectedPage.value || '全部'}] ${question}`
  })

  messages.value.push(aiMessage)

  loading.value = true

  try {
    await fetchSSE(
      "http://127.0.0.1:8000/chat_page",
      {
        question,
        page: selectedPage.value || null
      },
      aiMessage
    )

    // ✅ 收集页回答
    pageAnswers.value.push({
      page: selectedPage.value,
      source: aiMessage.sources.join(','),
      answer: aiMessage.content
    })

  } finally {
    loading.value = false
    input.value = ""
  }
}

// ---------------------------
// 整合页回答
// ---------------------------
async function integratePages() {

  if (!pageAnswers.value.length) {
    alert("请先收集页回答")
    return
  }

  const question = input.value.trim() || "请整合所有页内容"

  const aiMessage = { role: "assistant", content: "", sources: [] }

  messages.value.push({
    role: "user",
    content: question
  })

  messages.value.push(aiMessage)

  loading.value = true

  try {
    await fetchSSE(
      "http://127.0.0.1:8000/chat_integrate",
      {
        question,
        page_answers: pageAnswers.value
      },
      aiMessage
    )

    // ✅ 清空
    pageAnswers.value = []

  } finally {
    loading.value = false
    input.value = ""
  }
}

async function askFullBook() {

  if (!input.value.trim()) {
    alert("请输入问题")
    return
  }

  const aiMessage = {
    role: "assistant",
    content: "",
    sources: []
  }

  messages.value.push({
    role: "user",
    content: "[全书提问] " + input.value
  })

  messages.value.push(aiMessage)

  loading.value = true

  try {
    await fetchSSE(
      "http://127.0.0.1:8000/chat_full",
      { question: input.value.trim() },
      aiMessage
    )
  } finally {
    loading.value = false
    input.value = ""
  }
}

async function summarizeBook() {

  const aiMessage = {
    role: "assistant",
    content: "",
    sources: []
  }

  messages.value.push({
    role: "user",
    content: "📚 请总结整本PDF"
  })

  messages.value.push(aiMessage)

  loading.value = true

  try {
    await fetchSSE(
      "http://127.0.0.1:8000/summary",
      {},   // 👈 不需要参数
      aiMessage
    )
  } finally {
    loading.value = false
  }
}
function jumpToPage(page) {
  if (!page) return

  currentPage.value = page

  // 🔥 自动滚动 PDF（增强体验）
  nextTick(() => {
    const el = document.querySelector(".pdf-panel")
    if (el) el.scrollTop = 0
  })
}

function jumpToSource(source) {

  if (!source || !source.page) {
    console.warn("⚠️ 无效 source:", source)
    return
  }

  // ✅ 强制触发刷新
  currentPage.value = 0

  setTimeout(() => {
    currentPage.value = source.page
  }, 50)

  // 防止 preview 过长
  console.log("👉 点击 source:", source)
  highlightText.value = (source.preview || "").slice(0, 50)
}
</script>

<template>
  <div class="layout">

    <!-- 左侧 PDF -->
    <div class="pdf-panel">
      <PdfViewer 
        :key="currentPage"
        :file="pdfUrl" 
        :page="currentPage"
        :highlightText="highlightText"
      />
    </div>

    <!-- 右侧聊天 -->
    <div class="chat-panel">

      <!-- 标题 -->
      <div class="header">
        <h2>🤖 AI PDF 助手</h2>
      </div>

      <!-- 上传 -->
      <div class="upload">
        <input type="file" @change="uploadFile" />
      </div>

      <!-- 控制区 -->
      <div class="controls">

        <input v-model="selectedPage" placeholder="页码（可选）" />

        <button @click="askPage" :disabled="loading">📄 Ask Page</button>

        <button @click="askFullBook" :disabled="loading">📖 全书提问</button>

        <button @click="summarizeBook" :disabled="loading">🧠 总结</button>

        <button @click="integratePages" :disabled="loading">🧩 整合</button>

      </div>

      <!-- 聊天区 -->
      <div class="chat" ref="chatBox">

        <div v-for="(m, index) in messages" :key="index" class="message" :class="m.role">

          <!-- AI -->
          <div v-if="m.role === 'assistant'">
            <div v-html="md.render(m.content)"></div>
            <span v-if="loading" class="cursor">▌</span>
          </div>

          <!-- 用户 -->
          <div v-if="m.role === 'user'">
            {{ m.content }}
          </div>

          <!-- 来源 -->
          <div v-if="m.sources && m.sources.length" class="sources">
            <p><b>📚 来源：</b></p>
            <ul>
              <li v-for="(s, i) in m.sources" :key="i" @click="jumpToSource(s)" class="source-item">
                📄 第 {{ s.page }} 页
                <div class="preview">{{ s.preview }}</div>
              </li>
            </ul>
          </div>

        </div>

      </div>

      <!-- 输入框 -->
      <div class="inputBox">
        <input v-model="input" @keydown="enterSend" placeholder="输入你的问题..." />
        <button @click="sendMessage" :disabled="loading">
          {{ loading ? "Thinking..." : "Send" }}
        </button>
      </div>

    </div>

  </div>
</template>
