from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import CharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings

def build_db(file_path):

    import shutil, os

    if os.path.exists("./chroma_db"):
        shutil.rmtree("./chroma_db")

    loader = PyPDFLoader(file_path)
    docs = loader.load()

    splitter = CharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=150
    )

    split_docs = splitter.split_documents(docs)

    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )

    db = Chroma.from_documents(
        split_docs,
        embeddings,
        persist_directory="./chroma_db"
    )

    return db