# Specs

One file per feature: `TF-NNN-<slug>.md`, written by the **product-owner**
agent via `/groom`.

A spec is the contract. The Builder implements it, the Tester tests against it,
the Lead reviews against it. If it is not in the spec, it does not get built.

**Status** moves `Draft` → `Approved` → `Shipped`. Only the CPO changes it to
`Approved`, and only once every open question is answered.
