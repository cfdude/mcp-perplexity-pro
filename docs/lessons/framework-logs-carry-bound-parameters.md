---
name: framework-logs-carry-bound-parameters
kind: process-failure
trigger: Adding a logger.exception or exc_info call, or relying on a global redaction filter, in code that stores user or model content through SQLAlchemy.
cost: A failed insert's log record rendered SQLAlchemy's `[parameters: (...)]`, i.e. chat text, answers and job results, and FastMCP's own "Error calling tool" log did the same. The redaction filter removed key-shaped tokens but not content, so stored content reached stderr and the pm2 log files. The recorder already avoided this; three sibling call sites did not.
enforced_in: src/mcp_perplexity_pro/log_setup.py (RedactingFilter strips `[parameters: ...]` blocks from every record), src/mcp_perplexity_pro/server.py (SQLAlchemy errors logged as type plus driver text), tests/test_log_setup.py and tests/test_result_reasons_logs_deletes.py (trigger-forced failures assert no content in the log).
---

Log the exception type and the driver's message, never the exception object with its
parameters, and strip the parameter block centrally as a second layer. Test with a failure
forced by a trigger and assert that none of the stored content appears in the captured log.
