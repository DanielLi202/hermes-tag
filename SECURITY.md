# Security

This plugin stores data for approved Feishu group chats locally. The `enabled_chats` allowlist is the storage and processing boundary: messages outside that list should pass through without plugin storage.

## Data handled

- Tier-0: short-term group-chat buffer for `enabled_chats` only.
- Tier-1: long-term memory derived from @-mention interactions.
- Standing jobs and audit events are scoped to enabled chats.

The declared `encryption_posture` is `plaintext-db-on-local-disk`; use host-level disk encryption and filesystem controls if you need encrypted storage at rest.

## Data removal

Admin lifecycle commands such as `/tag admin clear` and disable remove plugin data for the chat, including stored context and standing-job state handled by the plugin.

## Reporting vulnerabilities

Please report vulnerabilities privately to the repo owner via GitHub. Do not include live credentials, private chat transcripts, or Feishu tokens in public issues.

This project is provided with no warranty under the MIT License.
