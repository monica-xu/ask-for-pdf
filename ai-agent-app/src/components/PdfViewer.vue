<script setup>
import { ref, watch, onMounted } from "vue"
import * as pdfjsLib from "pdfjs-dist"
import "pdfjs-dist/build/pdf.worker.mjs"

const props = defineProps({
  file: String,
  page: Number
})

const canvasRef = ref(null)
let pdfDoc = null

async function loadPdf() {
  if (!props.file) return

  const loadingTask = pdfjsLib.getDocument(props.file)
  pdfDoc = await loadingTask.promise

  renderPage(props.page || 1)
}

async function renderPage(pageNum) {
  if (!pdfDoc) return

  const page = await pdfDoc.getPage(pageNum)
  const viewport = page.getViewport({ scale: 1.5 })

  const canvas = canvasRef.value
  const context = canvas.getContext("2d")

  canvas.height = viewport.height
  canvas.width = viewport.width

  await page.render({
    canvasContext: context,
    viewport: viewport
  }).promise
}

// 👇 监听页变化
watch(() => props.page, (newPage) => {
  renderPage(newPage)
})

onMounted(loadPdf)
</script>

<template>
  <div class="pdf-container">
    <canvas ref="canvasRef"></canvas>
  </div>
</template>

<style>
.pdf-container {
  height: 100%;
  overflow: auto;
  background: #f5f5f5;
}
canvas {
  display: block;
  margin: auto;
}
</style>