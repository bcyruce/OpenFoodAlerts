"""Model name -> Classifier. The only place that knows which models exist.

The Anthropic SDK is imported only when a Claude model is built (it takes seconds to
import), so `ofa classify --dry-run`, `--model fake` and the tests that do not need it
stay fast.
"""

from openfoodalerts.classify.fake import FAKE_MODEL, KeywordClassifier
from openfoodalerts.classify.model import Classifier, ClassifierUnavailable
from openfoodalerts.eval.labelset import Taxonomy

CLAUDE_HAIKU_5_5 = "claude-haiku-5-5"
# The default model of `ofa classify` and `make eval-refresh` (spec §6.4).
DEFAULT_MODEL = CLAUDE_HAIKU_5_5
ANTHROPIC_MODELS = (CLAUDE_HAIKU_5_5,)
# Models `ofa classify --model` and `make eval-refresh MODEL=` accept.
MODELS = (*ANTHROPIC_MODELS, FAKE_MODEL)


def make_classifier(model: str, taxonomy: Taxonomy) -> Classifier:
    """Build the model's Classifier; raises ClassifierUnavailable (e.g. no API key)."""
    if model == FAKE_MODEL:
        return KeywordClassifier(taxonomy)
    if model in ANTHROPIC_MODELS:
        from openfoodalerts.classify.anthropic_model import AnthropicClassifier

        return AnthropicClassifier.from_env(model)
    raise ClassifierUnavailable(f"unknown model {model!r}; known: {', '.join(MODELS)}")
