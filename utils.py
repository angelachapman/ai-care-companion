from langchain.schema import Document

# Simple function to format sources as links before appending to a response
def add_sources(context:list[Document])->str:
    sources_str = ""
    if len(context)>0:
        i = 1
        sources_str = "Sources: "

        for doc in context:
            if not doc.metadata.get("url") in sources_str:
                sources_str += f'[<a href="{doc.metadata["url"]}">{i}</a>] '
                i+=1

    return sources_str