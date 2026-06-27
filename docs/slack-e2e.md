# Slack E2E smoke

Live workspace smoke for the Slack side of `hermes-tag`.

## Preconditions

- Gateway profile: `shiling-pm` on `192.168.10.78`.
- Test channel: `#hermes-tag-test`.
- `platforms.slack.reply_in_thread: false` so replies stay in the main channel.
- `platforms.slack.require_mention: false` so ambient channel messages can be stored as Tier-0 context.

## Checklist

1. Restart gateway and confirm both platforms connect:
   - Slack Socket Mode connected.
   - Feishu connected.
   - Gateway running with 2 platforms.
2. In `#hermes-tag-test`, send an ambient context message without mentioning the bot.
3. Mention `@Hermes Tag` and ask about the ambient fact.
4. Confirm the bot replies in the main channel and uses the ambient fact.
5. Send ` /tag admin count` as a normal Slack message (leading space avoids native slash-command parsing) and confirm a count reply.
6. Check gateway logs/audit for the inbound Slack message, response readiness, and selected Tier-0 context.

## 2026-06-27 smoke

Evidence token: `E2E-SLACK-20260627`.

Computer Use verified in Slack:

- Ambient message: `E2E-SLACK-20260627 ambient fact: the delivery window is Tuesday.`
- Mention message: `@Hermes Tag For E2E-SLACK-20260627, what is the delivery window?`
- Bot main-channel answer: `Tuesday.`
- Command smoke: ` /tag admin count` returned `tier0=19 tier1=8 standing_jobs=0`.

Remote evidence:

- Restart showed Slack Socket Mode connected, Feishu connected, and gateway running with 2 platforms.
- Gateway log showed the Slack inbound mention and response send at 2026-06-27 09:48.
- Slack Tier-0 DB contained both the ambient fact and the mention question.
- Latest `enhance_event` audit preview included the ambient fact in `channel_context` before the model answer.

Known Slack app nuance:

- Native `/tag` is not registered in the current Slack app, so Slackbot rejects it before Hermes sees it.
- Use ` /tag ...` (leading space) for the current E2E, or add a real Slack slash-command manifest entry later.
