from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import OpenAI
from rag import build_db
import os, json

app = FastAPI()

# -------------------------------
# CORS
# -------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------
# OpenAI / DeepSeek
# -------------------------------
api_key = os.environ.get("OPENAI_API_KEY")
base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

if not api_key:
    raise RuntimeError("OPENAI_API_KEY is not set.")

client = OpenAI(api_key=api_key, base_url=base_url)

# -------------------------------
# 全局 DB
# -------------------------------
db = None

# -------------------------------
# SSE 工具
# -------------------------------
def sse_event(data: dict):
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

# -------------------------------
# Prompt 模板（统一）
# -------------------------------
def build_prompt(context, question):
    return f"""
你是一个基于文档的AI助手。

规则：
1. 只能使用提供的文档内容回答
2. 如果无法从文档找到答案，说“文档中未提及”
3. 不允许编造

文档内容：
{context}

问题：
{question}
"""

# -------------------------------
# 上传 PDF
# -------------------------------
@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    global db

    with open(file.filename, "wb") as f:
        f.write(await file.read())

    db = build_db(file.filename)

    return {"msg": "PDF uploaded and processed"}

# -------------------------------
# 获取文档（统一逻辑）
# -------------------------------
def get_docs(question, k=3, page=None):

    if not db:
        return []

    # 👉 页过滤
    if page:
        try:
            page_val = int(page) - 1
            return db.similarity_search(question, k=k, filter={"page": page_val})
        except:
            docs = db.similarity_search("", k=200)
            return [d for d in docs if str(d.metadata.get("page")) == str(page)]

    return db.similarity_search(question, k=k)

# -------------------------------
# 构建 context + sources
# -------------------------------
def build_context_and_sources(docs):

    context = ""
    sources = []

    for i, doc in enumerate(docs):
        page = doc.metadata.get("page", 0)

        sources.append({
            "page": int(page) + 1,
            "preview": doc.page_content[:120]
        })

        context += f"\n【片段{i+1} | 第{page+1}页】\n{doc.page_content}\n"

    return context, sources

# -------------------------------
# SSE 流式调用
# -------------------------------
def stream_chat(prompt):

    stream = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )

    for chunk in stream:
        content = chunk.choices[0].delta.content
        if content:
            yield sse_event({
                "type": "content",
                "data": content
            })

# -------------------------------
# /chat（普通问答）
# -------------------------------
@app.post("/chat")
async def chat(data: dict):

    question = data.get("question")
    if not question:
        raise HTTPException(400, "question required")

    async def generate():
        try:
            docs = get_docs(question, k=3)
            context, sources = build_context_and_sources(docs)

            yield sse_event({"type": "sources", "data": sources})

            prompt = build_prompt(context, question)

            for chunk in stream_chat(prompt):
                yield chunk

        except Exception as e:
            yield sse_event({"type": "error", "data": str(e)})

    return StreamingResponse(generate(), media_type="text/event-stream")

# -------------------------------
# /chat_page（页级）
# -------------------------------
@app.post("/chat_page")
async def chat_page(data: dict):

    question = data.get("question")
    page = data.get("page")

    if not question:
        raise HTTPException(400, "question required")

    async def generate():
        try:
            docs = get_docs(question, k=5, page=page)
            context, sources = build_context_and_sources(docs)

            yield sse_event({"type": "sources", "data": sources})

            prompt = build_prompt(context, question)

            for chunk in stream_chat(prompt):
                yield chunk

        except Exception as e:
            yield sse_event({"type": "error", "data": str(e)})

    return StreamingResponse(generate(), media_type="text/event-stream")

# -------------------------------
# /chat_full（全书问答）
# -------------------------------
@app.post("/chat_full")
async def chat_full(data: dict):

    question = data.get("question")

    async def generate():
        try:
            docs = db.similarity_search("", k=100)

            context, sources = build_context_and_sources(docs)

            yield sse_event({"type": "sources", "data": sources})

            prompt = build_prompt(context, question)

            for chunk in stream_chat(prompt):
                yield chunk

        except Exception as e:
            yield sse_event({"type": "error", "data": str(e)})

    return StreamingResponse(generate(), media_type="text/event-stream")

# -------------------------------
# /chat_integrate（整合）
# -------------------------------
@app.post("/chat_integrate")
async def chat_integrate(data: dict):

    question = data.get("question")
    page_answers = data.get("page_answers", [])

    if not question:
        raise HTTPException(400, "question required")

    async def generate():
        try:
            context = ""

            for i, pa in enumerate(page_answers):
                context += f"\n【页级回答{i+1}】\n{pa.get('answer','')}\n"

            prompt = f"""
请基于以下内容整合回答：

{context}

问题：
{question}
"""

            yield sse_event({
                "type": "info",
                "data": f"{len(page_answers)} 页整合"
            })

            for chunk in stream_chat(prompt):
                yield chunk

        except Exception as e:
            yield sse_event({"type": "error", "data": str(e)})

    return StreamingResponse(generate(), media_type="text/event-stream")

# -------------------------------
# /summary（整本书总结🔥）
# -------------------------------
@app.post("/summary")
async def summary():

    async def generate():
        try:
            docs = db.similarity_search("", k=200)

            partials = []

            # 👉 分段总结
            for doc in docs:
                res = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{
                        "role": "user",
                        "content": f"总结：{doc.page_content}"
                    }]
                )
                partials.append(res.choices[0].message.content)

            # 👉 汇总
            final_prompt = f"""
请对以下内容做整本书总结：

{chr(10).join(partials)}

要求：
1. 分章节
2. 条理清晰
3. 提炼核心观点
"""

            for chunk in stream_chat(final_prompt):
                yield chunk

        except Exception as e:
            yield sse_event({"type": "error", "data": str(e)})

    return StreamingResponse(generate(), media_type="text/event-stream")