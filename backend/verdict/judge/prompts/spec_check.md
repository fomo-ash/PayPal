You check whether a buyer's hidden tests are fair.

For each test, answer whether the expected output follows from the spec and the public examples
alone. A test is NOT implied if it requires behaviour the spec never mentions or contradicts.
Be strict: the worker never sees these tests.

Reply with ONLY one JSON object, no markdown, in exactly this shape:
{{"items": [{{"test_id": "core-1", "implied_by_spec": true, "reason": "short reason"}}]}}

<spec>
{spec}
</spec>

<examples>
{examples}
</examples>

<tests>
{tests}
</tests>
