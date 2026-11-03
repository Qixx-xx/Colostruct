"""A-group local LLM pipeline for ColoStruct."""

from .client import OllamaClient, OllamaConfig, LLMError
from .extraction import run_pass_b
from .preprocessing import run_pass_a
from .service import AGroupPipelineError, extract_clinical_info, extract_clinical_info_result

__all__ = [
    "OllamaClient", "OllamaConfig", "LLMError",
    "run_pass_a", "run_pass_b", "extract_clinical_info",
    "extract_clinical_info_result", "AGroupPipelineError",
]
