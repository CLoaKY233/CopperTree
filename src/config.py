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
    retell_api_key: str = ""
    retell_agent_id: str = ""       # pre-created agent on Retell dashboard
    retell_phone_number: str = ""
    retell_webhook_secret: str = "" # optional — validates Retell webhook signatures
    eval_mode: bool = False
    webhook_port: int = 8001        # FastAPI webhook server port
    azure_foundry_endpoint: str = "https://coppertree1.services.ai.azure.com/"
    azure_voice_deployment: str = ""      # voice model, defaults to azure_openai_deployment
    azure_voice_voice: str = "en-US-Ava:DragonHDLatestNeural"
    azure_voice_max_duration: int = 300  # seconds before auto-ending session
    currency_symbol: str = "₹"          # default currency for collections


settings = Settings(
    azure_openai_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    azure_openai_api_key=os.environ["AZURE_OPENAI_API_KEY"],
    azure_openai_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    mongo_uri=os.environ["MONGO_URI"],
    mongo_db=os.environ["MONGO_DB"],
    temporal_host=os.environ.get("TEMPORAL_HOST", "localhost:7233"),
    retell_api_key=os.environ.get("RETELL_API_KEY", ""),
    retell_agent_id=os.environ.get("RETELL_AGENT_ID", ""),
    retell_phone_number=os.environ.get("RETELL_PHONE_NUMBER", ""),
    retell_webhook_secret=os.environ.get("RETELL_WEBHOOK_SECRET", ""),
    eval_mode=os.environ.get("EVAL_MODE", "false").lower() == "true",
    webhook_port=int(os.environ.get("WEBHOOK_PORT", "8001")),
    azure_foundry_endpoint=os.environ.get("AZURE_FOUNDRY_ENDPOINT", "https://coppertree1.services.ai.azure.com/"),
    azure_voice_deployment=os.environ.get("AZURE_VOICE_DEPLOYMENT", ""),
    azure_voice_voice=os.environ.get("AZURE_VOICE_VOICE", "en-US-Ava:DragonHDLatestNeural"),
    azure_voice_max_duration=int(os.environ.get("AZURE_VOICE_MAX_DURATION", "300")),
    currency_symbol=os.environ.get("CURRENCY_SYMBOL", "₹"),
)
