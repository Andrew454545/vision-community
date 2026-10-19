"""Diagnostic comparison of version-4 scene records; never a quality gate.

Each view decodes as positive binary16 scale * 768 signed int8 values.
All views have equal weight in these summaries. Location/view identity must
already be established by the caller; matching lengths alone does not do so.
"""
from __future__ import annotations

import math
import statistics
import struct

RECORD_BYTES = 3080
VIEW_BYTES = 770
DIMENSIONS = 768


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty_distribution")

    def percentile(fraction):
        position = (len(ordered) - 1) * fraction
        lower = math.floor(position)
        upper = math.ceil(position)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    return {"min": ordered[0], "p01": percentile(0.01), "p05": percentile(0.05),
            "median": percentile(0.5), "p95": percentile(0.95), "p99": percentile(0.99),
            "max": ordered[-1], "mean": statistics.fmean(ordered)}


def decoded_difference(candidate: bytes, reference: bytes) -> dict:
    """Return scale-aware error and scale-invariant direction diagnostics.

    Relative L2 uses the reference norm as denominator. Normalized L2 compares
    unit vectors. These are numerical diagnostics, not measured search quality
    or an acceptance decision. Invalid/zero-norm vectors cannot produce a
    meaningful cosine and are rejected rather than silently skipped.
    """
    if not candidate or len(candidate) != len(reference) or len(candidate) % RECORD_BYTES:
        raise ValueError("incomparable_geometry")
    cosines, normalized_errors, relative_errors, norm_ratios = [], [], [], []
    absolute_error = max_absolute_error = squared_error = 0.0
    worst_view = 0
    minimum_cosine = 2.0
    for view_index, offset in enumerate(range(0, len(candidate), VIEW_BYTES)):
        scales = [struct.unpack_from("<e", blob, offset)[0] for blob in (candidate, reference)]
        if any(not math.isfinite(scale) or scale <= 0 for scale in scales):
            raise ValueError("invalid_view_scale")
        left = struct.unpack_from("<768b", candidate, offset + 2)
        right = struct.unpack_from("<768b", reference, offset + 2)
        left_norm2 = sum(value * value for value in left)
        right_norm2 = sum(value * value for value in right)
        if not left_norm2 or not right_norm2:
            raise ValueError("zero_norm_view")
        cosine = sum(a * b for a, b in zip(left, right)) / math.sqrt(left_norm2 * right_norm2)
        cosine = max(-1.0, min(1.0, cosine))
        cosines.append(cosine)
        normalized_errors.append(math.sqrt(max(0.0, 2.0 - 2.0 * cosine)))
        if cosine < minimum_cosine:
            minimum_cosine, worst_view = cosine, view_index
        view_error2 = 0.0
        for a, b in zip(left, right):
            difference = abs(a * scales[0] - b * scales[1])
            absolute_error += difference
            max_absolute_error = max(max_absolute_error, difference)
            view_error2 += difference * difference
        squared_error += view_error2
        relative_errors.append(math.sqrt(view_error2) / (math.sqrt(right_norm2) * scales[1]))
        norm_ratios.append(math.sqrt(left_norm2 / right_norm2) * scales[0] / scales[1])
    coordinates = len(cosines) * DIMENSIONS
    return {
        "views": len(cosines), "cosine_similarity": distribution(cosines),
        "normalized_l2_distance": distribution(normalized_errors),
        "relative_l2_error": distribution(relative_errors),
        "candidate_to_reference_norm_ratio": distribution(norm_ratios),
        "decoded_coordinate_mae": absolute_error / coordinates,
        "decoded_coordinate_rmse": math.sqrt(squared_error / coordinates),
        "decoded_coordinate_max_absolute_error": max_absolute_error,
        "lowest_cosine_location_ordinal": worst_view // 4,
        "lowest_cosine_view_offset": worst_view % 4,
        "percentiles": "linear interpolation over equally weighted views",
        "interpretation": "DIAGNOSTIC_ONLY_NO_ACCEPTANCE_THRESHOLD",
    }
