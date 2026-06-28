import json
import unittest
from types import SimpleNamespace

from hermes_tag.context import ContextSelector


def source(user="Alice", thread_id=None):
    return SimpleNamespace(user_id=user, user_name=user, thread_id=thread_id)


def event(text, *, user="Alice", message_id="ask-1", thread_id=None):
    return SimpleNamespace(
        text=text,
        message_id=message_id,
        reply_to_message_id=None,
        source=source(user=user, thread_id=thread_id),
        thread_id=thread_id,
    )


def row(message_id, *, author="Bob", created_at=1.0, text="", media_paths=None, thread_id=None):
    return {
        "message_id": message_id,
        "author": author,
        "created_at": created_at,
        "text": text,
        "media_paths": json.dumps(media_paths or []),
        "thread_id": thread_id,
    }


class ContextDeicticRecentTest(unittest.TestCase):
    def test_deictic_recent_selects_nearest_recent_media(self):
        recent_rows = [
            row("old-image", created_at=10.0, text="older chart", media_paths=["/tmp/old.png"]),
            row("note", created_at=20.0, text="plain text note"),
            row("nearest-image", created_at=30.0, text="latest chart", media_paths=["/tmp/latest.png"]),
        ]

        pack = ContextSelector().select(
            event("What does the image above show?"),
            recent_rows=recent_rows,
            memory_rows=[],
        )

        self.assertEqual(pack.scope, "deictic_recent")
        self.assertFalse(pack.has_explicit_anchor)
        self.assertEqual([r["message_id"] for r in pack.media_rows], ["nearest-image"])
        self.assertIn("nearest-image", [r["message_id"] for r in pack.text_rows])
        self.assertIn(("old-image", "deictic:cap"), pack.excluded)


if __name__ == "__main__":
    unittest.main()
