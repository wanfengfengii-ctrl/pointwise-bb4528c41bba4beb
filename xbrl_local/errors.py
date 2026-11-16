"""Public input, qualification and identity errors."""
from dataclasses import dataclass
import json


class InputError(ValueError):
    pass


class ConflictError(InputError):
    pass


@dataclass(frozen=True)
class Issue:
    fact_id: str
    metric: str
    context_id: str


class QualificationError(InputError):
    def __init__(self, issues):
        self.issues = tuple(issues)
        super().__init__('DIMENSION_QUALIFICATION: ' + ', '.join(
            f'{i.fact_id} ({i.metric}, {i.context_id})' for i in self.issues))


class CalculationError(InputError):
    def __init__(self, groups):
        self.groups = groups
        super().__init__('CALCULATION_INCONSISTENT: ' + json.dumps(
            groups, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
