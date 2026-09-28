"""Bias-corrected failure prevalence for a monitoring period."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np


def corrected_mode_prevalence(
    sample_preds: Sequence[int],
    test_labels: Sequence[int],
    test_preds: Sequence[int],
    confidence: float = 0.95,
    bootstrap_iterations: int = 20000,
    seed: int | None = 7,
) -> dict[str, Any]:
    """Bias-corrected live prevalence for one mode from sampled verdicts.

    The contract, precisely:

      1. ``raw`` is the uncorrected flag rate: ``mean(sample_preds)``.
      2. Compute the frozen judge's failure sensitivity and pass specificity
         from ``test_labels`` and ``test_preds``. Both use the monitoring
         convention that 1 means a failure is present. Failure sensitivity is
         the flagged fraction of human-labeled failures. Pass specificity is
         the unflagged fraction of human-labeled passes.
      3. Compute the Rogan-Gladen point estimate, then resample the held-out
         records and sampled predictions to obtain a percentile-bootstrap
         interval. Use a seeded NumPy generator so the committed result is
         reproducible.
      4. Resample the monitoring predictions and the paired held-out records
         independently with replacement. Keep their original sample sizes.
         Discard a draw if the correction cannot be computed. Clamp each
         retained estimate to [0, 1], then take the percentile interval.
         Raise ``ValueError`` if no replicate is valid.

    Args:
        sample_preds: the judge's 0/1 verdicts over the UNIFORM BASE sample
            only (never the risk strata; they are biased toward failure by
            design).
        test_labels: human labels for the frozen Homework 5 judge's test
            split.
        test_preds: the frozen judge's predictions on that test split.
        confidence: interval confidence level.
        bootstrap_iterations: number of percentile-bootstrap replicates.
        seed: numpy seed for a reproducible interval; None leaves the RNG
            untouched.

    Returns:
        {"raw", "corrected", "ci_low", "ci_high", "confidence",
         "failure_sensitivity", "pass_specificity", "n_sample"}
        with "corrected" clamped to [0, 1] and rates rounded to 4 places.

    Raises:
        ValueError: if an input is empty, the held-out inputs have different
            lengths, a value is not 0 or 1, a class is absent, the judge is
            missing a usable correction, or no bootstrap replicate is valid.
    """
    sample = np.asarray(sample_preds, dtype=int)
    labels = np.asarray(test_labels, dtype=int)
    preds = np.asarray(test_preds, dtype=int)
    if sample.size == 0 or labels.size == 0:
        raise ValueError("sample and held-out inputs must be nonempty")
    if labels.size != preds.size:
        raise ValueError("held-out labels and predictions differ in length")
    if any(not set(np.unique(a)) <= {0, 1} for a in (sample, labels, preds)):
        raise ValueError("every value must be 0 or 1")
    if labels.min() == labels.max():
        raise ValueError("held-out labels need both failures and passes")

    def rates(labels: np.ndarray, preds: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        # Row-wise over a 2-D batch of resamples; NaN where a class is absent.
        failures = (labels == 1).sum(axis=-1)
        passes = (labels == 0).sum(axis=-1)
        with np.errstate(divide="ignore", invalid="ignore"):
            sensitivity = ((labels == 1) & (preds == 1)).sum(axis=-1) / failures
            specificity = ((labels == 0) & (preds == 0)).sum(axis=-1) / passes
        return sensitivity, specificity

    def rogan_gladen(raw, sensitivity, specificity):
        youden = sensitivity + specificity - 1
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(youden > 0, (raw + specificity - 1) / youden, np.nan)

    raw = float(sample.mean())
    sensitivity, specificity = (float(x) for x in rates(labels, preds))
    if sensitivity + specificity - 1 <= 0:
        raise ValueError("the judge is no better than chance; no usable correction")
    corrected = float(np.clip(rogan_gladen(raw, sensitivity, specificity), 0, 1))

    rng = np.random.default_rng(seed)
    raw_draws = rng.choice(sample, size=(bootstrap_iterations, sample.size)).mean(axis=1)
    rows = rng.integers(0, labels.size, size=(bootstrap_iterations, labels.size))
    sens_draws, spec_draws = rates(labels[rows], preds[rows])
    draws = rogan_gladen(raw_draws, sens_draws, spec_draws)
    draws = np.clip(draws[np.isfinite(draws)], 0, 1)
    if draws.size == 0:
        raise ValueError("no bootstrap replicate produced a valid correction")
    tail = (1 - confidence) / 2 * 100
    ci_low, ci_high = np.percentile(draws, [tail, 100 - tail])

    return {
        "raw": round(raw, 4),
        "corrected": round(corrected, 4),
        "ci_low": round(float(ci_low), 4),
        "ci_high": round(float(ci_high), 4),
        "confidence": confidence,
        "failure_sensitivity": round(sensitivity, 4),
        "pass_specificity": round(specificity, 4),
        "n_sample": int(sample.size),
    }
