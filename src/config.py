import os

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class Settings(BaseModel):
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_deployment: str
    mongo_uri: str
    mongo_db: str
    temporal_host: str


settings = Settings(
    azure_openai_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    azure_openai_api_key=os.environ["AZURE_OPENAI_API_KEY"],
    azure_openai_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    mongo_uri=os.environ["MONGO_URI"],
    mongo_db=os.environ["MONGO_DB"],
    temporal_host=os.environ.get("TEMPORAL_HOST", "localhost:7233"),
)
