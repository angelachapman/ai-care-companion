from operator import itemgetter
import os
from typing import cast
from dotenv import load_dotenv

import chainlit as cl
import asyncio

from langchain_qdrant import QdrantVectorStore
from langchain_anthropic import ChatAnthropic
from langchain_openai import OpenAIEmbeddings
from langchain.retrievers import EnsembleRetriever
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from langchain.memory import ConversationBufferWindowMemory
from langchain.chains import create_history_aware_retriever
from langchain_core.prompts import MessagesPlaceholder

from vars import SYSTEM_PROMPT, MAX_CONTEXT, GREETING, COLLECTION_NAME, URL
from vars import HAIKU, SONNET, TEMPERATURE, TOP_P, MAX_TOKENS, MAX_MEMORY
from utils import add_sources, get_toolbelt, use_eldercare_api

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
def init_retriever(llm):

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
    ensemble_retriever = EnsembleRetriever(retrievers=[mmr_retriever,similarity_retriever])
    
    retriever_prompt = ChatPromptTemplate.from_messages([
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "{input}"),
        ("user", "Given the above conversation, generate a search query to look up to get information relevant to the conversation")
    ])
    retriever_chain = create_history_aware_retriever(llm, ensemble_retriever, retriever_prompt)

    print(f"Initialized retriever of type {type(retriever_chain)}")
    return retriever_chain

@cl.on_chat_start
async def start():    

    rag_prompt = PromptTemplate.from_template(SYSTEM_PROMPT)
    haiku_llm = ChatAnthropic(
        model=HAIKU,    
        anthropic_api_key=ANTHROPIC_API_KEY,
        temperature = TEMPERATURE,
        top_p = TOP_P,
        max_tokens = MAX_TOKENS
    )
    sonnet_llm = ChatAnthropic(
        model= SONNET,
        anthropic_api_key=ANTHROPIC_API_KEY,
        temperature = TEMPERATURE,
        top_p = TOP_P,
        max_tokens = MAX_TOKENS
    )
    llm_with_tools = ChatAnthropic(
        model="claude-3-haiku-20240307",    
        anthropic_api_key=ANTHROPIC_API_KEY,
    ).bind_tools(get_toolbelt())

    memory = ConversationBufferWindowMemory(k=MAX_MEMORY)

    retriever = None
    try:
        retriever = init_retriever(haiku_llm)
    except Exception as e:
        print(f"error initializing retriever: {e}")
    if not retriever: raise ValueError("Error initializing retriever")

    memory.chat_memory.add_ai_message(GREETING)

    cl.user_session.set("retriever",retriever)
    cl.user_session.set("rag_prompt",rag_prompt)
    cl.user_session.set("llm",haiku_llm)
    cl.user_session.set("llm_with_tools",llm_with_tools)
    cl.user_session.set("memory",memory)

    msg = cl.Message(content=GREETING)
    await msg.send()


@cl.on_message
async def main(message: cl.Message):

    retriever = cl.user_session.get("retriever")
    rag_prompt = cl.user_session.get("rag_prompt")
    llm = cl.user_session.get("llm")
    llm_with_tools = cl.user_session.get("llm_with_tools")
    
    memory = cl.user_session.get("memory")
    memory.chat_memory.add_user_message(message.content)

    print(f"memory: {memory.load_memory_variables({})['history']}")

    msg = cl.Message(content="")

    context_docs = None
    try:
        retriever_inputs = {
            "input": message.content,
            "chat_history": memory.chat_memory.messages
        }
        retriever_task = retriever.ainvoke(retriever_inputs)
        tool_output_task = use_eldercare_api(memory.chat_memory.messages, llm_with_tools)
        context_docs, tool_output = await asyncio.gather(retriever_task, tool_output_task)

        #context_docs = await retriever.ainvoke(retriever_inputs)

        context_docs = context_docs[:MAX_CONTEXT]  # Limit context size if necessary
        sources = add_sources(context_docs)
        formatted_context = "\n".join([doc.page_content for doc in context_docs])

        #tool_output = await use_eldercare_api(memory.chat_memory.messages,llm_with_tools)

    except Exception as e:
        print(f"Error in retrieval or tool use: {e}")
        await cl.Message(content="An error occurred processing your request").send()

    if context_docs:
        try:
            prompt_inputs = {
                'context': formatted_context,
                'history': memory.load_memory_variables({})["history"],
                'tool_output': tool_output,
                'query': message.content
            }

            prompt_text = rag_prompt.format(**prompt_inputs)

            ai_response = ""
            async for chunk in llm.astream(prompt_text):
                #print(chunk)
                ai_response+=chunk.content
                await msg.stream_token(chunk.content)

            await msg.stream_token(sources)
            await msg.send()
            memory.chat_memory.add_ai_message(ai_response)

        except Exception as e:
            print(f"Error in chain execution: {e}")
            await cl.Message(content="An error occurred processing your request").send()

    cl.user_session.set("memory",memory)

if __name__ == "__main__":
    cl.run()