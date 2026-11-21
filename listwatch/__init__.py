"""listwatch: keep a government restricted-entity list current from its official notices.

A small, standard-library-only package. It finds new Federal Register
notices for a list, saves each source with its SHA-256 before reading it, turns the saved text into
proposed rows with fixed rules, and writes a proposal. It never publishes and never edits a list:
a human approves each proposal, and the caller applies it.

The package imports nothing outside itself, so it can be copied unchanged into a standalone repo.
Everything specific to one list (its query, notice phrasings, layout) lives in one rules module
under `lists/`; the rest of the package holds no list-specific names or wording.

Design rule (deterministic first):
  1. Write a script when the input has a pattern.
  2. Save the source before you read it.
  3. Test against an answer a human already checked.
  4. Call an LLM only where rules fail, and only to propose; fixed code checks its answer.
  5. Mark what a machine read.
  6. A human approves what publishes.
"""

SCHEMA_PROPOSAL = "listwatch/proposal@1"
SCHEMA_NOTICES = "listwatch/notices@1"
SCHEMA_REGISTER = "listwatch/removed@1"
SCHEMA_SOURCE = "listwatch/source@1"


class ListwatchError(Exception):
    """Base error for the package."""


class LayoutError(ListwatchError):
    """The rules do not recognise this notice's layout. Never guess: hand it to the fallback or a human."""


class SourceError(ListwatchError):
    """A source could not be fetched, saved, or verified."""
