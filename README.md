# ai-care-companion

Environment Creation:
1. Create a virtual environment and activate it
1. 'pip install -r requirements.txt'

Qdrant Setup:
To start qdrant:
Make sure to install **Docker** if you haven't already.

'docker run -p 6333:6333 -p 6334:6334 \
    -v $(pwd)/qdrant_storage:/qdrant/storage:z \
    qdrant/qdrant'

To check if it's running:
navigate to localhost:6333/dashboard in a browser

Data Processing:
1. Ensure your notebook is using the virtual environment
1. 'fetch_data.ipynb': Scrape the target websites and save as a local file
1. 'chunk_and_load_data.ipynb': Chunk the data and add it to a vector database