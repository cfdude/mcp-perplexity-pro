---
name: a-conditional-assertion-must-be-seen-firing
kind: process-failure
trigger: Writing a test whose assertion sits inside an `if` or a loop over data read from the system under test (flags checked against annotations, results checked per tool).
cost: In agent-help the flag test read each tool's annotations with `model_dump()`, which returns snake_case keys, and looked for `readOnlyHint`. The `if` never matched, the assertions inside it never ran, and the test passed for every tool while checking nothing. Found only because the tool-level test of the same behaviour failed with the real keys; the mutation that renamed the flag text then showed the first test still green until the key was fixed.
enforced_in: task 1.1 and 2.1 of agent-help (each guard test was mutated once and seen red) and this lesson; the mutation-check rule in CLAUDE.md "Testing" applies to conditional assertions too.
---

A test with `if condition: assert ...` proves nothing until the condition has been seen true.
After writing it, break the behaviour once (rename the output text, delete the entry) and confirm
the test goes red; or assert first that the branch ran (`assert matched >= 1`). When the data comes
from a library's model, print one real value before keying on it (pydantic's `model_dump()` uses
field names, `by_alias=True` uses the wire names).
