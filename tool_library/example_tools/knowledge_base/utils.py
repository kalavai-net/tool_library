import shutil
from pathlib import Path
import os
import hashlib

from langchain_community.document_loaders import (
    PyPDFium2Loader,
    TextLoader,
    Docx2txtLoader
)
from langchain.retrievers import (
    ContextualCompressionRetriever,
    EnsembleRetriever,
    ParentDocumentRetriever
)
from langchain.retrievers.document_compressors import EmbeddingsFilter
from langchain.storage import LocalFileStore
from langchain_community.vectorstores import Chroma
from langchain.storage._lc_store import create_kv_docstore
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings.huggingface import HuggingFaceEmbeddings
from langchain_community.embeddings import HuggingFaceInferenceAPIEmbeddings
from langchain_openai import OpenAIEmbeddings


FULL_DOC_LENGTH = 2000
DOC_LENGTH = 500
OVERLAP_LENGTH = 0
SEARCH_TYPE = "mmr"


def save_upload_file(upload_file, base_folder, username):

    os.makedirs(base_folder, exist_ok=True)

    file_name = username+"_"+upload_file.filename
    m = hashlib.sha256()
    m.update(file_name.encode('utf-8'))

    #hacky file name hashing with extension
    hash_file_name = m.hexdigest()+ "."+file_name.split(".")[-1]

    file_path = os.path.join(base_folder, hash_file_name)

    destination = Path(file_path)
    try:
        with destination.open("wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)
    finally:
        upload_file.file.close()
        return file_path, hash_file_name

def load_documents_from_file(file_path):
    """Load documents from a folder of specific extension"""
    
    docs = []
    extensions = {
        ".txt": TextLoader,
        ".pdf": PyPDFium2Loader,
        ".docx": Docx2txtLoader
    }
    for extension, loader_cls in extensions.items():
        if extension in file_path:
            loader = loader_cls(file_path)
            docs.extend(loader.load())

    return docs


def get_parent_text_splitter():
    return RecursiveCharacterTextSplitter(
        #separators=["\n\n", "\n", ". ", ""],
        keep_separator=True,
        chunk_size=FULL_DOC_LENGTH,
        chunk_overlap=0,
        length_function=len,
        is_separator_regex=False,
    )
    

def get_chunk_text_splitter():
    return RecursiveCharacterTextSplitter(
        #separators=["\n\n", "\n", ". ", ""],
        keep_separator=True,
        chunk_size=DOC_LENGTH,
        chunk_overlap=OVERLAP_LENGTH,
        length_function=len,
        is_separator_regex=False,
    )

def load_embedding(embedder_config):
    # embedding = HuggingFaceInferenceAPIEmbeddings(
    #     api_url=embedder_config.api_url,
    #     api_key=embedder_config.api_key,
    #     embedding_id=embedder_config.embedding_id
    # )
    embedding = HuggingFaceEmbeddings(
        model_name=embedder_config.embedding_id,
        model_kwargs={"device": "cuda"}
    )

    # embedding = OpenAIEmbeddings(
    #     model=embedder_config.embedding_id, 
    #     dimensions=1024,
    #     openai_api_key=embedder_config.api_key)
    return embedding


def load_document_retriever(index_name, embedding, top_k=10, similarity_threshold=0.5, docs=None, base_path="."):
    import time
    t = time.time()
    doc_store = create_kv_docstore(LocalFileStore(f"{base_path}/doc_store/{index_name}"))
    vector_store = Chroma(index_name, embedding, persist_directory=f"{base_path}/vector_store/{index_name}")

    child_splitter = get_chunk_text_splitter()
    parent_splitter = get_parent_text_splitter()
    
    retriever = ParentDocumentRetriever(
        vectorstore=vector_store,
        docstore=doc_store,
        child_splitter=child_splitter,
        parent_splitter=parent_splitter,
        search_type=SEARCH_TYPE,
        search_kwargs={"k": top_k}
    )
    if docs is not None:
        retriever.add_documents(docs)

    embeddings_filter = EmbeddingsFilter(embeddings=embedding, similarity_threshold=similarity_threshold)
    final_retriever = ContextualCompressionRetriever(
        base_compressor=embeddings_filter, base_retriever=retriever
    )
    print(f"-----Embeddings loaded: {time.time()-t:.2f}")
    
    # final_retriever = EnsembleRetriever(
    #     retrievers=[final_retriever], weights=[0.5]
    # )
    
    return final_retriever


def index_documents(docs, index_name, base_folder, embedding):

    retriever = load_document_retriever(
        index_name=index_name,
        embedding=embedding,
        docs=docs,
        base_path=base_folder
    )
    return retriever


def process_retriever_results(results):
    """Process results from retrievers into something we want to send back via HTTP responses"""
    processed_results = []
    for result in results:
        res = result
        res.state["embedded_doc"] = None
        processed_results.append(res)
    return processed_results
