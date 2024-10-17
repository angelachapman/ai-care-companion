from operator import itemgetter
import os
from typing import cast
from dotenv import load_dotenv

import chainlit as cl

from langchain_qdrant import QdrantVectorStore
from langchain_anthropic import ChatAnthropic
from langchain.schema.runnable import Runnable
from langchain.schema.runnable.config import RunnableConfig
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import OpenAIEmbeddings
from langchain.retrievers import EnsembleRetriever
from langchain_core.prompts import PromptTemplate

from vars import SYSTEM_PROMPT, HAIKU, MAX_CONTEXT, GREETING, COLLECTION_NAME, URL
from utils import add_sources

import logging
logging.basicConfig(level=logging.INFO)

# Environment vars
load_dotenv('.env')
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not ANTHROPIC_API_KEY or not OPENAI_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable is not set")

# Embedding model
from langchain_openai import OpenAIEmbeddings
openai_embeddings = OpenAIEmbeddings(
    model="text-embedding-3-large",
    openai_api_key=OPENAI_API_KEY  
)

# Initialize retriever
def init_retriever ():
    store = QdrantVectorStore.from_existing_collection (
        embedding=openai_embeddings,
        collection_name=COLLECTION_NAME,
        url=URL
    )
    mmr_retriever = store.as_retriever(
        search_type="mmr",
        search_kwargs={'k': 10, 'lambda_mult': 0.1}
    )
    similarity_retriever = store.as_retriever(k=10)
    retriever = EnsembleRetriever(retrievers=[mmr_retriever,similarity_retriever],
                                  id_key="url")
    return retriever

# Initialize main RAG chain
def init_chain (retriever):
    rag_prompt = PromptTemplate.from_template(SYSTEM_PROMPT)
    llm = ChatAnthropic(
        model=HAIKU,    
        anthropic_api_key=ANTHROPIC_API_KEY
    )
    rag_chain = (
        {"context": itemgetter("query") | retriever | (lambda docs: docs[:MAX_CONTEXT]), 
         "query": itemgetter("query"), 
         "history": ""} 
        | RunnablePassthrough.assign(context=itemgetter("context"))
        | {"response": rag_prompt | llm, "context": itemgetter("context")}
    )
    return rag_chain

@cl.on_chat_start
async def start():    
    try:
        retreiver = init_retriever()
    except Exception as e:
        logger.error(f"error initializing retriever: {e}")

    try: 
        rag_chain = init_chain(retriever)
    except Exception as e:
        logger.error(f"error initializing RAG chain: {e}")
    
    cl.user_session.set("chain",rag_chain)

    msg = cl.Message(content=GREETING)
    await msg.send()

@cl.on_message
async def main(message: cl.Message):
    chain = cast(Runnable, cl.user_session.get("chain"))  # type: Runnable
    msg = cl.Message(content="")

    try:
        async for chunk in chain.astream(
            {"input": message.content},
            config=RunnableConfig(callbacks=[cl.LangchainCallbackHandler()]),
        ):
            await msg.stream_token(chunk["response"].content)

    except Exception as e:
        print(f"Error in chain execution: {e}")
        msg.content = "An error occurred processing your request"

    await msg.send()

if __name__ == "__main__":
    cl.run()