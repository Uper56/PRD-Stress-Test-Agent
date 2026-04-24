"""Cross-challenge orchestration — the "triple-redundancy" safety net.

After the four critics have produced their independent critiques, each critic
gets a second pass in which it sees the *other three* critics' findings (plus
any prior challenges) and is asked to push back, add a missed angle, or stay
silent. The purpose is to reduce false negatives — one critic seeing something
that another should have caught.

Three safety layers are stacked:

  1. Hard round cap          — MAX_CROSS_CHALLENGE_ROUNDS (from .env, default 2).
  2. Early-exit on empty R1  — if no critic has anything to say in round 1,
                                we declare convergence and skip round 2.
  3. Similarity convergence   — after round 2, if its content duplicates round
                                1 above CONVERGENCE_SIMILARITY_THRESHOLD, we
                                flag convergence_signal=True.

Similarity uses `difflib.SequenceMatcher` to avoid pulling in embedding deps.
TODO: replace with real sentence embeddings (sentence-transformers or the
OpenAI embeddings endpoint) once the school API is provisioned.
"""

from __future__ import annotations

import asyncio
import logging
from difflib import SequenceMatcher

from ..agents.critics.business import run_business_challenge
from ..agents.critics.design import run_design_challenge
from ..agents.critics.engineering import run_engineering_challenge
from ..agents.critics.user_advocate import run_user_advocate_challenge
from ..config import MAX_CROSS_CHALLENGE_ROUNDS as _CFG_MAX_ROUNDS
from ..llm.provider import LLMProvider
from .state import CrossChallenge, GraphState

logger = logging.getLogger(__name__)


MAX_CROSS_CHALLENGE_ROUNDS: int = _CFG_MAX_ROUNDS
# SequenceMatcher is a character-level ratio; 0.85 is what embeddings would
# need, but with a lexical matcher 0.75 is a saner starting point. Tune once
# we swap in real embeddings.
CONVERGENCE_SIMILARITY_THRESHOLD: float = 0.75


_CHALLENGERS = (
    ("user_advocate", run_user_advocate_challenge),
    ("engineering", run_engineering_challenge),
    ("business", run_business_challenge),
    ("design", run_design_challenge),
)


def _blob(challenges: list[CrossChallenge]) -> str:
    """Flatten a list of challenges into a single comparable text blob."""
    parts = sorted(
        f"{c.challenger}|{c.target_critique_id}|{c.counter_finding}"
        for c in challenges
    )
    return "\n".join(parts)


def _texts_converged(a: list[CrossChallenge], b: list[CrossChallenge]) -> bool:
    """Return True iff the two rounds are similar enough to call it converged."""
    if not b:
        return True  # nothing new raised in the newer round
    if not a:
        return False  # first round had content but we're comparing to nothing
    ratio = SequenceMatcher(None, _blob(a), _blob(b)).ratio()
    logger.debug("cross-challenge similarity ratio = %.3f", ratio)
    return ratio >= CONVERGENCE_SIMILARITY_THRESHOLD


async def _run_round(
    state: GraphState,
    llm: LLMProvider,
    round_n: int,
    prior_challenges: list[CrossChallenge],
) -> list[CrossChallenge]:
    """Run one round of cross-challenge in parallel across the four critics."""
    critiques = state.get("critiques", []) or []

    # Each critic sees the full critique list; run_challenger filters out
    # its own findings before sending.
    coros = [
        runner(
            state=state,
            llm=llm,
            previous_critiques=critiques,
            prior_challenges=prior_challenges,
            round_n=round_n,
        )
        for _, runner in _CHALLENGERS
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)

    flat: list[CrossChallenge] = []
    for (critic_id, _), res in zip(_CHALLENGERS, results):
        if isinstance(res, Exception):
            logger.warning("cross-challenge round %d [%s] raised: %s", round_n, critic_id, res)
            continue
        flat.extend(res)
    return flat


async def run_cross_challenge(state: GraphState, llm: LLMProvider) -> dict:
    """Drive the full cross-challenge flow and return the state delta.

    Returns a dict with keys `challenges`, `challenge_round`, `convergence_signal`
    that LangGraph merges into GraphState. `challenges` uses the operator.add
    reducer, so returning the full flat list here (rather than per-round chunks)
    is equivalent — and cheaper on state-merge churn.
    """
    all_challenges: list[CrossChallenge] = []
    converged = False
    final_round = 0

    for round_n in range(1, MAX_CROSS_CHALLENGE_ROUNDS + 1):
        round_challenges = await _run_round(state, llm, round_n, all_challenges)
        final_round = round_n

        # Early-exit convergence: round 1 produced nothing — no disagreement.
        if round_n == 1 and not round_challenges:
            converged = True
            break

        # After non-first rounds, compare against the most recent prior round
        # to decide convergence.
        if round_n > 1:
            prev_round = [c for c in all_challenges if c.round == round_n - 1]
            converged = _texts_converged(prev_round, round_challenges)

        all_challenges.extend(round_challenges)

        if converged:
            break

    return {
        "challenges": all_challenges,
        "challenge_round": final_round,
        "convergence_signal": converged,
    }
