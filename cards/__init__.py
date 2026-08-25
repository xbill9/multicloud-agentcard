"""Fetch agent cards from remote native agents, then read them properly.

Four steps, four modules, deliberately separable:

    fetch    what came back, byte for byte, and what it cost to get it
    review   what one card says, measured against the spec
    compare  where the cards disagree with each other
    report   how any of that is rendered

The split exists because the interesting failures live between the steps. A
card that parses is not a card that conforms; a card that conforms is not a
card that agrees with its neighbours; and a run where two peers answered and
one 403'd is a *finding*, not an incomplete run. Keeping the raw bytes all the
way through is what lets the later steps be re-run over a stored specimen
without dialling anything.
"""
