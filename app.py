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

from vars import SYSTEM_PROMPT, HAIKU, MAX_CONTEXT, GREETING, COLLECTION_NAME, URL, SONNET, TEMPERATURE, TOP_P
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
def init_retriever():
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
    print(f"Initialized retriever of type {type(retriever)}")
    return retriever

# Initialize main RAG chain
def init_chain(retriever) -> Runnable:
    rag_prompt = PromptTemplate.from_template(SYSTEM_PROMPT)
    llm = ChatAnthropic(
        model=SONNET,    
        anthropic_api_key=ANTHROPIC_API_KEY,
        temperature=TEMPERATURE,
        top_p=TOP_P
    )
    rag_chain = (
        {
            "context": itemgetter("query") | retriever | (lambda docs: docs[:MAX_CONTEXT]), 
            "query": itemgetter("query"), 
        } 
        | RunnablePassthrough.assign(context=itemgetter("context"))
        | {"response": rag_prompt | llm, "context": itemgetter("context")}
    )
    return rag_chain

@cl.on_chat_start
async def start():    
    retriever = None
    try:
        retriever = init_retriever()
    except Exception as e:
        print(f"error initializing retriever: {e}")
    if not retriever: raise ValueError("Error initializing retriever")

    rag_prompt = PromptTemplate.from_template(SYSTEM_PROMPT)
    llm = ChatAnthropic(
        model=HAIKU,    
        anthropic_api_key=ANTHROPIC_API_KEY
    )

    cl.user_session.set("retriever",retriever)
    cl.user_session.set("rag_prompt",rag_prompt)
    cl.user_session.set("llm",llm)

    msg = cl.Message(content=GREETING)
    await msg.send()

@cl.on_message
async def main(message: cl.Message):
    retriever = cl.user_session.get("retriever")
    rag_prompt = cl.user_session.get("rag_prompt")
    llm = cl.user_session.get("llm")
    msg = cl.Message(content="")

    try:
        context_docs = await retriever.ainvoke(message.content)
        context_docs = context_docs[:MAX_CONTEXT]  # Limit context size if necessary

        sources = add_sources(context_docs)

        formatted_context = "\n".join([doc.page_content for doc in context_docs])
        prompt_inputs = {
            'context': formatted_context,
            'query': message.content
        }

        prompt_text = rag_prompt.format(**prompt_inputs)

        async for chunk in llm.astream(prompt_text):
            print(chunk)
            await msg.stream_token(chunk.content)

        await msg.stream_token(sources)
        await msg.send()

    except Exception as e:
        print(f"Error in chain execution: {e}")
        await cl.Message(content="An error occurred processing your request").send()


if __name__ == "__main__":
    cl.run()