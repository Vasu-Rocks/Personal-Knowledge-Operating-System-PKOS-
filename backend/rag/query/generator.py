import os
import requests
import logging

# Connect native Uvicorn-safe routing
logger = logging.getLogger(__name__)

# OS-Level Environment Mapping
LLM_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/chat")

# Optimization: Persistent TCP Connection Pipeline
session = requests.Session()

def generate_rag_response(messages: list[dict[str, str]], model_name: str = None) -> str:
    """
    Sub-Module 3.4: The Generative Engine
    Transmits the mathematically fenced context to the local LLM socket.
    """
    if not messages:
        logger.error("[ERROR] Generative Engine received an empty messages array and aborted network transmission.")
        return "System Error: The system aborted generation because no context was successfully built."
        
    # Evaluate model_name at execution time to allow dynamic OS Environment overrides!
    active_model = model_name if model_name else os.getenv("OLLAMA_MODEL", "llama3.2")
    
    payload = {
        "model": active_model,
        "messages": messages,
        "stream": False, 
        "keep_alive": "15m", # Optimization 1: Prevents 30s cold-start delays across queries
        "options": {
            "temperature": 0.1,  
            "num_predict": 512,
            "num_ctx": 4096,     
            "top_p": 0.9         
        }
    }
    
    try:
        # Note: 120s timeout is critical! Cold-starting models into your 16GB RAM can take ~30s on the first prompt.
        response = session.post(LLM_API_URL, json=payload, timeout=120.0)
        
        if response.status_code != 200:
            logger.error(f"[ERROR] LLM API Status {response.status_code} -> {response.text}")
            return f"System Error: LLM Engine returned status {response.status_code}."
            
        return response.json().get("message", {}).get("content", "").strip()

    except requests.exceptions.ConnectionError as e:
        logger.error(f"[ERROR] Ollama Connection Failed: {str(e)}")
        return f"System Error: Cannot connect to {LLM_API_URL}. Is Ollama running?"
    except requests.exceptions.Timeout as e:
        logger.error(f"[ERROR] Ollama Thermal Timeout: {str(e)}")
        return "System Error: Inference timeout. Model took too long to load into RAM."
    except requests.exceptions.JSONDecodeError as e:
        logger.error(f"[ERROR] Ollama Malformed Output: {str(e)}")
        return "System Error: Local AI returned invalid parsing data natively."
    except Exception as e:
        logger.error(f"[ERROR] Unexpected Execution Crash: {str(e)}")
        return f"System Error: Unexpected failure: {str(e)}"
