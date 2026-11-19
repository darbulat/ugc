# Profile drafts on this device

Creator and advertiser profile forms in Telegram and MAX save unfinished
fields locally as they change. Role selection offers a shortcut to each
unfinished form. Opening that form offers **Continue filling** and **Start
over** before displaying the saved draft.

Drafts belong to the authenticated UMC user, messenger, role and form mode
(registration or editing). A deleted/recreated account gets a different UMC
user ID and cannot load its previous draft. No initData, verification codes,
consent or verification status is stored in the draft.

**Start over** removes this form's local drafts. Registration starts from
empty/default fields; editing returns to the server's saved profile. Neither
action changes the server profile. Saving a draft never registers a user or
accepts terms. Successful profile submission removes the submitted draft;
errors keep it available for retry. Inputs are locked during submission so
new typing cannot be mistaken for data that the server already accepted.

A city still awaiting confirmation is not restored as confirmed geography.
Confirmed coordinates and selected dates survive interruption. Restarting
or submitting from a stale window cannot revive a registration draft already
cleared in another window. An edit saved in one window preserves a newer
unsent edit in another.

The hint says a draft is saved only after localStorage accepts the write.
Unavailable/full storage shows a warning and leaves ordinary registration
usable. Corrupt, oversized or differently owned records are ignored. Drafts
remain on this device and WebView storage; clearing app data or switching
devices does not transfer them.

Validation: `tests/e2e/test_miniapp_profile_drafts.py` uses real templates and
synthetic requests in Chromium for Telegram/MAX, plus the existing form,
registration recovery and Instagram browser suites. No production requests
or real messages are required.
