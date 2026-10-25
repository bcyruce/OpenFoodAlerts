"""Model name -> Classifier. The only place that knows which models exist.

The provider SDKs are imported only when one of their models is built (`anthropic` takes
seconds to import), so `ofa classify --dry-run`, `--model fake` and the tests that do not
need them stay fast.
"""

from typing import TYPE_CHECKING

from openfoodalerts.classify.fake import FAKE_MODEL, KeywordClassifier
from openfoodalerts.classify.model import Classifier, ClassifierUnavailable
from openfoodalerts.eval.labelset import Taxonomy

if TYPE_CHECKING:  # classify.batch imports the job and the database layer
    from openfoodalerts.classify.batch import BatchBackend

CLAUDE_HAIKU_5_5 = "claude-haiku-5-5"
GPT_5_MINI = "gpt-5-mini"
DEEPSEEK_FLASH = "deepseek-flash"
# The default model of `ofa classify` and `make eval-refresh` (spec §6.4).
DEFAULT_MODEL = CLAUDE_HAIKU_5_5
ANTHROPIC_MODELS = (CLAUDE_HAIKU_5_5,)
# the earlier second candidate (ticket 21), key OPENAI_API_KEY; shuts down on 2026-12-11
OPENAI_MODELS = (GPT_5_MINI,)
# spec §6.4's second candidate, key DEEPSEEK_API_KEY; no Batch API
DEEPSEEK_MODELS = (DEEPSEEK_FLASH,)
# Models `ofa classify --model` and `make eval-refresh MODEL=` accept.
MODELS = (*ANTHROPIC_MODELS, *OPENAI_MODELS, *DEEPSEEK_MODELS, FAKE_MODEL)


def provider_of(model: str) -> str:
    """anthropic, openai, deepseek or fake; raises ClassifierUnavailable for an unknown
    model."""
    if model in ANTHROPIC_MODELS:
        return "anthropic"
    if model in OPENAI_MODELS:
        return "openai"
    if model in DEEPSEEK_MODELS:
        return "deepseek"
    if model == FAKE_MODEL:
        return "fake"
    raise ClassifierUnavailable(f"unknown model {model!r}; known: {', '.join(MODELS)}")


def make_classifier(model: str, taxonomy: Taxonomy) -> Classifier:
    """Build the model's Classifier; raises ClassifierUnavailable (e.g. no API key)."""
    provider = provider_of(model)
    if provider == "fake":
        return KeywordClassifier(taxonomy)
    if provider == "openai":
        from openfoodalerts.classify.openai_model import OpenAIClassifier

        return OpenAIClassifier.from_env(model)
    if provider == "deepseek":
        from openfoodalerts.classify.deepseek_model import DeepSeekClassifier

        return DeepSeekClassifier.from_env(model)
    from openfoodalerts.classify.anthropic_model import AnthropicClassifier

    return AnthropicClassifier.from_env(model)


def has_batch_api(model: str) -> bool:
    """Whether `ofa classify --batch` can use the model (DeepSeek has no Batch API)."""
    return provider_of(model) != "deepseek"


def make_batch_backend(model: str, taxonomy: Taxonomy) -> "BatchBackend":
    """The model's Batch API (`ofa classify --batch`); raises ClassifierUnavailable."""
    provider = provider_of(model)
    if not has_batch_api(model):
        raise ClassifierUnavailable(
            f"{model} has no Batch API; run `ofa classify` without --batch"
            " (--concurrency N for the backfill)"
        )
    if provider == "fake":
        from openfoodalerts.classify.fake_batch import FakeBatches

        return FakeBatches(taxonomy)
    if provider == "openai":
        from openfoodalerts.classify.openai_model import OpenAIBatches, OpenAIClassifier

        return OpenAIBatches(OpenAIClassifier.from_env(model))
    from openfoodalerts.classify.anthropic_model import AnthropicBatches, AnthropicClassifier

    return AnthropicBatches(AnthropicClassifier.from_env(model))
