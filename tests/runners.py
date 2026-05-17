from __future__ import annotations

from krtour_map.parser import parse_feature_response
from krtour_map.processor import process_feature_response

RUNNERS = {
    "feature_summary": {
        "parse": parse_feature_response,
        "process": process_feature_response,
    },
}
