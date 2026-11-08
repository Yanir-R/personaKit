import json


class FakeClient:
    """Returns canned replies in order and records every prompt it was given."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def reply(*memories):
    return json.dumps({"memories": [dict(m) for m in memories]})
