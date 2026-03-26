from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from rag import build_db
import os

# 尝试加载 .env（如果安装了 python-dotenv）
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
from fastapi.responses import StreamingResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注意：这里使用了现有的 key 与 base_url（请在生产环境中使用安全的配置方式）
api_key = os.environ.get("OPENAI_API_KEY")
base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

if not api_key:
    raise RuntimeError("OPENAI_API_KEY is not set. Put it in environment or a .env file.")

client = OpenAI(
    api_key=api_key,
    base_url=base_url,
)

db = None


@app.get("/debug_page")
async def debug_page(page: str = None, k: int = 50):
    """调试接口：按 page 返回匹配的文档元信息与内容预览，便于排查 metadata 与检索问题。"""
    if not db:
        return {"docs": [], "note": "db not initialized, upload a PDF first"}

    try:
        docs = []
        # 尝试按 metadata 过滤检索
        if page is not None and str(page) != "":
            try:
                page_val = int(page)
            except Exception:
                page_val = page

            # 支持页号偏移：用户输入通常为 1-based，但某些文档元数据可能是 0-based。
            # 先尝试用原始 page_val 作为 filter；若结果为空且 page_val 可转为 int，则尝试 page_val-1。
            tried_found = None
            try:
                tried_found = db.similarity_search("", k=k, filter={"page": page_val})
            except TypeError:
                # 不支持 filter 时会在下面做通用过滤
                tried_found = None

            if not tried_found and isinstance(page_val, int):
                try:
                    alt_page = max(0, page_val - 1)
                    tried_found = db.similarity_search("", k=k, filter={"page": alt_page})
                except TypeError:
                    tried_found = None

            if tried_found:
                found = tried_found
            else:
                # 底层不支持 filter 或 filter 无结果：拉取较多片段并按 metadata 做宽松匹配
                found = db.similarity_search("", k=max(200, k))
                # 构建可接受的 page 值集合（字符串形式比对）
                page_candidates = set()
                page_candidates.add(str(page))
                if isinstance(page_val, int):
                    page_candidates.add(str(page_val))
                    page_candidates.add(str(max(0, page_val - 1)))

                found = [d for d in found if str(d.metadata.get("page", "")) in page_candidates]
        else:
            found = db.similarity_search("", k=k)

        for d in found:
            docs.append({
                "page": d.metadata.get("page"),
                "source": d.metadata.get("source"),
                "content_preview": d.page_content[:300]
            })

        return {"docs": docs}
    except Exception as e:
        return {"error": str(e)}


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):

    global db
    import traceback

    try:
        with open(file.filename, "wb") as f:
            f.write(await file.read())

        # 简单校验：尝试用 pypdf 打开文件，快速捕获损坏或非 PDF 的情况
        try:
            from pypdf import PdfReader
            _ = PdfReader(file.filename)
        except Exception as _e:
            return {"error": "PDF 解析失败，可能为损坏或非标准 PDF 文件，请检查后重试。", "detail": str(_e)}

        db = build_db(file.filename)

        return {"msg": "PDF uploaded and processed"}

    except Exception as e:
        tb = traceback.format_exc()
        # 返回详细错误用于调试（生产环境不要返回完整堆栈）
        return {"error": str(e), "trace": tb}


@app.post("/chat_page")
async def chat_page(data: dict):
    """按页提问的接口：可指定 page（可选），返回该页相关内容的流式回答与来源。"""

    question = data.get("question")
    page = data.get("page")
    k = data.get("k", 3)

    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    async def generate():
        try:
            # DEBUG: 打印收到的原始请求参数，便于确认前端传参
            try:
                print(f"[chat_page] received request -> question={question!r}, page={page!r}, k={k!r}")
            except Exception:
                pass
            context = ""
            sources = []

            if db:
                # 如果指定了 page，优先使用 metadata 过滤检索对应页的片段（某些 VectorStore 支持 filter 参数）
                if page is not None and str(page) != "":
                    # 尝试将页号解析为数字
                    try:
                        page_val = int(page)
                    except Exception:
                        page_val = page

                    # 支持页号偏移：优先用 filter（若可用），否则拉取大量片段并按 metadata 宽松匹配。
                    docs = None
                    try:
                        docs = db.similarity_search(question, k=k, filter={"page": page_val - 1})
                    except TypeError:
                        docs = None

                    # 若 filter 无结果且 page_val 为 int，尝试 page_val-1
                    if (not docs) and isinstance(page_val, int):
                        try:
                            alt_page = max(0, page_val - 1)
                            docs = db.similarity_search(question, k=k, filter={"page": alt_page})
                        except TypeError:
                            docs = None

                    if not docs:
                        docs = db.similarity_search("", k=max(1000, k))
                        page_candidates = set()
                        page_candidates.add(str(page))
                        if isinstance(page_val, int):
                            page_candidates.add(str(page_val))
                            page_candidates.add(str(max(0, page_val - 1)))

                        docs = [d for d in docs if str(d.metadata.get("page", "")) in page_candidates]
                else:
                    docs = db.similarity_search(question, k=k)

                for i, doc in enumerate(docs):
                    page_meta = doc.metadata.get("page", "未知页")
                    filename = doc.metadata.get("source", "未知文件")
                    # DEBUG: 打印选中 docs 的 page metadata 帮助定位问题
                    try:
                        print(f"[chat_page] input page={page!r}, selected doc page={page_meta!r}, source={filename}")
                    except Exception:
                        pass
                    sources.append(f"{filename} 第{page_meta}页")
                    truncated_content = doc.page_content[:500]
                    context += f"\n【来源{i+1} | {filename} 第{page_meta + 1}页】\n{truncated_content}\n"

            prompt = f"""
                你是一个AI助手，请严格根据提供的知识回答问题。

                知识：
                {context}

                问题：
                {question}
                """

            stream = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是一个专业助手"},
                    {"role": "user", "content": prompt}
                ],
                stream=True,
            )

            # 先输出来源信息
            yield "[SOURCES] " + "|".join(sources) + "\n"

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            yield f"\n[ERROR]: {str(e)}"

    return StreamingResponse(generate(), media_type="text/plain")


@app.post("/chat_integrate")
async def chat_integrate(data: dict):
    """整合多个页级回答：接收 question 与 page_answers 列表（每项包含 page/source/answer），返回合并后的最终回答。"""

    question = data.get("question")
    page_answers = data.get("page_answers", [])

    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    # 构建整合用的上下文——严格使用传入的页级回答
    context = ""
    for i, pa in enumerate(page_answers):
        src = pa.get("source", f"第{pa.get('page','?')}页")
        ans = pa.get("answer", "")
        context += f"\n【页级回答{i+1} | {src}】\n{ans}\n"

    prompt = f"""
        你是一个AI助手。下面是来自文档不同页的独立页级回答（注意：不得引用未提供的信息）。

        页级回答：
        {context}

        请基于上面的页级回答，针对问题作出一个格式清晰、简洁且完整的最终回答。
        如果信息不足，请明确说明缺失哪些信息并避免编造。

        问题：
        {question}
        """

    async def generate():
        try:
            stream = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是一个专业助手"},
                    {"role": "user", "content": prompt}
                ],
                stream=True,
            )

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            yield f"\n[ERROR]: {str(e)}"

    return StreamingResponse(generate(), media_type="text/plain")


@app.post("/chat")
async def chat(data: dict):
    """保留原有的整体查询接口，但仍会限制每页内容长度以避免超出模型输入限制。"""

    question = data.get("question")

    async def generate():
        try:
            context = ""
            sources = []

            if db:
                docs = db.similarity_search(question, k=3)
                for i, doc in enumerate(docs):
                    page = doc.metadata.get("page", "未知页")
                    filename = doc.metadata.get("source", "未知文件")
                    sources.append(f"{filename} 第{page}页")
                    truncated_content = doc.page_content[:500]
                    context += f"\n【来源{i+1} | {filename} 第{page}页】\n{truncated_content}\n"

            prompt = f"""
                你是一个AI助手，请严格根据提供的知识回答问题。

                知识：
                {context}

                问题：
                {question}
                """

            stream = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是一个专业助手"},
                    {"role": "user", "content": prompt}
                ],
                stream=True,
            )

            yield "[SOURCES] " + "|".join(sources) + "\n"

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            yield f"\n[ERROR]: {str(e)}"

    return StreamingResponse(generate(), media_type="text/plain")