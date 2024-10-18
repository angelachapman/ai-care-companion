from langchain.schema import Document

# Simple function to format sources as links before appending to a response
def add_sources(context:list[Document])->str:
    sources = []
    for idx, doc in enumerate(context, 1):
        title = doc.metadata.get('title', f"Source {idx}")
        url = doc.metadata.get('url', 'No URL')
        sources.append(f"[{idx}]({url})")
    sources_str = "\n\nSources:" + " ".join(sources)
    return sources_str
    