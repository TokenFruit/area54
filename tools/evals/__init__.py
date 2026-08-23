"""Behavioural evaluation of the team's agents.

The deterministic checks in :mod:`tools.agents` and :mod:`tools.commands` cover
everything decidable by reading a file. They cannot tell you whether the Lead
actually catches a bug, or whether the Tester quietly weakens a failing test
instead of reporting it. That is what these evals are for.

Evals are stochastic. A single trial proves nothing, so every case runs several
times and passes on a threshold rather than on one lucky result.
"""
