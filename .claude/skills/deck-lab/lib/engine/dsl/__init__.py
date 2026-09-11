"""The card-script DSL — schema, validator and the committed script library.

Card text is executed from scripts that are data (ADR 0009 decision 2). This
package holds the half of that which does not need an interpreter:

* `schema.py` — the JSON AST, its closed vocabulary, and a validator that
  returns structured error records rather than a message. The LLM compiler's
  repair loop reads those records; a human reads the same ones.
* `library.py` — the committed scripts in `data/scripts/`, the clause-coverage
  arithmetic, and which census atoms any script exercises.
* `selftest.py` — the checks, run as part of `deck_cli.py selftest`.

Nothing here executes a script. The interpreter is #25's, and it will be a
client of this schema rather than a second opinion about it.
"""
from . import library, schema

__all__ = ["schema", "library"]
