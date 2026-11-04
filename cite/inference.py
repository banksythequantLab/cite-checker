"""Vultr Serverless Inference client (OpenAI-compatible). Model IDs resolved live."""
from __future__ import annotations
import os
DEFAULT_BASE_URL = "https://api.vultrinference.com/v1"
class InferenceError(RuntimeError): ...
class Vultr:
    def __init__(self):
        self.api_key = os.environ.get("VULTR_INFERENCE_API_KEY", "")
        self.base_url = os.environ.get("VULTR_INFERENCE_BASE_URL", DEFAULT_BASE_URL)
        self.model = os.environ.get("DOCKET_MODEL", "glm-5.3-flash")
        self._c = None
    @property
    def client(self):
        if self._c is None:
            if not self.api_key:
                raise InferenceError("VULTR_INFERENCE_API_KEY unset")
            from openai import OpenAI
            self._c = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._c
    def models(self): return [m.id for m in self.client.models.list().data]
