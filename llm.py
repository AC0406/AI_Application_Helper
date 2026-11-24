import ollama
from pydantic import BaseModel

FAST, STRONG = "qwen3:8b", "qwen3:14b"

def ask(prompt: str, schema: type[BaseModel], system: str = "", model: str = STRONG):
    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        format=schema.model_json_schema(),
        options={"num_ctx": 8192, "temperature": 0.2},
    )
    try:
        r = ollama.chat(**kwargs, think=False)
    except TypeError:
        # Older ollama-python without the `think` param
        r = ollama.chat(**kwargs)
    return schema.model_validate_json(r.message.content)