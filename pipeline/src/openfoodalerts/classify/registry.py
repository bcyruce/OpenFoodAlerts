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
# The default model of `ofa classify` and `make eval-refresh` (spec §6.4).
DEFAULT_MODEL = CLAUDE_HAIKU_5_5
ANTHROPIC_MODELS = (CLAUDE_HAIKU_5_5,)
# spec §6.4's second candidate (ticket 21), key OPENAI_API_KEY
OPENAI_MODELS = (GPT_5_MINI,)
# Models `ofa classify --model` and `make eval-refresh MODEL=` accept.
MODELS = (*ANTHROPIC_MODELS, *OPENAI_MODELS, FAKE_MODEL)


def provider_of(model: str) -> str:
    """anthropic, openai or fake; raises ClassifierUnavailable for an unknown model."""
    if model in ANTHROPIC_MODELS:
        return "anthropic"
    if model in OPENAI_MODELS:
        return "openai"
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
    from openfoodalerts.classify.anthropic_model import AnthropicClassifier

    return AnthropicClassifier.from_env(model)


def make_batch_backend(model: str, taxonomy: Taxonomy) -> "BatchBackend":
    """The model's Batch API (`ofa classify --batch`); raises ClassifierUnavailable."""
    provider = provider_of(model)
    if provider == "fake":
        from openfoodalerts.classify.fake_batch import FakeBatches

        return FakeBatches(taxonomy)
    if provider == "openai":
        from openfoodalerts.classify.openai_model import OpenAIBatches, OpenAIClassifier

        return OpenAIBatches(OpenAIClassifier.from_env(model))
    from openfoodalerts.classify.anthropic_model import AnthropicBatches, AnthropicClassifier

    return AnthropicBatches(AnthropicClassifier.from_env(model))
